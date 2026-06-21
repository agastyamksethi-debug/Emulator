"""
Ratiometric hall-effect sensor.

Output rests at mid-supply with no field and deflects toward the rails with the
applied field's polarity and strength.  Set the field with set_field(−1…+1).

    V_out = V_sup/2 · (1 + field)        field −1 → 0 V, 0 → V_sup/2, +1 → V_sup

Pins: VCC, OUT, GND.
"""

from __future__ import annotations
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry


class HallNode(Node):
    PART_ID = "hall"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_out: str = (pins.get("OUT") or pins.get("AO")
                              or pins.get("2") or "")
        self._field: float = 0.0          # −1 … +1
        self.v_out: float = 0.0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_field(self, field: float):
        self._field = max(-1.0, min(1.0, float(field)))

    @property
    def field(self) -> float:
        return self._field

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v = (v_sup / 2.0) * (1.0 + self._field) + sensor_noise(0.005)
        self.v_out = max(0.0, min(v_sup, v))
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self._field = 0.0
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:Hall", HallNode)
registry.register_part("hall",        HallNode)
