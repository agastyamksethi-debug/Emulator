"""
Circuit analyzer / simulation planner — the "compile" pass (Layer 1).

Runs before simulation.  Given a circuit dict + part pin-contracts, it:
  1. builds the net→pins map,
  2. runs ERC checks (floating required/inputs, power-window, missing pull-ups),
  3. identifies electrically-significant phenomena (power-rail bring-up, I2C/bus
     RC rise-time) and characterizes each with a closed-form Intermediate model
     across tolerance corners,
  4. memoizes characterizations by a content-hash key so re-runs of an unchanged
     region are free.

Output: a SimPlan (phenomena + their characterizations) and a list of
Diagnostics.  GUI overlays and the MNA "advanced island" solver are Phase 2.

Dependency-light on purpose (no bus/Qt) so it can run as a fast pre-pass.
"""

from __future__ import annotations
import hashlib
import json
import math
import os
from dataclasses import dataclass, field

from core.contracts import (
    PinRole, Diagnostic, Severity, load_pin_contracts,
    component_tolerance, corners,
)
from physics.passive import _parse_value

_PARTS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "parts"))

# default lumped capacitance contributed by each device pin on a bus (farads)
_PIN_CAP = 5e-12
# I2C rise-time limits per mode (seconds): mode -> max t_r (10%->90%)
_I2C_TR_LIMIT = {"Standard (100 kHz)": 1000e-9, "Fast (400 kHz)": 300e-9}


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class Phenomenon:
    kind:    str                       # "power_sequence" | "bus_rc"
    tier:    str                       # "intermediate" | "advanced" | "standard"
    region:  tuple[str, ...]           # nets involved
    parts:   tuple[str, ...]           # refs involved
    params:  dict                      # inputs to the characterizer
    result:  dict = field(default_factory=dict)   # characterization output
    cache_hit: bool = False


@dataclass
class SimPlan:
    phenomena:   list[Phenomenon]
    diagnostics: list[Diagnostic]

    def errors(self):   return [d for d in self.diagnostics if d.severity == Severity.ERROR]
    def warnings(self): return [d for d in self.diagnostics if d.severity == Severity.WARNING]


# ── characterization cache (content-hash memoization) ──────────────────────────

