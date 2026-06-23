"""
Pin electrical contracts and component tolerances — the metadata layer (Layer 0)
that the ERC pass and the simulation planner reason over.

Descriptors may declare:

  "pin_contracts": {
    "VCC": {"role": "power_in", "required": true, "v_min": 2.3, "v_max": 3.6},
    "SDA": {"role": "i2c", "required": true, "needs_pullup": true},
    ...
  },
  "tolerance": 0.03            # fractional component tolerance (±3 %)

Pins with no contract default to PASSIVE/optional.  Components with no tolerance
fall back to class defaults derived from the reference-designator prefix.

This module is intentionally dependency-free (no bus / Qt imports) so it can be
used by static analysis before any simulation starts.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum


class PinRole(str, Enum):
    POWER_IN    = "power_in"
    POWER_OUT   = "power_out"
    GND         = "gnd"
    DIGITAL_IN  = "digital_in"
    DIGITAL_OUT = "digital_out"
    OPEN_DRAIN  = "open_drain"
    ANALOG_IN   = "analog_in"
    ANALOG_OUT  = "analog_out"
    I2C         = "i2c"
    PASSIVE     = "passive"
    NC          = "nc"


class Severity(str, Enum):
    INFO    = "info"
    WARNING = "warning"
    ERROR   = "error"


@dataclass(frozen=True)
class PinContract:
    name:         str
    role:         PinRole = PinRole.PASSIVE
    required:     bool    = False
    v_min:        float | None = None
    v_max:        float | None = None
    needs_pullup: bool    = False


@dataclass(frozen=True)
class Diagnostic:
    """A single ERC / planner finding, routed to the diagnostics stream."""
    severity: Severity
    message:  str
    code:     str = ""
    parts:    tuple[str, ...] = ()
    nets:     tuple[str, ...] = ()
    pins:     tuple[str, ...] = ()

    def __str__(self) -> str:
        loc = " ".join(filter(None, [
            ",".join(self.parts), ",".join(self.pins), ",".join(self.nets)]))
        tag = f"[{self.code}] " if self.code else ""
        return f"{self.severity.value.upper():7} {tag}{self.message}" + (f"  ({loc})" if loc else "")


# ── component tolerances ──────────────────────────────────────────────────────

# fractional tolerance defaults by reference-designator class
_DEFAULT_TOLERANCE = {"R": 0.01, "C": 0.10, "L": 0.10, "FB": 0.10}
_DEFAULT_TOL_OTHER = 0.05


def default_tolerance(reference: str) -> float:
    prefix = reference.rstrip("0123456789").upper()
    for n in range(len(prefix), 0, -1):
        if prefix[:n] in _DEFAULT_TOLERANCE:
            return _DEFAULT_TOLERANCE[prefix[:n]]
    return _DEFAULT_TOL_OTHER


def component_tolerance(reference: str, descriptor: dict) -> float:
    """Fractional tolerance for a component (descriptor override, else class default)."""
    if descriptor and "tolerance" in descriptor:
        return float(descriptor["tolerance"])
    return default_tolerance(reference)


def corners(nominal: float, tolerance: float) -> tuple[float, float, float]:
    """(min, nominal, max) corner values for a tolerance band."""
    return (nominal * (1.0 - tolerance), nominal, nominal * (1.0 + tolerance))


# ── pin contracts ─────────────────────────────────────────────────────────────

def load_pin_contracts(descriptor: dict) -> dict[str, PinContract]:
    """Parse a descriptor's pin_contracts block into PinContract objects."""
    out: dict[str, PinContract] = {}
    for name, spec in (descriptor.get("pin_contracts") or {}).items():
        role = spec.get("role", "passive")
        try:
            role = PinRole(role)
        except ValueError:
            role = PinRole.PASSIVE
        out[name] = PinContract(
            name=name,
            role=role,
            required=bool(spec.get("required", False)),
            v_min=spec.get("v_min"),
            v_max=spec.get("v_max"),
            needs_pullup=bool(spec.get("needs_pullup", False)),
        )
    return out


def validate_descriptor(reference: str, descriptor: dict) -> list[Diagnostic]:
    """Self-consistency checks on a part's contract metadata (well-formedness)."""
    diags: list[Diagnostic] = []
    pins = set((descriptor.get("pins") or {}).keys())
    valid_roles = {r.value for r in PinRole}
    for name, spec in (descriptor.get("pin_contracts") or {}).items():
        if pins and name not in pins:
            diags.append(Diagnostic(
                Severity.WARNING,
                f"pin_contract references unknown pin '{name}'",
                code="contract.unknown_pin", parts=(reference,), pins=(name,)))
        if spec.get("role") not in valid_roles:
            diags.append(Diagnostic(
                Severity.ERROR,
                f"pin '{name}' has invalid role '{spec.get('role')}'",
                code="contract.bad_role", parts=(reference,), pins=(name,)))
        if spec.get("role") == "power_in" and spec.get("v_min") is None:
            diags.append(Diagnostic(
                Severity.INFO,
                f"power pin '{name}' has no voltage window (v_min/v_max)",
                code="contract.no_vrange", parts=(reference,), pins=(name,)))
    if "tolerance" in descriptor:
        t = descriptor["tolerance"]
        if not isinstance(t, (int, float)) or not (0.0 <= float(t) < 1.0):
            diags.append(Diagnostic(
                Severity.ERROR,
                f"tolerance {t!r} must be a fraction in [0, 1)",
                code="contract.bad_tolerance", parts=(reference,)))
    return diags
