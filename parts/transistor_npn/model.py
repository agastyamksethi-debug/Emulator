"""
NPN BJT — behavioural switch model.

When V_base − V_emitter exceeds Vbe the transistor turns on and saturates,
pulling the collector net down to V_emitter + Vce(sat) (the classic low-side
switch).  When off, the collector is released (high-impedance) so a pull-up or
load defines its voltage.

Pins: B, C, E.  Descriptor: vbe (0.7), v_ce_sat (0.2).
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class NPNTransistorNode(Node):
    PART_ID = "transistor_npn"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_b: str = pins.get("B") or pins.get("1") or ""
        self._net_c: str = pins.get("C") or pins.get("2") or ""
        self._net_e: str = pins.get("E") or pins.get("3") or "GND"
        self._vbe:    float = float(descriptor.get("vbe", 0.7))
        self._vce_sat: float = float(descriptor.get("v_ce_sat", 0.2))
        self.on: bool = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_c:
            return
        v_b = self._bus.gpio.voltage(self._net_b) if self._net_b else 0.0
        v_e = self._bus.gpio.voltage(self._net_e) if self._net_e else 0.0
        self.on = (v_b - v_e) >= self._vbe
        if self.on:
            self._bus.gpio.drive(self._net_c, self.id, v_e + self._vce_sat)
        else:
            self._bus.gpio.release(self._net_c, self.id)

    def reset(self):
        self.on = False
        if self._bus and self._net_c:
            self._bus.gpio.release(self._net_c, self.id)


registry.register_part("Device:Q_NPN", NPNTransistorNode)
registry.register_part("transistor_npn", NPNTransistorNode)
registry.register_part("npn",            NPNTransistorNode)
