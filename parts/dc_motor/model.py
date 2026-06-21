"""
Brushed DC motor.

Reads the voltage across its two terminals and derives a speed.  Below the
stall voltage it doesn't turn; above it, speed scales linearly with voltage up
to the nominal voltage.  Sign of the terminal voltage sets direction.

Exposes `voltage`, `speed_pct` (0–100), `rpm`, `direction` (+1/0/−1).
Pins: "1"/"+", "2"/"-".
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class DCMotorNode(Node):
    PART_ID = "dc_motor"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_a: str = pins.get("1") or pins.get("+") or pins.get("A") or ""
        self._net_b: str = pins.get("2") or pins.get("-") or pins.get("B") or "GND"

        self._max_rpm:  float = float(descriptor.get("max_rpm", 9000.0))
        self._v_nom:    float = float(descriptor.get("v_nominal", 3.3))
        self._v_stall:  float = float(descriptor.get("v_stall", 0.3))

        self.voltage:   float = 0.0
        self.speed_pct: float = 0.0
        self.rpm:       float = 0.0
        self.direction: int   = 0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_a:
            return
        v_a = self._bus.gpio.voltage(self._net_a)
        v_b = self._bus.gpio.voltage(self._net_b) if self._net_b else 0.0
        self.voltage = v_a - v_b
        mag = abs(self.voltage)
        self.direction = 0 if mag <= self._v_stall else (1 if self.voltage > 0 else -1)
        if mag <= self._v_stall:
            self.speed_pct = 0.0
        else:
            span = max(1e-6, self._v_nom - self._v_stall)
            self.speed_pct = min(100.0, (mag - self._v_stall) / span * 100.0)
        self.rpm = self.speed_pct / 100.0 * self._max_rpm

    def reset(self):
        self.voltage = self.speed_pct = self.rpm = 0.0
        self.direction = 0


registry.register_part("Device:Motor_DC", DCMotorNode)
registry.register_part("dc_motor",        DCMotorNode)
registry.register_part("motor",           DCMotorNode)
