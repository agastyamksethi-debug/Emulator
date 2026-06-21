"""
Infrared emitter LED.

Behaves like a visible LED but emits in the infrared (~940 nm).  Reads the
voltage across anode/cathode each tick; above Vf it conducts and the forward
current sets the IR output intensity (0–1), exposed for the rw-bus 'ir' domain
and any IR receiver wired to it.

Pin mapping:  anode "A"/"+"/"1",  cathode "K"/"-"/"2"

Descriptor keys: vf, if_ma, series_r, wavelength (defaults 1.2 V / 50 mA / 220 Ω / 940 nm)
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


def _pin(pins: dict, *cands: str) -> str | None:
    for k in cands:
        v = pins.get(k)
        if isinstance(v, str) and v:
            return v
    return None


class IRLedNode(Node):
    PART_ID = "ir_led"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self.anode_net:   str = _pin(pins, "A", "+", "1") or "A"
        self.cathode_net: str = _pin(pins, "K", "-", "2") or "GND"

        self.vf:        float = float(descriptor.get("vf", 1.2))
        self.if_ma:     float = float(descriptor.get("if_ma", 50.0))
        self._series_r: float = float(descriptor.get("series_r", 220.0))
        self.wavelength: int  = int(descriptor.get("wavelength", 940))

        self.on:         bool  = False
        self.current_ma: float = 0.0
        self.intensity:  float = 0.0      # 0–1, IR output for the rw 'ir' domain
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def tick(self, dt_ms: float):
        if self._bus is None:
            return
        v_a = self._bus.gpio.voltage(self.anode_net)
        v_k = self._bus.gpio.voltage(self.cathode_net)
        self.on = (v_a - v_k) >= self.vf
        if self.on and self._series_r > 0:
            self.current_ma = max(0.0, (v_a - self.vf) / self._series_r * 1000)
            self.intensity = min(1.0, self.current_ma / self.if_ma)
        else:
            self.current_ma = 0.0
            self.intensity = 0.0

    def reset(self):
        self.on = False
        self.current_ma = 0.0
        self.intensity = 0.0


registry.register_part("Device:LED_IR", IRLedNode)
registry.register_part("ir_led",        IRLedNode)
