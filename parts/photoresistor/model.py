"""
Photoresistor (LDR) simulation model.

Wired as the upper leg of a voltage divider:

    V_top ──[ LDR ]── OUT ──[ R_fixed ]── GND

The LDR resistance falls as illumination rises, so the divider output OUT
climbs toward V_top in bright light and sinks toward GND in the dark.

Two fidelity tiers (selected by core.fidelity.CONFIG.real_world)
───────────────────────────────────────────────────────────────
  BASIC     R linear in light, instantaneous, wavelength-agnostic:
                R = r_bright + (r_dark − r_bright)·(1 − L)

  ADVANCED  physically grounded CdS behaviour:
              • spectral sensitivity — response peaks ~540 nm (green), so red
                or blue light is sensed at reduced efficiency
              • log-linear resistance — log(R) linear in light level (real
                CdS cells are linear on a log-R / log-lux plot)
              • response lag — first-order light integration with asymmetric
                rise/fall time constants (cells are slow, slower to recover)

Illumination
────────────
The GUI pushes the propagated rw_bus light (and its source wavelength) via
set_light(); `gain` maps the dim in-sim LED brightness onto a usable range.
If "source" names a part, the LDR falls back to reading its brightness.

Descriptor keys:
  r_bright (Ω)  resistance under full light            default 1k
  r_dark   (Ω)  resistance in darkness                 default 100k
  r_fixed  (Ω)  fixed lower-leg divider resistor       default 10k
  gain          optical-coupling / full-scale factor   default 3.3
  peak_nm       spectral response peak (advanced)      default 540
  band_nm       spectral response width σ (advanced)   default 90
  gamma         resistance-curve shape (advanced)      default 0.9
  tau_rise_ms / tau_fall_ms   response lag (advanced)  default 60 / 150
  source        ref of illuminating part (fallback)    default ""
"""

from __future__ import annotations
import math
from core.node import Node
from core.fidelity import CONFIG
import core.registry as registry


class PhotoresistorNode(Node):
    PART_ID = "photoresistor"

    def __init__(self, instance_id: str, descriptor: dict):
        super().__init__(instance_id, descriptor)
        pins = descriptor.get("pins", {})

        self._net_top: str = pins.get("1") or pins.get("A") or pins.get("+") or ""
        self._net_out: str = pins.get("2") or pins.get("K") or pins.get("-") or ""

        self._r_bright: float = float(descriptor.get("r_bright", 1000.0))
        self._r_dark:   float = float(descriptor.get("r_dark",   100000.0))
        self._r_fixed:  float = float(descriptor.get("r_fixed",  10000.0))
        self._gain:     float = float(descriptor.get("gain",     3.3))
        self._source:   str   = descriptor.get("source", "")

        # advanced-tier parameters
        self._peak_nm:  float = float(descriptor.get("peak_nm", 540.0))
        self._band_nm:  float = float(descriptor.get("band_nm", 90.0))
        self._gamma:    float = float(descriptor.get("gamma",   0.9))
        self._tau_rise: float = float(descriptor.get("tau_rise_ms", 60.0))
        self._tau_fall: float = float(descriptor.get("tau_fall_ms", 150.0))

        self._bus    = None
        self._runner = None
        self._src_node = None

        # external (rw_bus) light push from the GUI
        self._ext_active: bool  = False
        self._ext_light:  float = 0.0
        self._ext_wl:     int   = 0       # source wavelength (nm), 0 = unknown

        self._lpf: float = 0.0            # response-lag integrator (advanced)

        # exposed state (read by GUI / serial)
        self.light:      float = 0.0
        self.resistance: float = self._r_dark
        self.v_out:      float = 0.0

    # ── wiring ────────────────────────────────────────────────────────────────

    def attach_bus(self, bus):
        self._bus = bus

    def attach(self, netlist, bus, runner):
        self._bus    = bus
        self._runner = runner

    # ── public ────────────────────────────────────────────────────────────────

    def set_light(self, level: float, wavelength: int = 0):
        """
        External light push from the GUI's rw_bus (carries any spliced loss).
        `wavelength` is the source colour in nm (0 = unknown).  Thread-safe:
        plain scalar writes are atomic under the GIL.
        """
        self._ext_light  = max(0.0, min(1.0, float(level)))
        self._ext_wl     = int(wavelength)
        self._ext_active = True

    # ── illumination input ──────────────────────────────────────────────────────

    def _raw_light(self) -> float:
        if self._ext_active:
            return min(1.0, max(0.0, self._ext_light * self._gain))
        if self._source and self._runner is not None:
            if self._src_node is None:
                self._src_node = self._runner.node(self._source)
            node = self._src_node
            if node is not None and hasattr(node, "brightness_pct"):
                return min(1.0, max(0.0, (node.brightness_pct / 100.0) * self._gain))
        return 0.0

    def _spectral_response(self) -> float:
        """CdS sensitivity at the incident wavelength (1.0 at peak)."""
        if self._ext_wl <= 0:
            return 1.0
        d = self._ext_wl - self._peak_nm
        return math.exp(-(d / self._band_nm) ** 2)

    # ── sim tick ──────────────────────────────────────────────────────────────

    def tick(self, dt_ms: float):
        if not self._bus or not self._net_out:
            return

        advanced = CONFIG.is_advanced("real_world")
        target = self._raw_light()

        if advanced:
            # spectral sensitivity, then first-order response lag
            target *= self._spectral_response()
            tau = self._tau_rise if target > self._lpf else self._tau_fall
            alpha = 1.0 - math.exp(-dt_ms / tau) if tau > 0 else 1.0
            self._lpf += (target - self._lpf) * alpha
            self.light = self._lpf
            # log-linear resistance (real CdS): log(R) linear in light
            L = max(0.0, min(1.0, self.light)) ** self._gamma
            self.resistance = self._r_dark * (self._r_bright / self._r_dark) ** L
        else:
            self.light = target
            self.resistance = (self._r_bright
                               + (self._r_dark - self._r_bright) * (1.0 - target))

        v_sup = getattr(self._bus, "v_supply", 3.3)
        v_top = self._bus.gpio.voltage(self._net_top) if self._net_top else v_sup
        self.v_out = v_top * self._r_fixed / (self.resistance + self._r_fixed)
        self._bus.gpio.drive(self._net_out, self.id, self.v_out)

    def reset(self):
        self.light       = 0.0
        self.resistance  = self._r_dark
        self.v_out       = 0.0
        self._lpf        = 0.0
        self._src_node   = None
        self._ext_active = False
        self._ext_light  = 0.0
        self._ext_wl     = 0
        if self._bus and self._net_out:
            self._bus.gpio.release(self._net_out, self.id)


# ── registration ──────────────────────────────────────────────────────────────

registry.register_part("Device:R_Photo",  PhotoresistorNode)
registry.register_part("photoresistor",   PhotoresistorNode)
registry.register_part("ldr",             PhotoresistorNode)
