"""
RGB LED.

Three colour channels (R, G, B) sharing a COM pin.  Each channel's brightness
comes from the voltage across it relative to COM, above the forward drop.
Supports common-cathode (default) and common-anode wiring.

Exposes `r`, `g`, `b` (0–1), `color` (0–255 tuple) and `on`.
Pins: R, G, B, COM.
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class RGBLedNode(Node):
    PART_ID = "rgb_led"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_r:   str = pins.get("R") or ""
        self._net_g:   str = pins.get("G") or ""
        self._net_b:   str = pins.get("B") or ""
        self._net_com: str = pins.get("COM") or pins.get("K") or pins.get("A") or "GND"
        self._common_anode: bool = bool(descriptor.get("common_anode", False))
        self._vf: float = float(descriptor.get("vf", 2.0))

        self.r = self.g = self.b = 0.0
        self.on = False
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def _channel(self, net: str, v_com: float, v_sup: float) -> float:
        if not net:
            return 0.0
        v = self._bus.gpio.voltage(net)
        # forward drop is COM→ch for common-anode, ch→COM otherwise
        drop = (v_com - v) if self._common_anode else (v - v_com)
        if drop <= self._vf:
            return 0.0
        return max(0.0, min(1.0, (drop - self._vf) / max(1e-6, v_sup - self._vf)))

    def tick(self, dt_ms: float):
        if not self._bus:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_com = self._bus.gpio.voltage(self._net_com) if self._net_com else 0.0
        self.r = self._channel(self._net_r, v_com, v_sup)
        self.g = self._channel(self._net_g, v_com, v_sup)
        self.b = self._channel(self._net_b, v_com, v_sup)
        self.on = (self.r + self.g + self.b) > 0.0

    @property
    def color(self) -> tuple[int, int, int]:
        return (int(self.r * 255), int(self.g * 255), int(self.b * 255))

    def reset(self):
        self.r = self.g = self.b = 0.0
        self.on = False


registry.register_part("Device:LED_RGB", RGBLedNode)
registry.register_part("rgb_led",        RGBLedNode)
