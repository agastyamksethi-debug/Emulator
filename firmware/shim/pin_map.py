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
    """Pin capability flags."""
    DIGITAL_IN  = auto()
    DIGITAL_OUT = auto()
    ADC         = auto()
    DAC         = auto()
    PWM         = auto()
    SPI         = auto()
    I2C         = auto()
    UART        = auto()
    INPUT_ONLY  = auto()   # cannot be driven as output (ESP32 GPIO34-39)

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
        "adc":         Cap.ADC,
        "dac":         Cap.DAC,
        "pwm":         Cap.PWM,
        "spi":         Cap.SPI,
        "i2c":         Cap.I2C,
        "uart":        Cap.UART,
        "input_only":  Cap.INPUT_ONLY,
    }
    result = Cap(0)
    for c in cap_list:
        result |= mapping.get(c.lower(), Cap(0))
    return result
