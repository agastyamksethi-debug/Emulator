"""
Arduino API shim — maps Arduino/ESP32 API calls to simulation bus operations.

One shim instance per MCU node. The MCU node holds a reference to its shim
and calls these methods from its firmware execution context.

Pin validation is enforced against the PinMap capabilities. Violations raise
SimPinError so firmware bugs are caught before hardware is fabbed.

Covered:
  GPIO     — pinMode, digitalWrite, digitalRead
  ADC      — analogRead (12-bit, 0–4095, Vref from descriptor)
  DAC      — dacWrite (8-bit, ESP32-style)
  PWM      — analogWrite / ledcWrite (simplified: duty → DC voltage)
  I2C      — Wire object (beginTransmission, write, endTransmission,
               requestFrom, read, available)
  SPI      — SPI object (beginTransaction, transfer, endTransaction)
  UART     — Serial / Serial1 / Serial2 objects
  Timing   — millis(), micros(), delay() (advances simulation time)
  Math     — map(), constrain(), min(), max()
"""

from __future__ import annotations
from collections import deque
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bus import SimBus
    from core.runner import SimRunner
    from firmware.shim.pin_map import PinMap, Cap


# ---------------------------------------------------------------- constants --

INPUT       = 0x00
OUTPUT      = 0x01
INPUT_PULLUP= 0x02
HIGH        = 1
LOW         = 0


class SimPinError(Exception):
    """Raised when firmware uses a pin in a way its hardware doesn't support."""


# --------------------------------------------------------------- Wire (I2C) --

class _Wire:
    def __init__(self, bus: SimBus, pin_map: PinMap):
        self._bus = bus
        self._pin_map = pin_map
        self._addr: int = 0
        self._tx_buf: list[int] = []
        self._rx_buf: deque[int] = deque()
        self._sda_pin: int | None = None
        self._scl_pin: int | None = None

    def begin(self, sda: int | None = None, scl: int | None = None):
        """Wire.begin() or Wire.begin(sda, scl) for custom pin assignment."""
        if sda is not None:
            self._sda_pin = sda
        if scl is not None:
            self._scl_pin = scl

    def beginTransmission(self, address: int):
        self._addr = address & 0x7F
        self._tx_buf.clear()

    def write(self, data):
        if isinstance(data, int):
            self._tx_buf.append(data & 0xFF)
        else:
            self._tx_buf.extend(b & 0xFF for b in data)

    def endTransmission(self, stop: bool = True) -> int:
        """Returns 0 on success (ACK), 2 on NAK (device not found)."""
        if not self._tx_buf:
            return 0
        register = self._tx_buf[0]
        payload  = bytes(self._tx_buf[1:]) if len(self._tx_buf) > 1 else b""
        ok = self._bus.i2c_write(self._addr, register, payload)
        self._tx_buf.clear()
        return 0 if ok else 2

    def requestFrom(self, address: int, length: int, stop: bool = True) -> int:
        data = self._bus.i2c_read(address & 0x7F, 0, length)
        self._rx_buf.clear()
        self._rx_buf.extend(data)
        return len(data)

    def available(self) -> int:
        return len(self._rx_buf)

    def read(self) -> int:
        return self._rx_buf.popleft() if self._rx_buf else -1


# ---------------------------------------------------------------- SPI --------

class _SPISettings:
    def __init__(self, clock: int = 1_000_000, bit_order: int = 1, mode: int = 0):
        self.clock = clock
        self.bit_order = bit_order   # MSBFIRST=1, LSBFIRST=0
        self.mode = mode


MSBFIRST = 1
LSBFIRST = 0
SPI_MODE0 = 0
SPI_MODE1 = 1
SPI_MODE2 = 2
SPI_MODE3 = 3


