"""
PIR motion sensor.

OUT goes HIGH when motion is detected and stays HIGH for `hold_ms` after the
last trigger (the module's retrigger/dwell time).  Trigger motion from the GUI
or a test with set_motion(True).

Pins: VCC, OUT, GND.
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class PIRNode(Node):
    PART_ID = "pir"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_out: str = (pins.get("OUT") or pins.get("S")
                              or pins.get("2") or "")
        self._hold_ms: float = float(descriptor.get("hold_ms", 2000.0))
        self._timer: float = 0.0
        self.active: bool = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_motion(self, present: bool):
        if present:
            self._timer = self._hold_ms

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        if self._timer > 0.0:
            self._timer -= dt_ms
        self.active = self._timer > 0.0
        v_sup = getattr(self._bus, "v_supply", 3.3)
        self._bus.gpio.drive(self._net_out, self.id, v_sup if self.active else 0.0)

    def reset(self):
        self._timer = 0.0
        self.active = False
        if self._bus and self._net_out:
            self._bus.gpio.drive(self._net_out, self.id, 0.0)


registry.register_part("Device:PIR", PIRNode)
registry.register_part("pir",        PIRNode)
