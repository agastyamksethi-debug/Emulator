"""
Potentiometer simulation model.

A 3-terminal variable resistor.  Terminals 1 and 2 connect to two nets
(typically a supply rail and GND); the wiper W outputs a voltage that is a
linear blend of the two terminal voltages, set by the knob position 0.0–1.0.

    V_wiper = V_2 + position · (V_1 − V_2)

Pin mapping (checked in order):
  Terminal 1 (high): "1", "A", "T1"
  Wiper:             "W", "WIPER", "3"
  Terminal 2 (low):  "2", "B", "T2"

Descriptor keys:
  position   (float) — initial wiper position 0.0–1.0, default 0.5

Thread safety
─────────────
set_position() is called from the GUI (main) thread; tick() runs in the sim
worker thread.  The float write is atomic in CPython (GIL-protected).
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class PotentiometerNode(Node):
    PART_ID = "potentiometer"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})

        self._net_a: str = pins.get("1") or pins.get("A") or pins.get("T1") or ""
        self._net_w: str = pins.get("W") or pins.get("WIPER") or pins.get("3") or ""
        self._net_b: str = pins.get("2") or pins.get("B") or pins.get("T2") or ""

        self._position: float = max(0.0, min(1.0, float(descriptor.get("position", 0.5))))
        self._bus = None

    # ── wiring ────────────────────────────────────────────────────────────────

    def attach_bus(self, bus):
        self._bus = bus

    # ── public (called from GUI thread) ───────────────────────────────────────

    def set_position(self, frac: float):
        self._position = max(0.0, min(1.0, float(frac)))

    @property
    def position(self) -> float:
        return self._position

    # ── sim tick ──────────────────────────────────────────────────────────────

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_w:
            return
        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_a = self._bus.gpio.voltage(self._net_a) if self._net_a else v_sup
        v_b = self._bus.gpio.voltage(self._net_b) if self._net_b else 0.0
        v_w = v_b + self._position * (v_a - v_b)
        self._bus.gpio.drive(self._net_w, self.id, v_w)

    def reset(self):
        if self._bus and self._net_w:
            self._bus.gpio.release(self._net_w, self.id)


# ── registration ──────────────────────────────────────────────────────────────

registry.register_part("Device:R_Potentiometer", PotentiometerNode)
registry.register_part("potentiometer",          PotentiometerNode)
registry.register_part("pot",                     PotentiometerNode)
