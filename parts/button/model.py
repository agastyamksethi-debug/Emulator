"""
Button / tactile switch simulation model.

Models a normally-open momentary push switch.  When pressed it creates a
short between its two pins; when released the pins are disconnected.

The GPIO bus uses lowest-voltage-wins arbitration, so when the button shorts
pin1 to GND (pin2) it correctly overrides any pull-up resistor on pin1.

Pin mapping (checked in order):
  pin1: "1", "A", "IN"
  pin2: "2", "B", "GND"

Descriptor keys: none required beyond "pins".

Thread safety
─────────────
set_pressed() is called from the GUI (main) thread; tick() runs in the sim
worker thread.  The bool write is atomic in CPython (GIL-protected), so no
lock is needed.
"""

from __future__ import annotations
from core.node import Node
import core.registry as registry


class ButtonModel(Node):
    PART_ID = "button"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})

        self._net1: str = (
            pins.get("1") or pins.get("A") or pins.get("IN") or ""
        )
        self._net2: str = (
            pins.get("2") or pins.get("B") or pins.get("GND_PIN") or ""
        )

        self._pressed: bool = False
        self._was_pressed: bool = False
        self._bus = None

    # ── wiring ────────────────────────────────────────────────────────────────

    def attach_bus(self, bus):
        self._bus = bus

    # ── public (called from GUI thread) ───────────────────────────────────────

    def set_pressed(self, pressed: bool):
        self._pressed = pressed

    @property
    def pressed(self) -> bool:
        return self._pressed

    # ── sim tick ──────────────────────────────────────────────────────────────

    def tick(self, dt_ms: float):
        if not self._bus or not self._net1 or not self._net2:
            return

        if self._pressed:
            # Short pin1 to pin2: drive pin1 to whatever pin2 is at (usually 0 V)
            v2 = self._bus.gpio.voltage(self._net2)
            self._bus.gpio.drive(self._net1, self.id, v2)
        else:
            # Open circuit: stop driving pin1, let pull-up/external source win
            self._bus.gpio.release(self._net1, self.id)

        if self._pressed != self._was_pressed:
            state = "PRESSED" if self._pressed else "RELEASED"
            print(f"[BTN {self.id}] {state}")
            self._was_pressed = self._pressed

    def reset(self):
        self._pressed = False
        self._was_pressed = False
        if self._bus and self._net1:
            self._bus.gpio.release(self._net1, self.id)


# ── registration ──────────────────────────────────────────────────────────────

registry.register_part("Device:SW_Push",         ButtonModel)
registry.register_part("Device:SW_Push_Virtual", ButtonModel)
registry.register_part("button",                 ButtonModel)
registry.register_fallback(registry.Category.SWITCH, ButtonModel)
