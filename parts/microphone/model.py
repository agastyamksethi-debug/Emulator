"""
Analog microphone / sound sensor.

Output rests at a mid-supply bias and rises with sound level (an envelope of
the AC signal an amplified electret module would produce).  Set the sound level
with set_sound(0–1).

    V_out = bias + sound · swing · (V_sup − bias)        bias = V_sup / 2

Pins: VCC, OUT, GND.
"""

from __future__ import annotations
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry


class MicrophoneNode(Node):
    PART_ID = "microphone"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_out: str = (pins.get("OUT") or pins.get("AO")
                              or pins.get("2") or "")
        self._swing: float = float(descriptor.get("swing", 0.9))
        self._sound: float = 0.0
        self.v_out: float = 0.0
        self._bus = None

    def attach_bus(self, bus):
        self._bus = bus

    def set_sound(self, level: float):
        self._sound = max(0.0, min(1.0, float(level)))

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        bias = v_sup / 2.0
        v = bias + (self._sound + sensor_noise(0.01)) * self._swing * (v_sup - bias)
        self.v_out = max(0.0, min(v_sup, v))
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self._sound = 0.0
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:Microphone", MicrophoneNode)
registry.register_part("microphone",        MicrophoneNode)
registry.register_part("sound_sensor",      MicrophoneNode)