class _SPI:
    def __init__(self, bus: SimBus, pin_map: PinMap, shim: ArduinoShim):
        self._bus = bus
        self._pin_map = pin_map
        self._shim = shim
        self._settings: _SPISettings = _SPISettings()

    def begin(self):
        pass

    def end(self):
        pass

    def beginTransaction(self, settings: _SPISettings):
        self._settings = settings

    def endTransaction(self):
        pass

    def transfer(self, data) -> int | bytes:
        if isinstance(data, int):
            result = self._bus.spi_transfer(bytes([data & 0xFF]))
            return result[0] if result else 0
        else:
            return self._bus.spi_transfer(bytes(data))

    def transfer16(self, data: int) -> int:
        b = bytes([( data >> 8) & 0xFF, data & 0xFF])
        r = self._bus.spi_transfer(b)
        return (r[0] << 8) | r[1]

    @staticmethod
    def SPISettings(clock: int = 1_000_000, bit_order: int = MSBFIRST,
                    mode: int = SPI_MODE0) -> _SPISettings:
        return _SPISettings(clock, bit_order, mode)


# --------------------------------------------------------------- Serial ------

class _Serial:
    def __init__(self, bus: SimBus, node_id: str, port: int = 0):
        self._bus = bus
        self._node_id = node_id
        self._port = port
        self._log: list[str] = []     # captured output for testing

    def begin(self, baud: int = 115200, *args):
        pass

    def end(self):
        pass

    def print(self, value, base: int | None = None):
        s = _format(value, base)
        self._log.append(s)
        self._bus.uart_write(self._node_id, self._port, s.encode())

    def println(self, value="", base: int | None = None):
        s = _format(value, base) + "\n"
        self._log.append(s)
        self._bus.uart_write(self._node_id, self._port, s.encode())

    def printf(self, fmt: str, *args):
        s = fmt % args
        self._log.append(s)
        self._bus.uart_write(self._node_id, self._port, s.encode())

    def available(self) -> int:
        return self._bus.uart.available(self._node_id, self._port)

    def read(self) -> int:
        b = self._bus.uart_read(self._node_id, self._port, 1)
        return b[0] if b else -1

    def write(self, data) -> int:
        if isinstance(data, int):
            data = bytes([data & 0xFF])
        self._bus.uart_write(self._node_id, self._port, bytes(data))
        return len(data)

    def flush(self):
        pass

    def get_log(self) -> list[str]:
        return list(self._log)


def _format(value, base: int | None) -> str:
    if base == 16:
        return hex(int(value))
    if base == 2:
        return bin(int(value))
    if base == 8:
        return oct(int(value))
    return str(value)


# ---------------------------------------------------------- ArduinoShim ------

