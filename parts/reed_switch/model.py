"""
Reed switch.

A normally-open switch that closes when a magnet is near.  When closed it
shorts its two pins (driving pin 1 to pin 2's voltage), exactly like a button;
when open the contacts float.  Set the field with set_field(True/False).

Pins: "1", "2".
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class ReedSwitchNode(Node):
    PART_ID = "reed_switch"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net1: str = pins.get("1") or pins.get("A") or ""
        self._net2: str = pins.get("2") or pins.get("B") or "GND"
        self._closed: bool = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_field(self, present: bool):
        self._closed = bool(present)

    @property
    def closed(self) -> bool:
        return self._closed

    def tick(self, dt_ms: float):
        if not self._bus or not self._net1:
            return
        if self._closed:
            v2 = self._bus.gpio.voltage(self._net2) if self._net2 else 0.0
            self._bus.gpio.drive(self._net1, self.id, v2)
        else:
            self._bus.gpio.release(self._net1, self.id)

    def reset(self):
        self._closed = False
        if self._bus and self._net1:
            self._bus.gpio.release(self._net1, self.id)


registry.register_part("Device:Reed", ReedSwitchNode)
registry.register_part("reed",        ReedSwitchNode)
registry.register_part("reed_switch", ReedSwitchNode)
