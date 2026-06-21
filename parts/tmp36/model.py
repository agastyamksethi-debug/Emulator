"""
TMP36 analog temperature sensor.

Drives its OUT pin with a voltage linear in temperature:

    V_out = 0.5 V + 0.01 V/°C · T          (−40 °C → 0.1 V, 25 °C → 0.75 V)

Set the sensed temperature with set_temperature(°C).
Pins: VCC, OUT, GND.
"""

from __future__ import annotations
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry


class TMP36Node(Node):
    PART_ID = "tmp36"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_out: str = (pins.get("OUT") or pins.get("VOUT")
                              or pins.get("2") or "")
        self._temp_c: float = float(descriptor.get("temperature_c", 25.0))
        self._bus = None
        self.v_out: float = 0.0

    def attach_bus(self, bus):
        self._bus = bus

    def set_temperature(self, celsius: float):
        self._temp_c = float(celsius)

    @property
    def sensed_temperature(self) -> float:
        return self._temp_c

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v = 0.5 + 0.01 * (self._temp_c + sensor_noise(0.1))
        self.v_out = max(0.0, min(v_sup, v))
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:TMP36", TMP36Node)
registry.register_part("tmp36",        TMP36Node)
