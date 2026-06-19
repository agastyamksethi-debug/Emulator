from __future__ import annotations
from core.node import Node
import core.registry as registry


def _resolve_pin(pins: dict, *candidates: str) -> str | None:
    """Return the net name for the first matching pin key, skipping dict values."""
    for key in candidates:
        val = pins.get(key)
        if isinstance(val, str) and val:
            return val
    return None


class LEDNode(Node):
    """
    Generic LED peripheral.

    Reads the voltage across its anode/cathode nets each tick.
    When V_anode − V_cathode rises above Vf, prints a timestamped ON message.
    When it drops below Vf, prints OFF.  self.on always reflects current state.

    Pin mapping (checked in order, first string match wins):
      Anode:   "A", "+", "1"
      Cathode: "K", "-", "2"

    Descriptor keys:
      vf (float)        — forward voltage threshold, default 2.0 V
      color (str)       — label shown in messages, default "red"
    """

    PART_ID = "led"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})

        self.anode_net:   str = _resolve_pin(pins, "A", "+", "1") or "A"
        self.cathode_net: str = _resolve_pin(pins, "K", "-", "2") or "GND"
        self.vf:   float = float(descriptor.get("vf", 2.0))
        self.color: str  = descriptor.get("color", "red")

        self.on: bool = False
        self._prev_on: bool = False
        self._elapsed_ms: float = 0.0
        self._bus = None

    # ---------------------------------------------------------------- wiring ---

    def attach_bus(self, bus):
        self._bus = bus

    def reset(self):
        self.on = False
        self._prev_on = False
        self._elapsed_ms = 0.0

    # ------------------------------------------------------------------ tick ---

    def tick(self, dt_ms: float):
        self._elapsed_ms += dt_ms

        if self._bus is None:
            return

        v_a = self._bus.gpio.voltage(self.anode_net)
        v_k = self._bus.gpio.voltage(self.cathode_net)
        self.on = (v_a - v_k) >= self.vf

        if self.on != self._prev_on:
            state = "ON " if self.on else "OFF"
            v_drop = v_a - v_k
            print(
                f"[LED {self.id}] {state}  "
                f"(V={v_drop:.2f}V  anode={v_a:.2f}V  t={self._elapsed_ms:.1f}ms)"
            )
            self._prev_on = self.on


# Register under common KiCad lib_id variants
registry.register_part("Device:LED",     LEDNode)
registry.register_part("Device:LED_ALT", LEDNode)
registry.register_part("led",            LEDNode)
