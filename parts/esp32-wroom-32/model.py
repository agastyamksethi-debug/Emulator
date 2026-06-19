"""
ESP32-WROOM-32 Simulation Model
================================
Complete MCU simulation with:
- 34 GPIO pins with full I/O capability
- 2x 12-bit ADC (18 channels total)
- 2x 8-bit DAC
- 3x UART interfaces
- 4x SPI interfaces
- 2x I2C interfaces
- 16x LEDC PWM channels
- 4x general timers
- 10x capacitive touch channels
- Real-time firmware execution via Arduino shim
"""

from core.node import Node
from firmware.shim.pin_map import PinMap
from firmware.shim.arduino_api import ArduinoShim
from typing import Dict, Optional, Tuple, List
import time


class ESP32WROOM32Node(Node):
    """Dual-core 32-bit MCU with WiFi/BT and comprehensive analog/digital I/O"""

    PART_ID = "esp32-wroom-32"

    def __init__(self, instance_id: str, descriptor: dict):
        """Initialize the ESP32 MCU node with all internal registers and state"""
        super().__init__(instance_id, descriptor)

        # ─────────────────────────────────────────────────────────────
        # GPIO STATE
        # ─────────────────────────────────────────────────────────────
        self.gpio_levels: Dict[int, int] = {i: 0 for i in range(40)}  # GPIO0-39 levels (0 or 1)
        self.gpio_modes: Dict[int, str] = {}  # "input", "output", "adc", "dac", "pwm"
        self.gpio_pull: Dict[int, str] = {}  # "up", "down", "floating"
        self.gpio_drive_strength: Dict[int, int] = {i: 20 for i in range(40)}  # mA

        # ─────────────────────────────────────────────────────────────
        # ADC STATE
        # ─────────────────────────────────────────────────────────────
        self.adc1_readings: Dict[int, int] = {i: 0 for i in range(8)}  # 8 ADC1 channels
        self.adc2_readings: Dict[int, int] = {i: 0 for i in range(10)}  # 10 ADC2 channels
        self.adc_attenuation: Dict[int, Dict[int, int]] = {
            1: {i: 0 for i in range(8)},    # 0=0dB, 1=2.5dB, 2=6dB, 3=11dB
            2: {i: 0 for i in range(10)}
        }
        self.adc_calibration_offset: Dict[int, int] = {1: 0, 2: 0}
        self.adc_sample_count = 0
        self.adc_enabled = False

        # ─────────────────────────────────────────────────────────────
        # DAC STATE
        # ─────────────────────────────────────────────────────────────
        self.dac1_value: int = 0  # 8-bit (GPIO25)
        self.dac2_value: int = 0  # 8-bit (GPIO26)
        self.dac1_enabled = False
        self.dac2_enabled = False
        self.dac_settling_time_us = 10

        # ─────────────────────────────────────────────────────────────
        # PWM/LEDC STATE
        # ─────────────────────────────────────────────────────────────
        self.ledc_timers: Dict[int, Dict] = {}  # Timer configurations
        self.ledc_channels: Dict[int, Dict] = {}  # PWM channel state
        for ch in range(16):
            self.ledc_channels[ch] = {
                "timer": 0,
                "duty": 0,
                "frequency_hz": 5000,
                "resolution": 13,
                "enabled": False,
                "gpio": None
            }

        # ─────────────────────────────────────────────────────────────
        # UART STATE
        # ─────────────────────────────────────────────────────────────
        self.uart_configs = {
            0: {"baud": 115200, "data_bits": 8, "stop_bits": 1, "parity": "none", "enabled": True},
            1: {"baud": 115200, "data_bits": 8, "stop_bits": 1, "parity": "none", "enabled": False},
            2: {"baud": 115200, "data_bits": 8, "stop_bits": 1, "parity": "none", "enabled": False}
        }
        self.uart_rx_buffer = {0: [], 1: [], 2: []}
        self.uart_tx_buffer = {0: [], 1: [], 2: []}

        # ─────────────────────────────────────────────────────────────
        # TIMER STATE
        # ─────────────────────────────────────────────────────────────
        self.timers: Dict[int, Dict] = {}
        for i in range(4):
            self.timers[i] = {
                "counter": 0,
                "alarm": 0,
                "enabled": False,
                "autoreload": False,
                "divider": 80,  # Clock divider
                "interrupt_enabled": False,
                "interrupt_fired": False
            }

        # ─────────────────────────────────────────────────────────────
        # WATCHDOG STATE
        # ─────────────────────────────────────────────────────────────
        self.watchdog_enabled = False
        self.watchdog_timeout_ms = 5000
        self.watchdog_elapsed_ms = 0

        # ─────────────────────────────────────────────────────────────
        # TOUCH SENSOR STATE
        # ─────────────────────────────────────────────────────────────
        self.touch_values: Dict[int, int] = {i: 0 for i in range(10)}
        self.touch_threshold = 400
        self.touch_triggered: Dict[int, bool] = {i: False for i in range(10)}

        # ─────────────────────────────────────────────────────────────
        # SYSTEM STATE
        # ─────────────────────────────────────────────────────────────
        self.core_clock_mhz = 240
        self.apb_clock_mhz = 80
        self.rtc_slow_clock_hz = 150000
        self.sleep_mode = "none"  # "none", "light", "deep"
        self.chip_temperature_c = 25.0
        self.supply_current_ua = 80000

        # ─────────────────────────────────────────────────────────────
        # FIRMWARE INTERFACE
        # ─────────────────────────────────────────────────────────────
        self._firmware: Optional[Tuple] = None  # (setup_fn, loop_fn)
        self._pin_map: Optional[PinMap] = None
        self.shim: Optional[ArduinoShim] = None
        self._bus = None
        self._runner = None

        # ─────────────────────────────────────────────────────────────
        # RUNTIME METRICS
        # ─────────────────────────────────────────────────────────────
        self.boot_time_ms = 0
        self.last_activity_ms = 0

    def reset(self):
        """Reset MCU to power-on defaults (called after instantiation or RST assertion)"""
        # GPIO state reset
        for i in range(40):
            self.gpio_levels[i] = 0
            self.gpio_modes[i] = "input"
            self.gpio_pull[i] = "floating"

        # Strapping pin defaults
        self.gpio_levels[0] = 0  # IO0 strapping
        self.gpio_levels[2] = 0  # IO2 strapping
        self.gpio_levels[12] = 1  # IO12 strapping (internal pull-up)
        self.gpio_levels[15] = 0  # IO15 strapping

        # ADC reset
        for adc in [1, 2]:
            for ch in range(10):
                if adc == 1 and ch >= 8:
                    break
                self.adc_attenuation[adc][ch] = 0  # 0dB attenuation

        # DAC reset
        self.dac1_value = 0
        self.dac2_value = 0
        self.dac1_enabled = False
        self.dac2_enabled = False

        # PWM/LEDC reset
        for ch in range(16):
            self.ledc_channels[ch]["duty"] = 0
            self.ledc_channels[ch]["frequency_hz"] = 5000
            self.ledc_channels[ch]["enabled"] = False

        # Timer reset
        for i in range(4):
            self.timers[i]["counter"] = 0
            self.timers[i]["enabled"] = False

        # Watchdog reset
        self.watchdog_enabled = False
        self.watchdog_elapsed_ms = 0

        # System reset
        self.chip_temperature_c = 25.0
        self.sleep_mode = "none"
        self.boot_time_ms = self._runner.elapsed_ms if self._runner else 0

    def tick(self, dt_ms: float):
        """
        Advance internal state by dt_ms milliseconds.
        Called by the simulator each tick cycle.
        """
        # ─────────────────────────────────────────────────────────────
        # TIMER UPDATES
        # ─────────────────────────────────────────────────────────────
        for timer_idx, timer in self.timers.items():
            if timer["enabled"]:
                # Increment counter based on clock divider
                increment = (dt_ms * self.core_clock_mhz * 1000) / timer["divider"]
                timer["counter"] += int(increment)

                # Check for alarm
                if timer["counter"] >= timer["alarm"]:
                    timer["interrupt_fired"] = True
                    if timer["autoreload"]:
                        timer["counter"] = 0

        # ─────────────────────────────────────────────────────────────
        # WATCHDOG TIMER
        # ─────────────────────────────────────────────────────────────
        if self.watchdog_enabled:
            self.watchdog_elapsed_ms += dt_ms
            if self.watchdog_elapsed_ms >= self.watchdog_timeout_ms:
                # Watchdog would trigger reset in real hardware
                self.watchdog_elapsed_ms = 0

        # Feed estimated power dissipation to the thermal engine.
        # The thermal model in physics/thermal.py reads self.power_dissipation
        # each tick to compute junction temperature — don't duplicate it here.
        self._update_supply_current()
        self.power_dissipation = (
            self.descriptor.get("vdd_nom", 3.3) * self.supply_current_ua
        ) / 1e6
        # chip_temperature_c mirrors the thermal engine's result for convenience
        self.chip_temperature_c = self.temperature

    def attach(self, netlist, bus, runner):
        """Called once after netlist is loaded — builds PinMap and ArduinoShim."""
        self._bus     = bus
        self._runner  = runner
        self._netlist = netlist
        self._pin_map = PinMap(self.id, netlist, self.descriptor)
        self.shim = ArduinoShim(
            node_id  = self.id,
            bus      = bus,
            runner   = runner,
            pin_map  = self._pin_map,
            adc_bits = 12,
            adc_vref = 1.1,   # default 0 dB range; analogSetAttenuation() expands it
            dac_bits = 8,
        )

    def load_firmware(self, setup_fn, loop_fn):
        """Accept Arduino-style firmware functions"""
        self._firmware = (setup_fn, loop_fn)

    def run_setup(self):
        if self._firmware:
            self._firmware[0](self.shim)

    def run_loop(self):
        if self._firmware:
            self._firmware[1](self.shim)

    # ─────────────────────────────────────────────────────────────
    # GPIO INTERFACE
    # ─────────────────────────────────────────────────────────────

    def gpio_read(self, gpio: int) -> int:
        """Read GPIO logic level (0 or 1)"""
        if 0 <= gpio < 40:
            return self.gpio_levels[gpio]
        return 0

    def gpio_write(self, gpio: int, value: int):
        """Write GPIO logic level (0 or 1)"""
        if 0 <= gpio < 40:
            self.gpio_levels[gpio] = 1 if value else 0
            self.last_activity_ms = self._runner.elapsed_ms if self._runner else 0

    def gpio_mode(self, gpio: int, mode: str):
        """Set GPIO mode (input, output, adc, dac, pwm)"""
        if 0 <= gpio < 40:
            self.gpio_modes[gpio] = mode

    def gpio_pullup(self, gpio: int, enable: bool):
        """Enable/disable internal pull-up"""
        if 0 <= gpio < 40:
            self.gpio_pull[gpio] = "up" if enable else "floating"

    def gpio_pulldown(self, gpio: int, enable: bool):
        """Enable/disable internal pull-down"""
        if 0 <= gpio < 40:
            self.gpio_pull[gpio] = "down" if enable else "floating"

    # ─────────────────────────────────────────────────────────────
    # ADC INTERFACE
    # ─────────────────────────────────────────────────────────────

    def adc_read(self, adc_num: int, channel: int, attenuation: int = 0) -> int:
        """
        Read ADC value (12-bit, 0-4095).
        attenuation: 0=0dB, 1=2.5dB, 2=6dB, 3=11dB
        """
        _t = int(self._runner.elapsed_ms) if self._runner else 0
        if adc_num == 1 and 0 <= channel < 8:
            # Simulate ADC noise and quantization
            value = self.adc1_readings[channel]
            noise = (_t % 16) - 8  # ±8 LSB noise
            return min(4095, max(0, value + noise))

        elif adc_num == 2 and 0 <= channel < 10:
            value = self.adc2_readings[channel]
            noise = (_t % 16) - 8
            return min(4095, max(0, value + noise))

        return 0

    def adc_set_reading(self, adc_num: int, channel: int, value_12bit: int):
        """Set ADC simulated reading (for testing/injection)"""
        if adc_num == 1 and 0 <= channel < 8:
            self.adc1_readings[channel] = min(4095, max(0, value_12bit))
        elif adc_num == 2 and 0 <= channel < 10:
            self.adc2_readings[channel] = min(4095, max(0, value_12bit))

    def adc_enable(self, enable: bool):
        """Enable/disable ADC"""
        self.adc_enabled = enable

    # ─────────────────────────────────────────────────────────────
    # DAC INTERFACE
    # ─────────────────────────────────────────────────────────────

    def dac_write(self, dac_num: int, value_8bit: int):
        """Write 8-bit DAC output (0-255 maps to 0-3.3V)"""
        if dac_num == 1:
            self.dac1_value = min(255, max(0, value_8bit))
            self.dac1_enabled = True
            self.last_activity_ms = self._runner.elapsed_ms if self._runner else 0
        elif dac_num == 2:
            self.dac2_value = min(255, max(0, value_8bit))
            self.dac2_enabled = True
            self.last_activity_ms = self._runner.elapsed_ms if self._runner else 0

    def dac_read(self, dac_num: int) -> int:
        """Read current DAC output value"""
        if dac_num == 1:
            return self.dac1_value
        elif dac_num == 2:
            return self.dac2_value
        return 0

    def dac_voltage(self, dac_num: int) -> float:
        """Get DAC output voltage in volts"""
        value = self.dac_read(dac_num)
        return (value / 255.0) * 3.3

    # ─────────────────────────────────────────────────────────────
    # PWM/LEDC INTERFACE
    # ─────────────────────────────────────────────────────────────

    def ledc_setup(self, channel: int, gpio: int, frequency_hz: int, resolution: int, duty_percent: int = 50):
        """Setup LEDC PWM channel"""
        if 0 <= channel < 16:
            self.ledc_channels[channel]["gpio"] = gpio
            self.ledc_channels[channel]["frequency_hz"] = frequency_hz
            self.ledc_channels[channel]["resolution"] = resolution
            self.ledc_channels[channel]["duty"] = int((duty_percent / 100.0) * ((1 << resolution) - 1))
            self.ledc_channels[channel]["enabled"] = True
            self.last_activity_ms = self._runner.elapsed_ms if self._runner else 0

    def ledc_write(self, channel: int, duty: int):
        """Write PWM duty cycle (0 to 2^resolution - 1)"""
        if 0 <= channel < 16:
            max_duty = (1 << self.ledc_channels[channel]["resolution"]) - 1
            self.ledc_channels[channel]["duty"] = min(max_duty, max(0, duty))

    def ledc_read_duty(self, channel: int) -> int:
        """Read current PWM duty value"""
        if 0 <= channel < 16:
            return self.ledc_channels[channel]["duty"]
        return 0

    # ─────────────────────────────────────────────────────────────
    # UART INTERFACE
    # ─────────────────────────────────────────────────────────────

    def uart_write(self, uart_num: int, data: bytes):
        """Write data to UART TX buffer"""
        if 0 <= uart_num < 3:
            self.uart_tx_buffer[uart_num].extend(data)
            self.last_activity_ms = self._runner.elapsed_ms if self._runner else 0

    def uart_read(self, uart_num: int, length: int = 1) -> bytes:
        """Read data from UART RX buffer"""
        if 0 <= uart_num < 3:
            result = bytes(self.uart_rx_buffer[uart_num][:length])
            self.uart_rx_buffer[uart_num] = self.uart_rx_buffer[uart_num][length:]
            return result
        return b""

    def uart_available(self, uart_num: int) -> int:
        """Get number of bytes available in RX buffer"""
        if 0 <= uart_num < 3:
            return len(self.uart_rx_buffer[uart_num])
        return 0

    def uart_config(self, uart_num: int, baud: int, data_bits: int = 8, stop_bits: int = 1):
        """Configure UART parameters"""
        if 0 <= uart_num < 3:
            self.uart_configs[uart_num]["baud"] = baud
            self.uart_configs[uart_num]["data_bits"] = data_bits
            self.uart_configs[uart_num]["stop_bits"] = stop_bits

    # ─────────────────────────────────────────────────────────────
    # TIMER INTERFACE
    # ─────────────────────────────────────────────────────────────

    def timer_setup(self, timer_idx: int, divider: int = 80, autoreload: bool = False):
        """Configure timer"""
        if 0 <= timer_idx < 4:
            self.timers[timer_idx]["divider"] = divider
            self.timers[timer_idx]["autoreload"] = autoreload

    def timer_start(self, timer_idx: int):
        """Start timer"""
        if 0 <= timer_idx < 4:
            self.timers[timer_idx]["enabled"] = True

    def timer_stop(self, timer_idx: int):
        """Stop timer"""
        if 0 <= timer_idx < 4:
            self.timers[timer_idx]["enabled"] = False

    def timer_set_alarm(self, timer_idx: int, alarm_value: int):
        """Set timer alarm value"""
        if 0 <= timer_idx < 4:
            self.timers[timer_idx]["alarm"] = alarm_value

    def timer_get_count(self, timer_idx: int) -> int:
        """Get current timer count"""
        if 0 <= timer_idx < 4:
            return self.timers[timer_idx]["counter"]
        return 0

    def timer_has_fired(self, timer_idx: int) -> bool:
        """Check if timer interrupt has fired"""
        if 0 <= timer_idx < 4:
            fired = self.timers[timer_idx]["interrupt_fired"]
            self.timers[timer_idx]["interrupt_fired"] = False
            return fired
        return False

    # ─────────────────────────────────────────────────────────────
    # TOUCH SENSOR INTERFACE
    # ─────────────────────────────────────────────────────────────

    def touch_read(self, channel: int) -> int:
        """Read capacitive touch sensor value"""
        if 0 <= channel < 10:
            return self.touch_values[channel]
        return 0

    def touch_set_value(self, channel: int, value: int):
        """Set touch sensor simulated value"""
        if 0 <= channel < 10:
            self.touch_values[channel] = value
            self.touch_triggered[channel] = value < self.touch_threshold

    def touch_is_triggered(self, channel: int) -> bool:
        """Check if touch sensor is below threshold (triggered)"""
        if 0 <= channel < 10:
            return self.touch_triggered[channel]
        return False

    # ─────────────────────────────────────────────────────────────
    # SYSTEM INTERFACE
    # ─────────────────────────────────────────────────────────────

    def get_uptime_ms(self) -> float:
        """Get milliseconds since boot"""
        now = self._runner.elapsed_ms if self._runner else 0
        return now - self.boot_time_ms

    def set_sleep_mode(self, mode: str):
        """Set sleep mode (none, light, deep)"""
        self.sleep_mode = mode

    def get_chip_temperature(self) -> float:
        """Get simulated chip temperature in Celsius"""
        return self.chip_temperature_c

    def get_supply_current(self) -> int:
        """Get estimated supply current in µA"""
        return int(self.supply_current_ua)

    def watchdog_enable(self, timeout_ms: int):
        """Enable watchdog timer"""
        self.watchdog_enabled = True
        self.watchdog_timeout_ms = timeout_ms
        self.watchdog_elapsed_ms = 0

    def watchdog_disable(self):
        """Disable watchdog timer"""
        self.watchdog_enabled = False

    def watchdog_feed(self):
        """Reset watchdog counter"""
        self.watchdog_elapsed_ms = 0

    # ─────────────────────────────────────────────────────────────
    # INTERNAL HELPERS
    # ─────────────────────────────────────────────────────────────

    def _update_supply_current(self):
        """
        Update supply current estimate based on active peripherals.
        Real-world typical ranges:
        - Idle: 10-20 mA
        - WiFi RX: 80-100 mA
        - WiFi TX: 120-150 mA
        """
        base_ua = 10000  # 10 mA minimum

        # Add GPIO output drive current
        for gpio in range(40):
            if self.gpio_modes.get(gpio) == "output" and self.gpio_levels.get(gpio) == 1:
                base_ua += self.gpio_drive_strength.get(gpio, 20) * 1000

        # Add ADC current
        if self.adc_enabled:
            base_ua += 5000

        # Add DAC current
        if self.dac1_enabled or self.dac2_enabled:
            base_ua += 10000

        # Add PWM current
        for ch in range(16):
            if self.ledc_channels[ch]["enabled"]:
                duty_percent = (self.ledc_channels[ch]["duty"] / ((1 << self.ledc_channels[ch]["resolution"]) - 1)) * 100
                base_ua += int(5000 * (duty_percent / 100.0))

        # Add UART current
        for uart_idx in range(3):
            if self.uart_configs[uart_idx]["enabled"]:
                base_ua += 2000

        # Add timer current
        for timer_idx in range(4):
            if self.timers[timer_idx]["enabled"]:
                base_ua += 1000

        self.supply_current_ua = base_ua

    def inject(self, **kwargs) -> None:
        """
        Test/debugging hook: inject simulated values onto bus nets.

        Examples:
          inject(adc1_ch4_mv=2500)      # Drive GPIO32 (ADC1 ch4) net to 2500 mV
          inject(adc2_ch7_mv=1800)      # Drive GPIO27 (ADC2 ch7) net to 1800 mV
          inject(gpio5_mv=3300)         # Drive GPIO5 net to 3.3 V
          inject(gpio5_level=1)         # Drive GPIO5 net high (3.3 V)
          inject(touch_ch0_value=300)   # Set touch sensor 0 capacitance value
          inject(temperature_c=45)      # Override chip temperature
        """
        for key, value in kwargs.items():
            if key.startswith("adc1_ch") and key.endswith("_mv"):
                ch_str = key[len("adc1_ch"):-len("_mv")]
                if ch_str.isdigit():
                    gpio_label = (self.descriptor.get("adc_specs", {})
                                  .get("adc1", {})
                                  .get("channel_map", {})
                                  .get(ch_str, ""))
                    if gpio_label.startswith("GPIO"):
                        self._drive_gpio_mv(int(gpio_label[4:]), value)

            elif key.startswith("adc2_ch") and key.endswith("_mv"):
                ch_str = key[len("adc2_ch"):-len("_mv")]
                if ch_str.isdigit():
                    gpio_label = (self.descriptor.get("adc_specs", {})
                                  .get("adc2", {})
                                  .get("channel_map", {})
                                  .get(ch_str, ""))
                    if gpio_label.startswith("GPIO"):
                        self._drive_gpio_mv(int(gpio_label[4:]), value)

            elif key.startswith("gpio") and key.endswith("_mv"):
                gpio_str = key[len("gpio"):-len("_mv")]
                if gpio_str.isdigit():
                    self._drive_gpio_mv(int(gpio_str), value)

            elif key.startswith("gpio") and key.endswith("_level"):
                gpio_str = key[len("gpio"):-len("_level")]
                if gpio_str.isdigit():
                    gpio = int(gpio_str)
                    self.gpio_write(gpio, value)
                    self._drive_gpio_mv(gpio, 3300.0 if value else 0.0)

            elif key.startswith("touch_ch") and key.endswith("_value"):
                ch_str = key[len("touch_ch"):-len("_value")]
                if ch_str.isdigit():
                    self.touch_set_value(int(ch_str), value)

            elif key == "temperature_c":
                self.chip_temperature_c = float(value)

    def _drive_gpio_mv(self, gpio_num: int, mv: float) -> None:
        """Drive a GPIO's connected bus net to the given millivolt level."""
        if self._bus is None or self._pin_map is None:
            return
        try:
            net = self._pin_map.net(gpio_num)
            self._bus.gpio.drive(net, f"{self.id}._inject", mv / 1000.0)
        except Exception:
            pass


# Register with multiple KiCad lib_id variants so the runner's auto-instantiate
# can find this class regardless of which symbol library the schematic uses.
from core.registry import register_part  # noqa: E402
register_part("ESP32-WROOM-32:ESP32-WROOM-32", ESP32WROOM32Node)
register_part("Espressif:ESP32-WROOM-32",       ESP32WROOM32Node)
register_part("esp32-wroom-32",                  ESP32WROOM32Node)
