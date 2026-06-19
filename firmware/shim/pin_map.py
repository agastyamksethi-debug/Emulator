"""
PinMap — resolves an MCU's GPIO pin numbers to simulation net names.

Built from two sources:
  1. The netlist component entry (KiCad pin number → net name)
  2. The MCU descriptor's gpio_map (logical GPIO int → KiCad pin name)

Without a descriptor gpio_map, falls back to parsing KiCad pin names
that look like GPIO numbers ("IO18", "GPIO18", "18", "ADC1_CH0" etc.).

Also stores per-pin capabilities so the shim can reject invalid calls
(e.g. analogRead on an output-only pin).
"""

from __future__ import annotations
import re
from enum import Flag, auto
from dataclasses import dataclass, field


class Cap(Flag):
    """
    Pin capability flags.

    Specific sub-types (ADC1, SPI1, UART0 etc.) identify which hardware
    controller a pin belongs to. Generic aliases (ADC, SPI, UART, I2C) are
    the union of all sub-types and remain valid for backward-compat checks.

    Use specific flags in descriptor pin_caps when the controller matters
    (e.g. ADC2 conflicts with WiFi on ESP32). Use the generic alias when
    you only care whether the capability exists at all.
    """
    DIGITAL_IN  = auto()
    DIGITAL_OUT = auto()

    # ADC controllers
    ADC1 = auto()   # e.g. GPIO32-39 on ESP32
    ADC2 = auto()   # e.g. GPIO0,2,4,12-15,25-27 on ESP32 (conflicts with WiFi)
    ADC  = ADC1 | ADC2

    DAC  = auto()
    PWM  = auto()

    # SPI controllers
    SPI1 = auto()   # e.g. HSPI on ESP32 (default: MISO=12,MOSI=13,CLK=14,CS=15)
    SPI2 = auto()   # e.g. VSPI on ESP32 (default: MISO=19,MOSI=23,CLK=18,CS=5)
    SPI  = SPI1 | SPI2

    # I2C controllers
    I2C0 = auto()
    I2C1 = auto()
    I2C  = I2C0 | I2C1

    # UART controllers
    UART0 = auto()
    UART1 = auto()
    UART2 = auto()
    UART  = UART0 | UART1 | UART2

    INPUT_ONLY = auto()   # no output driver — cannot be driven (ESP32 GPIO34-39)

    DIGITAL = DIGITAL_IN | DIGITAL_OUT
    ANY     = DIGITAL | ADC | DAC | PWM | SPI | I2C | UART


@dataclass
class PinInfo:
    gpio: int
    net: str
    caps: Cap = Cap.ANY     # permissive default — overridden by descriptor
    kicad_pin: str = ""


class PinMap:
    """
    Maps GPIO numbers ↔ net names for one MCU instance.
    Loaded once per MCU node; immutable after construction.
    """

    def __init__(self, reference: str, netlist, descriptor: dict | None = None):
        self._pins: dict[int, PinInfo] = {}    # gpio_num → PinInfo
        self._net_to_gpio: dict[str, int] = {}

        comp = netlist.components.get(reference, {}) if netlist else {}
        kicad_pins: dict[str, str] = comp.get("pins", {})  # kicad_pin → net

        if descriptor and "gpio_map" in descriptor:
            # Descriptor provides explicit {gpio_num_str: kicad_pin_name} map
            gpio_map: dict[str, str] = descriptor["gpio_map"]
            cap_map: dict[str, list[str]] = descriptor.get("pin_caps", {})

            for gpio_str, kicad_pin in gpio_map.items():
                net = kicad_pins.get(kicad_pin, "")
                gpio_num = int(gpio_str)
                caps = _parse_caps(cap_map.get(gpio_str, []))
                info = PinInfo(gpio=gpio_num, net=net, caps=caps, kicad_pin=kicad_pin)
                self._pins[gpio_num] = info
                if net:
                    self._net_to_gpio[net] = gpio_num
        else:
            # Fallback: parse KiCad pin names that look like GPIO numbers
            for kicad_pin, net in kicad_pins.items():
                gpio_num = _parse_gpio_num(kicad_pin)
                if gpio_num is not None:
                    info = PinInfo(gpio=gpio_num, net=net, kicad_pin=kicad_pin)
                    self._pins[gpio_num] = info
                    if net:
                        self._net_to_gpio[net] = gpio_num

    # ----------------------------------------------------------------- lookup

    def net(self, gpio: int) -> str | None:
        info = self._pins.get(gpio)
        return info.net if info else None

    def gpio(self, net_name: str) -> int | None:
        return self._net_to_gpio.get(net_name)

    def caps(self, gpio: int) -> Cap:
        info = self._pins.get(gpio)
        return info.caps if info else Cap.ANY

    def has_cap(self, gpio: int, cap: Cap) -> bool:
        return bool(self.caps(gpio) & cap)

    def all_pins(self) -> list[PinInfo]:
        return list(self._pins.values())

    def __repr__(self):
        return f"<PinMap {len(self._pins)} pins>"


# ----------------------------------------------------------------- helpers ----

def _parse_gpio_num(pin_name: str) -> int | None:
    """Extract integer GPIO number from strings like 'IO18', 'GPIO18', '18'."""
    m = re.match(r'(?:GPIO|IO)?(\d+)$', pin_name.strip(), re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _parse_caps(cap_list: list[str]) -> Cap:
    """Convert a list of capability strings from the descriptor to Cap flags."""
    if not cap_list:
        return Cap.ANY
    mapping = {
        "digital_in":  Cap.DIGITAL_IN,
        "digital_out": Cap.DIGITAL_OUT,
        # ADC — use specific controller when it matters
        "adc":         Cap.ADC,
        "adc1":        Cap.ADC1,
        "adc2":        Cap.ADC2,
        "dac":         Cap.DAC,
        "pwm":         Cap.PWM,
        # SPI — use specific controller to distinguish buses
        "spi":         Cap.SPI,
        "spi1":        Cap.SPI1,
        "spi2":        Cap.SPI2,
        # I2C
        "i2c":         Cap.I2C,
        "i2c0":        Cap.I2C0,
        "i2c1":        Cap.I2C1,
        # UART — use specific controller to enforce correct TX/RX assignment
        "uart":        Cap.UART,
        "uart0":       Cap.UART0,
        "uart1":       Cap.UART1,
        "uart2":       Cap.UART2,
        "input_only":  Cap.INPUT_ONLY,
    }
    result = Cap(0)
    for c in cap_list:
        result |= mapping.get(c.lower(), Cap(0))
    return result