class ArduinoShim:
    """
    Drop-in Arduino/ESP32 API surface for firmware running in simulation.

    Usage (inside an MCU node's firmware runner):
        shim = ArduinoShim(node_id="U1", bus=bus, runner=runner, pin_map=pm)
        shim.pinMode(18, OUTPUT)
        shim.digitalWrite(18, HIGH)
        val = shim.analogRead(34)
    """

    def __init__(self, node_id: str, bus: SimBus, runner: SimRunner,
                 pin_map: PinMap, adc_bits: int = 12,
                 adc_vref: float = 3.3, dac_bits: int = 8):
        self._id = node_id
        self._bus = bus
        self._runner = runner
        self._pin_map = pin_map
        self._adc_max = (1 << adc_bits) - 1
        self._adc_vref = adc_vref
        self._dac_max = (1 << dac_bits) - 1
        self._pin_modes: dict[int, int] = {}
        self._cs_pins: set[int] = set()   # pins currently used as SPI CS

        # Public API objects (match Arduino global variable names)
        self.Wire    = _Wire(bus, pin_map)
        self.Wire1   = _Wire(bus, pin_map)
        self.SPI     = _SPI(bus, pin_map, self)
        self.Serial  = _Serial(bus, node_id, port=0)
        self.Serial1 = _Serial(bus, node_id, port=1)
        self.Serial2 = _Serial(bus, node_id, port=2)

    # ----------------------------------------------------------- GPIO --------

    def pinMode(self, pin: int, mode: int):
        from firmware.shim.pin_map import Cap
        if mode == OUTPUT and not self._pin_map.has_cap(pin, Cap.DIGITAL_OUT):
            if self._pin_map.has_cap(pin, Cap.INPUT_ONLY):
                raise SimPinError(f"GPIO{pin} is input-only — cannot set OUTPUT")
        self._pin_modes[pin] = mode

    def digitalWrite(self, pin: int, value: int):
        from firmware.shim.pin_map import Cap
        if not self._pin_map.has_cap(pin, Cap.DIGITAL_OUT):
            raise SimPinError(f"GPIO{pin} cannot be used as digital output")
        net = self._pin_map.net(pin)
        if net is None:
            return
        high = bool(value)
        # If this pin is wired to a known SPI CS net, also manage SPI CS state
        cs_pin = self._bus.cs_pin_for_net(net)
        if cs_pin is not None:
            if not high:
                self._bus.spi_assert_cs(cs_pin)
                self._cs_pins.add(pin)
            else:
                self._bus.spi_deassert_cs(cs_pin)
                self._cs_pins.discard(pin)
        self._bus.drive_digital(net, self._id, high)

    def digitalRead(self, pin: int) -> int:
        from firmware.shim.pin_map import Cap
        if not self._pin_map.has_cap(pin, Cap.DIGITAL_IN):
            raise SimPinError(f"GPIO{pin} cannot be read as digital input")
        net = self._pin_map.net(pin)
        if net is None:
            return 0
        return self._bus.read_digital(net)

    # ----------------------------------------------------------- ADC ---------

    def analogRead(self, pin: int) -> int:
        """Returns 0–4095 (12-bit) proportional to net voltage / adc_vref."""
        from firmware.shim.pin_map import Cap
        if not self._pin_map.has_cap(pin, Cap.ADC):
            raise SimPinError(f"GPIO{pin} does not have ADC capability")
        net = self._pin_map.net(pin)
        if net is None:
            return 0
        voltage = self._bus.read_voltage(net)
        raw = int(voltage / self._adc_vref * self._adc_max)
        return max(0, min(self._adc_max, raw))

    def analogReadMilliVolts(self, pin: int) -> int:
        voltage = self._bus.read_voltage(self._pin_map.net(pin) or "")
        return int(voltage * 1000)

    def analogSetAttenuation(self, attenuation: int):
        pass   # ESP32-specific — no-op in simulation

    # ----------------------------------------------------------- DAC ---------

    def dacWrite(self, pin: int, value: int):
        """ESP32 8-bit DAC — drives an analog voltage onto the net."""
        from firmware.shim.pin_map import Cap
        if not self._pin_map.has_cap(pin, Cap.DAC):
            raise SimPinError(f"GPIO{pin} does not have DAC capability")
        net = self._pin_map.net(pin)
        if net is None:
            return
        voltage = (value / self._dac_max) * self._adc_vref
        self._bus.drive(net, self._id, voltage)

    # ----------------------------------------------------------- PWM ---------

    def analogWrite(self, pin: int, value: int):
        """Simplified PWM: maps duty 0–255 to proportional DC voltage."""
        from firmware.shim.pin_map import Cap
        if not self._pin_map.has_cap(pin, Cap.PWM):
            raise SimPinError(f"GPIO{pin} does not support PWM")
        net = self._pin_map.net(pin)
        if net is None:
            return
        voltage = (value / 255.0) * self._adc_vref
        self._bus.drive(net, self._id, voltage)

    def ledcWrite(self, channel: int, duty: int):
        """ESP32 LEDC PWM — maps duty to voltage on the attached pin."""
        # Channel → pin mapping is set by ledcAttachPin; simplification: no-op
        pass

    def ledcAttachPin(self, pin: int, channel: int):
        pass

    def ledcSetup(self, channel: int, freq: float, resolution: int):
        pass

    # --------------------------------------------------------- timing --------

    def millis(self) -> int:
        return int(self._runner.elapsed_ms)

    def micros(self) -> int:
        return int(self._runner.elapsed_ms * 1000)

    def delay(self, ms: int):
        """Advance simulation time by ms milliseconds."""
        self._runner.run(float(ms))

    def delayMicroseconds(self, us: int):
        self._runner.run(us / 1000.0)

    # ---------------------------------------------------------- helpers ------

    @staticmethod
    def map(x, in_min, in_max, out_min, out_max) -> float:
        return (x - in_min) * (out_max - out_min) / (in_max - in_min) + out_min

    @staticmethod
    def constrain(x, lo, hi):
        return lo if x < lo else (hi if x > hi else x)

    @staticmethod
    def min(a, b):
        return a if a < b else b

    @staticmethod
    def max(a, b):
        return a if a > b else b
