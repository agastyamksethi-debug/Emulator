"""
SPDT relay.

When the coil control net (IN) is driven above half-supply the relay
energises: COM connects to NO (and disconnects from NC); otherwise COM rests on
NC.  The connected contact net is driven to COM's voltage so downstream logic
sees the switch.

Pins: IN (coil), COM, NO, NC.
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class RelayNode(Node):
    PART_ID = "relay"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_in:  str = pins.get("IN") or pins.get("COIL") or pins.get("1") or ""
        self._net_com: str = pins.get("COM") or ""
        self._net_no:  str = pins.get("NO") or ""
        self._net_nc:  str = pins.get("NC") or ""
        self.energized: bool = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_in:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        self.energized = self._bus.gpio.voltage(self._net_in) > v_sup / 2
        v_com = self._bus.gpio.voltage(self._net_com) if self._net_com else 0.0

        live, dead = (self._net_no, self._net_nc) if self.energized \
            else (self._net_nc, self._net_no)
        if live:
            self._bus.gpio.drive(live, self.id, v_com)
        if dead:
            self._bus.gpio.release(dead, self.id)

    def reset(self):
        self.energized = False
        for net in (self._net_no, self._net_nc):
            if self._bus and net:
                self._bus.gpio.release(net, self.id)


registry.register_part("Device:Relay", RelayNode)
registry.register_part("relay",        RelayNode)
