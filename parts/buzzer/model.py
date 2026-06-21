"""
Active buzzer.

Reads the voltage across its two pins; when driven above half-supply it sounds
at its fixed frequency.  Exposes `on` and `sound_level` (0–1) for the rw
'sound' domain.  (For tone control, use a passive buzzer driven by PWM.)

Pins: "+"/"1", "-"/"2".
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class BuzzerNode(Node):
    PART_ID = "buzzer"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_p: str = pins.get("+") or pins.get("1") or pins.get("A") or ""
        self._net_n: str = pins.get("-") or pins.get("2") or pins.get("K") or "GND"
        self.frequency_hz: float = float(descriptor.get("frequency_hz", 2400.0))

        self.on: bool = False
        self.sound_level: float = 0.0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_p:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_p = self._bus.gpio.voltage(self._net_p)
        v_n = self._bus.gpio.voltage(self._net_n) if self._net_n else 0.0
        self.on = (v_p - v_n) > v_sup / 2
        self.sound_level = 1.0 if self.on else 0.0

    def reset(self):
        self.on = False
        self.sound_level = 0.0


registry.register_part("Device:Buzzer", BuzzerNode)
registry.register_part("buzzer",        BuzzerNode)
