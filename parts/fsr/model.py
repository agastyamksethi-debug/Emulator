"""
Force-sensitive resistor (FSR).

Resistance is very high with no force and drops sharply as force is applied.
Wired as the upper leg of a divider (top → FSR → OUT → R_fixed → GND), so the
output rises with force.  Set normalised force with set_force(0–1).

    R = r_min + (r_max − r_min) · (1 − force)^2      (knee near light touch)
    V_out = V_top · R_fixed / (R + R_fixed)

Pins: "1" (top/rail), "2" (output).
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class FSRNode(Node):
    PART_ID = "fsr"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_top: str = pins.get("1") or pins.get("A") or pins.get("+") or ""
        self._net_out: str = pins.get("2") or pins.get("K") or pins.get("-") or ""
        self._r_min:   float = float(descriptor.get("r_min", 2000.0))
        self._r_max:   float = float(descriptor.get("r_max", 1000000.0))
        self._r_fixed: float = float(descriptor.get("r_fixed", 10000.0))

        self._force: float = 0.0
        self.resistance: float = self._r_max
        self.v_out: float = 0.0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_force(self, force: float):
        self._force = max(0.0, min(1.0, float(force)))

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        self.resistance = self._r_min + (self._r_max - self._r_min) * (1.0 - self._force) ** 2
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_top = self._bus.gpio.voltage(self._net_top) if self._net_top else v_sup
        self.v_out = v_top * self._r_fixed / (self.resistance + self._r_fixed)
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self._force = 0.0
        self.resistance = self._r_max
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:FSR", FSRNode)
registry.register_part("fsr",        FSRNode)
