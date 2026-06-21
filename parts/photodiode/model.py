"""
Photodiode (photoconductive mode).

Unlike the LDR, a photodiode's current is linear in illumination and its
response is effectively instantaneous.  Here the output voltage rises linearly
with the incident light level:

    V_out = V_top · clamp(light · responsivity, 0, 1)

Feed light with set_light(0–1).  Pins: "1" (top/rail), "2" (output).
"""

from __future__ import annotations
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry


class PhotodiodeNode(Node):
    PART_ID = "photodiode"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_top: str = pins.get("1") or pins.get("A") or pins.get("+") or ""
        self._net_out: str = pins.get("2") or pins.get("K") or pins.get("-") or ""
        self._resp: float = float(descriptor.get("responsivity", 1.0))

        self._light: float = 0.0
        self.v_out: float = 0.0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_light(self, level: float, wavelength: int = 0):
        self._light = max(0.0, min(1.0, float(level)))

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_top = self._bus.gpio.voltage(self._net_top) if self._net_top else v_sup
        frac = max(0.0, min(1.0, self._light * self._resp + sensor_noise(0.005)))
        self.v_out = v_top * frac
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self._light = 0.0
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:Photodiode", PhotodiodeNode)
registry.register_part("photodiode",        PhotodiodeNode)