class CharacterizationCache:
    def __init__(self, path: str | None = None):
        self._mem: dict[str, dict] = {}
        self._path = path
        self.misses = 0
        self.hits = 0
        if path and os.path.exists(path):
            try:
                self._mem = json.load(open(path))
            except Exception:
                self._mem = {}

    @staticmethod
    def key(kind: str, payload: dict) -> str:
        blob = json.dumps({"kind": kind, **payload}, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    def get_or_compute(self, key: str, fn) -> tuple[dict, bool]:
        if key in self._mem:
            self.hits += 1
            return self._mem[key], True
        self.misses += 1
        val = fn()
        self._mem[key] = val
        return val, False

    def flush(self):
        if self._path:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            json.dump(self._mem, open(self._path, "w"), indent=2)


# ── descriptor / netlist helpers ────────────────────────────────────────────────

def _load_descriptor(part_def: dict) -> dict:
    t = part_def.get("type", "")
    path = os.path.join(_PARTS_DIR, t, "descriptor.json")
    base = json.load(open(path)) if os.path.exists(path) else {}
    merged = {**base, **{k: v for k, v in part_def.items() if k != "pins"}}
    merged["pins"] = {**base.get("pins", {}), **part_def.get("pins", {})}
    return merged


def _is_resistor(ref: str) -> bool:  return ref.rstrip("0123456789").upper() == "R"
def _is_cap(ref: str) -> bool:       return ref.rstrip("0123456789").upper() == "C"


def _build_nets(circuit: dict, descriptors: dict) -> dict[str, list[tuple]]:
    """net -> list of (ref, pin, role)."""
    nets: dict[str, list[tuple]] = {}
    for ref, pdef in circuit.get("parts", {}).items():
        contracts = load_pin_contracts(descriptors[ref])
        for pin, net in (pdef.get("pins") or {}).items():
            role = contracts[pin].role if pin in contracts else PinRole.PASSIVE
            nets.setdefault(net, []).append((ref, pin, role))
    return nets


# ── analysis ────────────────────────────────────────────────────────────────────

def analyze(circuit: dict, cache: CharacterizationCache | None = None,
            advanced: bool = False) -> SimPlan:
    cache = cache or CharacterizationCache()
    descriptors = {ref: _load_descriptor(p) for ref, p in circuit.get("parts", {}).items()}
    power = circuit.get("power", {})                 # net -> voltage
    nets = _build_nets(circuit, descriptors)
    diags: list[Diagnostic] = []
    phenomena: list[Phenomenon] = []

    # ---- ERC: per-pin contract checks -------------------------------------------
    for ref, pdef in circuit.get("parts", {}).items():
        contracts = load_pin_contracts(descriptors[ref])
        pins = pdef.get("pins") or {}
        for pin, c in contracts.items():
            net = pins.get(pin)

            if c.required and not net:
                diags.append(Diagnostic(Severity.ERROR,
                    f"required pin '{pin}' is not connected",
                    code="erc.unconnected", parts=(ref,), pins=(pin,)))
                continue
            if not net:
                continue

            others = [x for x in nets.get(net, []) if not (x[0] == ref and x[1] == pin)]
            on_rail = net in power

            # floating: a driven/sensing pin alone on its net with no rail/driver
            if not others and not on_rail and c.role in (
                    PinRole.DIGITAL_IN, PinRole.I2C, PinRole.ANALOG_IN, PinRole.POWER_IN):
                sev = Severity.ERROR if c.required else Severity.WARNING
                diags.append(Diagnostic(sev,
                    f"{c.role.value} pin '{pin}' on net '{net}' is floating "
                    f"(nothing else connected)",
                    code="erc.floating", parts=(ref,), pins=(pin,), nets=(net,)))

            # power window
            if c.role == PinRole.POWER_IN and on_rail and c.v_min is not None:
                v = power[net]
                if not (c.v_min <= v <= (c.v_max if c.v_max is not None else c.v_min)):
                    diags.append(Diagnostic(Severity.ERROR,
                        f"power pin '{pin}' on '{net}' = {v} V, outside "
                        f"[{c.v_min}, {c.v_max}] V",
                        code="erc.power_window", parts=(ref,), pins=(pin,), nets=(net,)))
            if c.role == PinRole.POWER_IN and net and not on_rail and not others:
                diags.append(Diagnostic(Severity.ERROR,
                    f"power pin '{pin}' net '{net}' is not a power rail",
                    code="erc.no_power", parts=(ref,), pins=(pin,), nets=(net,)))

    # ---- ERC + phenomenon: I2C / open-drain buses -------------------------------
    seen_bus: set[str] = set()
    for net, conns in nets.items():
        roles = {role for _, _, role in conns}
        if not (roles & {PinRole.I2C, PinRole.OPEN_DRAIN}):
            continue
        if net in seen_bus:
            continue
        seen_bus.add(net)

        pullup = _find_pullup(net, circuit, descriptors, power)
        if pullup is None:
            diags.append(Diagnostic(Severity.WARNING,
                f"bus net '{net}' needs a pull-up but none was found "
                f"(line will float / logic indeterminate)",
                code="erc.missing_pullup", nets=(net,),
                parts=tuple(r for r, _, _ in conns)))
            continue

        r_ref, r_ohm = pullup
        c_bus = _bus_capacitance(net, conns, circuit, descriptors)
        r_tol = component_tolerance(r_ref, _value_def(circuit, r_ref))
        params = {"net": net, "r_ohm": r_ohm, "r_tol": r_tol,
                  "c_bus": c_bus, "vdd": _bus_vdd(net, circuit, descriptors, power)}
        key = cache.key("bus_rc", params)
        result, hit = cache.get_or_compute(key, lambda p=params: _characterize_bus_rc(p))
        ph = Phenomenon("bus_rc", "intermediate", (net,),
                        tuple(r for r, _, _ in conns), params, result, hit)
        phenomena.append(ph)
        for mode, ok in result["modes"].items():
            if not ok:
                diags.append(Diagnostic(Severity.WARNING,
                    f"bus '{net}': worst-case rise time {result['t_rise_max_ns']:.0f} ns "
                    f"exceeds the {mode} limit — won't reliably run at that speed",
                    code="erc.bus_speed", nets=(net,)))

    # ---- phenomenon: power-rail bring-up ----------------------------------------
    for rail, v in power.items():
        if v <= 0:                       # skip GND
            continue
        c_bulk = _rail_capacitance(rail, nets, circuit, descriptors)
        if c_bulk <= 0:
            continue
        params = {"rail": rail, "vdd": v, "c_bulk": c_bulk, "r_src": 10.0}
        key = cache.key("power_sequence", params)
        result, hit = cache.get_or_compute(key, lambda p=params: _characterize_power_ramp(p))
        phenomena.append(Phenomenon("power_sequence", "intermediate", (rail,),
                                    (), params, result, hit))

    # ---- Advanced tier: solve coupled analog islands with MNA -------------------
    if advanced:
        _analyze_islands(circuit, descriptors, nets, power, phenomena, diags)

    return SimPlan(phenomena, diags)


def _analyze_islands(circuit, descriptors, nets, power, phenomena, diags):
    """Solve coupled analog clusters with MNA; flag indeterminate logic levels."""
    from core.islands import find_islands, solve_island

    rails = set(power)
    driven = dict(power)                 # known boundary voltages (rails)
    vdd = max([v for v in power.values()] + [3.3])
    v_il, v_ih = 0.3 * vdd, 0.7 * vdd    # CMOS-ish forbidden band

    islands = find_islands(circuit, rails)
    _analyze_gpio_drive(circuit, descriptors, islands, driven, phenomena, diags)
    _analyze_supply(circuit, descriptors, power, phenomena, diags)

    for island in islands:
        if not island["internal_nets"]:
            continue
        try:
            volts = solve_island(circuit, island, driven)
        except Exception as exc:         # numerical / unsupported device — skip
            diags.append(Diagnostic(Severity.INFO,
                f"analog island {sorted(island['parts'])} not solved: {exc}",
                code="mna.skip", parts=tuple(sorted(island["parts"]))))
            continue

        phenomena.append(Phenomenon(
            "analog_island", "advanced",
            tuple(sorted(island["internal_nets"])),
            tuple(sorted(island["parts"])),
            {"boundary": sorted(island["boundary_nets"])},
            {"voltages": {n: round(volts.get(n, 0.0), 4)
                          for n in sorted(island["internal_nets"])}}))

        # indeterminate-logic check on any digital/i2c input sitting on an
        # internal node whose solved voltage lands in the forbidden band
        for net in island["internal_nets"]:
            v = volts.get(net)
            if v is None or not (v_il < v < v_ih):
                continue
            for ref, pin, role in nets.get(net, []):
                if role in (PinRole.DIGITAL_IN, PinRole.I2C):
                    diags.append(Diagnostic(Severity.WARNING,
                        f"{role.value} pin '{pin}' on '{net}' solves to "
                        f"{v:.2f} V — indeterminate logic level "
                        f"(forbidden band {v_il:.2f}–{v_ih:.2f} V)",
                        code="erc.indeterminate_level",
                        parts=(ref,), pins=(pin,), nets=(net,)))


def _analyze_gpio_drive(circuit, descriptors, islands, driven, phenomena, diags):
    """Worst-case MCU GPIO drive current into each load island → over-current."""
    from core.mna_ic import mcu_output_pins, gpio_drive_current

    by_net = {}
    for isl in islands:
        for n in isl["nets"]:
            by_net.setdefault(n, isl)

    for ref, pin, net, specs in mcu_output_pins(circuit, descriptors, set(driven)):
        isl = by_net.get(net)
        if isl is None:
            continue
        try:
            i_a = gpio_drive_current(circuit, isl, net, specs["voh"],
                                     specs["rout"], driven)
        except Exception:
            continue
        i_ma = i_a * 1000.0
        phenomena.append(Phenomenon(
            "gpio_drive", "advanced", (net,), (ref,),
            {"pin": pin, "imax_ma": specs["imax_a"] * 1000.0},
            {"i_ma": round(i_ma, 2)}))
        if i_a > specs["imax_a"]:
            diags.append(Diagnostic(Severity.ERROR,
                f"GPIO '{pin}' would source {i_ma:.0f} mA into '{net}' if driven "
                f"HIGH — exceeds the {specs['imax_a']*1000:.0f} mA pin limit "
                f"(add a series current-limit resistor)",
                code="erc.gpio_overcurrent", parts=(ref,), pins=(pin,), nets=(net,)))
        elif i_a > 0.6 * specs["imax_a"]:
            diags.append(Diagnostic(Severity.WARNING,
                f"GPIO '{pin}' would source {i_ma:.0f} mA into '{net}' — near the "
                f"{specs['imax_a']*1000:.0f} mA pin limit",
                code="erc.gpio_highcurrent", parts=(ref,), pins=(pin,), nets=(net,)))


def _analyze_supply(circuit, descriptors, power, phenomena, diags):
    """Per-rail supply-current tally from parts' idd_ma."""
    from core.mna_ic import supply_currents

    totals = supply_currents(circuit, descriptors, power)
    for rail, ma in totals.items():
        phenomena.append(Phenomenon("supply_current", "intermediate", (rail,), (),
                                    {"rail": rail}, {"current_ma": round(ma, 2)}))


# ── topology probes ───────────────────────────────────────────────────────────

def _value_def(circuit: dict, ref: str) -> dict:
    return circuit.get("parts", {}).get(ref, {})


def _find_pullup(net, circuit, descriptors, power):
    """A resistor with one pin on `net` and the other on a power rail → (ref, ohms)."""
    for ref, pdef in circuit.get("parts", {}).items():
        if not _is_resistor(ref):
            continue
        pins = list((pdef.get("pins") or {}).values())
        if net in pins and any(p in power and power[p] > 0 for p in pins):
            ohm = _parse_value(str(pdef.get("value", ""))) or 0.0
            if ohm > 0:
                return ref, ohm
    return None


def _bus_capacitance(net, conns, circuit, descriptors) -> float:
    """Lumped bus C: explicit caps on the net + a default per device pin."""
    c = _PIN_CAP * len(conns)
    for ref, pdef in circuit.get("parts", {}).items():
        if _is_cap(ref) and net in (pdef.get("pins") or {}).values():
            c += _parse_value(str(pdef.get("value", ""))) or 0.0
    return c


def _bus_vdd(net, circuit, descriptors, power) -> float:
    pu = _find_pullup(net, circuit, descriptors, power)
    if pu:
        for ref, pdef in circuit.get("parts", {}).items():
            if ref == pu[0]:
                for p in (pdef.get("pins") or {}).values():
                    if p in power and power[p] > 0:
                        return power[p]
    return max([v for v in power.values()] + [3.3])


def _rail_capacitance(rail, nets, circuit, descriptors) -> float:
    """Sum of caps between this rail and any other net (decoupling/bulk)."""
    c = 0.0
    for ref, pdef in circuit.get("parts", {}).items():
        if _is_cap(ref) and rail in (pdef.get("pins") or {}).values():
            c += _parse_value(str(pdef.get("value", ""))) or 0.0
    return c


# ── intermediate characterizers (closed form, tolerance corners) ────────────────

def _characterize_bus_rc(p: dict) -> dict:
    # 10%->90% rise time of an RC pull-up:  t_r = 0.8473 · R · C
    r_lo, r_nom, r_hi = corners(p["r_ohm"], p["r_tol"])
    c = p["c_bus"]
    t = lambda r: 0.8473 * r * c
    t_nom, t_max = t(r_nom), t(r_hi)
    modes = {m: (t_max <= lim) for m, lim in _I2C_TR_LIMIT.items()}
    return {
        "t_rise_ns":     t_nom * 1e9,
        "t_rise_max_ns": t_max * 1e9,
        "t_rise_min_ns": t(r_lo) * 1e9,
        "c_bus_pf":      c * 1e12,
        "modes":         modes,
    }


def _characterize_power_ramp(p: dict) -> dict:
    # rail charges through source impedance: V(t)=Vdd(1-e^-t/τ), τ=R_src·C
    tau = p["r_src"] * p["c_bulk"]
    return {
        "tau_us":   tau * 1e6,
        "t_90_us":  tau * math.log(10) * 1e6,    # time to reach 90 %
        "t_99_us":  tau * math.log(100) * 1e6,
        "c_bulk_uf": p["c_bulk"] * 1e6,
    }
