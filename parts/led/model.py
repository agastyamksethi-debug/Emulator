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
    When V_anode − V_cathode rises above Vf, prints a timestamped ON message
    with estimated current and brightness percentage.

    Pin mapping (checked in order, first string match wins):
      Anode:   "A", "+", "1"
      Cathode: "K", "-", "2"

    Descriptor keys:
      vf        (float) — forward voltage threshold, default 2.0 V
      if_ma     (float) — rated max forward current in mA, default 20 mA
      series_r  (float) — series current-limiting resistor in Ω, default 0
                          (if 0 or missing, current/brightness are not shown)
      color     (str)   — label shown in messages, default "red"
    """

    PART_ID = "led"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})

        self.anode_net:   str   = _resolve_pin(pins, "A", "+", "1") or "A"
        self.cathode_net: str   = _resolve_pin(pins, "K", "-", "2") or "GND"
        self.vf:          float = float(descriptor.get("vf", 2.0))
        self.if_ma:       float = float(descriptor.get("if_ma", 20.0))
        self._series_r:   float = float(descriptor.get("series_r", 0.0))
        self.color:       str   = descriptor.get("color", "red")

        # dominant emission wavelength (nm) — explicit, else derived from colour
        _COLOR_WL = {"red": 625, "orange": 605, "yellow": 590,
                     "green": 525, "blue": 470, "white": 580}
        self.wavelength: int = int(descriptor.get(
            "wavelength", _COLOR_WL.get(self.color, 625)))

        self.on:             bool  = False
        self.current_ma:     float = 0.0
        self.brightness_pct: float = 0.0
        self.power_dissipation: float = 0.0

        self._prev_on:         bool  = False
        self._elapsed_ms:      float = 0.0
        self._last_print_ms:   float = 0.0
        self._last_brightness: float = -1.0
        self._bus = None

    # ---------------------------------------------------------------- wiring ---

    def attach_bus(self, bus):
        self._bus = bus

    def reset(self):
        self.on             = False
        self.current_ma     = 0.0
        self.brightness_pct = 0.0
        self.power_dissipation = 0.0
        self._prev_on         = False
        self._elapsed_ms      = 0.0
        self._last_print_ms   = 0.0
        self._last_brightness = -1.0

    # ------------------------------------------------------------------ tick ---

    def tick(self, dt_ms: float):
        self._elapsed_ms += dt_ms

        if self._bus is None:
            return

        v_a = self._bus.gpio.voltage(self.anode_net)
        v_k = self._bus.gpio.voltage(self.cathode_net)
        self.on = (v_a - v_k) >= self.vf

        if self.on and self._series_r > 0:
            # V_anode in the simulator ≈ V_source (the resistor propagates the
            # source voltage to the anode net), so:
            #   I = (V_source − Vf) / R_series = (V_anode − Vf) / R_series
            self.current_ma = max(0.0, (v_a - self.vf) / self._series_r * 1000)
            self.brightness_pct = min(100.0, self.current_ma / self.if_ma * 100)
            self.power_dissipation = (self.current_ma / 1000) * self.vf
        elif not self.on:
            self.current_ma     = 0.0
            self.brightness_pct = 0.0
            self.power_dissipation = 0.0

        v_drop = v_a - v_k

        if self.on != self._prev_on:
            state = "ON " if self.on else "OFF"
            if self.on and self._series_r > 0:
                print(
                    f"[LED {self.id}] {state}  "
                    f"(V={v_drop:.2f}V  "
                    f"I={self.current_ma:.1f}mA  "
                    f"brightness={self.brightness_pct:.0f}%  "
                    f"t={self._elapsed_ms:.1f}ms)"
                )
            else:
                print(
                    f"[LED {self.id}] {state}  "
                    f"(V={v_drop:.2f}V  t={self._elapsed_ms:.1f}ms)"
                )
            self._prev_on         = self.on
            self._last_print_ms   = self._elapsed_ms
            self._last_brightness = self.brightness_pct

        elif self.on and self._series_r > 0:
            dt_since = self._elapsed_ms - self._last_print_ms
            b_delta  = abs(self.brightness_pct - self._last_brightness)
            if dt_since >= 50.0 or b_delta >= 10.0:
                print(
                    f"[LED {self.id}]  ~  "
                    f"(V={v_drop:.2f}V  "
                    f"I={self.current_ma:.1f}mA  "
                    f"brightness={self.brightness_pct:.0f}%  "
                    f"t={self._elapsed_ms:.1f}ms)"
                )
                self._last_print_ms   = self._elapsed_ms
                self._last_brightness = self.brightness_pct


# Register under common KiCad lib_id variants
registry.register_part("Device:LED",     LEDNode)
registry.register_part("Device:LED_ALT", LEDNode)
registry.register_part("led",            LEDNode)
