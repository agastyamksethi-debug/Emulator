"""
Demodulating IR receiver (TSOP-style).

Outputs an active-LOW digital signal: OUT is pulled LOW while a modulated IR
carrier is present and idles HIGH otherwise.  Feed it the incoming IR level
with set_ir(0–1) (e.g. from an IR LED's intensity over the rw 'ir' domain).

Pins: OUT (signal), VCC, GND.

Descriptor keys: threshold — IR level above which it detects (default 0.1)
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class IRReceiverNode(Node):
    PART_ID = "ir_receiver"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_out: str = (pins.get("OUT") or pins.get("S")
                              or pins.get("3") or pins.get("1") or "")
        self._threshold: float = float(descriptor.get("threshold", 0.1))

        self._ir: float = 0.0
        self.detecting: bool = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_ir(self, level: float):
        self._ir = max(0.0, min(1.0, float(level)))

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        self.detecting = self._ir >= self._threshold
        # active-low output
        self._bus.gpio.drive(self._net_out, self.id, 0.0 if self.detecting else v_sup)

    def reset(self):
        self._ir = 0.0
        self.detecting = False
        if self._bus and self._net_out:
            v_sup = getattr(self._bus, "v_supply", 3.3)
            self._bus.gpio.drive(self._net_out, self.id, v_sup)


registry.register_part("Device:IR_Receiver", IRReceiverNode)
registry.register_part("ir_receiver",        IRReceiverNode)
