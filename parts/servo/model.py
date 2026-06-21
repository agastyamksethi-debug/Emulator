"""
Hobby servo.

A real servo reads a 1–2 ms pulse at 50 Hz; in this behavioural simulator PWM
is modelled as an averaged DC level, so the control net's duty (its voltage as
a fraction of supply) maps linearly to shaft angle:

    angle = min_angle + duty · (max_angle − min_angle)

Exposes `angle` (degrees).  Pins: SIG, VCC, GND.
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class ServoNode(Node):
    PART_ID = "servo"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_sig: str = (pins.get("SIG") or pins.get("S")
                              or pins.get("1") or "")
        self._min: float = float(descriptor.get("min_angle", 0.0))
        self._max: float = float(descriptor.get("max_angle", 180.0))
        self.angle: float = self._min
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_sig:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        duty = max(0.0, min(1.0, self._bus.gpio.voltage(self._net_sig) / v_sup))
        self.angle = self._min + duty * (self._max - self._min)

    def reset(self):
        self.angle = self._min


registry.register_part("Device:Servo", ServoNode)
registry.register_part("servo",        ServoNode)
