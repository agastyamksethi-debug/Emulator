"""
Simulation fidelity configuration.

Two model tiers exist for each simulation domain:

  BASIC     — fast, idealised behaviour (good enough for logic / digital)
  ADVANCED  — physically grounded behaviour (analog / real-world domains)

A single process-wide CONFIG object holds the chosen tier per domain.  Both the
GUI thread (canvas, menus) and the simulation worker thread read it live, so
toggling a tier takes effect on the next tick.  Reads/writes of the enum
attributes are atomic under the GIL, so no lock is needed.

Domains
  real_world — light transport, wavelength loss, photoresistor behaviour
  adc        — ADC voltage→code conversion (window, non-linearity, noise)
  digital    — GPIO / logic levels (kept BASIC; advanced is rarely worth it)

`auto` is a placeholder for a future differentiator that selects tiers from
circuit complexity; auto_select() implements a first-cut heuristic.
"""

from __future__ import annotations
import random
from enum import Enum


class Level(Enum):
    BASIC    = "Basic"
    ADVANCED = "Advanced"


class SimConfig:
    def __init__(self):
        # default: run the real-world / analog path advanced, digital basic
        self.real_world: Level = Level.ADVANCED
        self.adc:        Level = Level.ADVANCED
        self.electrical: Level = Level.BASIC   # runtime MNA nodal solve (opt-in)
        self.digital:    Level = Level.BASIC
        self.auto:       bool  = False

    def is_advanced(self, domain: str) -> bool:
        return getattr(self, domain, Level.BASIC) == Level.ADVANCED

    def __repr__(self):
        return (f"<SimConfig real_world={self.real_world.value} "
                f"adc={self.adc.value} digital={self.digital.value} "
                f"auto={self.auto}>")


# process-wide singleton
CONFIG = SimConfig()


# ── helpers ───────────────────────────────────────────────────────────────────

def sensor_noise(sigma: float) -> float:
    """Gaussian sensor noise, only in the advanced real-world tier (else 0)."""
    return random.gauss(0.0, sigma) if CONFIG.is_advanced("real_world") else 0.0


# ── future differentiator (heuristic first cut) ───────────────────────────────

_REAL_WORLD_TYPES = {
    "photoresistor", "ldr", "loss", "attenuator",
    "Device:R_Photo", "Device:Loss",
}


def auto_select(circuit: dict | None) -> None:
    """
    Pick fidelity tiers from circuit complexity.

    Current rule: if the circuit contains any real-world / analog-sensing part,
    run the real-world and ADC domains advanced; otherwise drop to basic.  This
    is intentionally simple — the hook exists so the differentiator can grow
    (part counts, analog net depth, requested accuracy, …) without touching
    callers.
    """
    if not circuit:
        return
    has_real_world = any(
        p.get("type", "") in _REAL_WORLD_TYPES
        for p in circuit.get("parts", {}).values()
    )
    CONFIG.real_world = Level.ADVANCED if has_real_world else Level.BASIC
    CONFIG.adc        = Level.ADVANCED if has_real_world else Level.BASIC
