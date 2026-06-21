"""
NTC thermistor model.

Wired as the upper leg of a voltage divider (top → NTC → OUT → R_fixed → GND).
Resistance follows the Beta equation relative to 25 °C, so it falls as the
temperature rises and the divider output climbs:

    R(T) = R25 · exp( B · (1/T − 1/298.15) )      T in kelvin
    V_out = V_top · R_fixed / (R(T) + R_fixed)

Set the sensed temperature with set_temperature(°C).

Descriptor keys:
  r25      (Ω)  resistance at 25 °C          default 10k
  beta     (K)  Beta coefficient             default 3950
  r_fixed  (Ω)  fixed lower-leg resistor      default 10k
  temperature_c  initial temperature          default 25
"""

from __future__ import annotations
import math
from core.node import Node
from core.fidelity import sensor_noise
import core.registry as registry


class NTCNode(Node):
    PART_ID = "ntc"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})
        self._net_top: str = pins.get("1") or pins.get("A") or pins.get("+") or ""
        self._net_out: str = pins.get("2") or pins.get("K") or pins.get("-") or ""

        self._r25:    float = float(descriptor.get("r25", 10000.0))
        self._beta:   float = float(descriptor.get("beta", 3950.0))
        self._r_fixed: float = float(descriptor.get("r_fixed", 10000.0))
        self._temp_c: float = float(descriptor.get("temperature_c", 25.0))

        self._bus = None
        self.resistance: float = self._r25
        self.v_out:      float = 0.0

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
        t_k = self._temp_c + 273.15 + sensor_noise(0.05)
        self.resistance = self._r25 * math.exp(self._beta * (1.0 / t_k - 1.0 / 298.15))
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_top = self._bus.gpio.voltage(self._net_top) if self._net_top else v_sup
        self.v_out = v_top * self._r_fixed / (self.resistance + self._r_fixed)
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self.resistance = self._r25
        self.v_out = 0.0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


registry.register_part("Device:Thermistor_NTC", NTCNode)
registry.register_part("ntc",        NTCNode)
registry.register_part("thermistor", NTCNode)
