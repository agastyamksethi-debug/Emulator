"""
Power-rail model.

Rails are NOT ideal sources. Every rail has a small Thévenin source impedance
(regulator output + wiring) so heavy loads sag it — stable under normal draw,
but a short or an over-budget load browns it out.

circuit.json `power` entries accept either form:
    "3V3": 3.3                          # default source impedance
    "3V3": { "v": 3.3, "r_src": 0.5 }   # explicit impedance (e.g. a weak rail)

Ground nets are the reference (zero impedance).
"""

from __future__ import annotations

# realistic default: a decent regulator + a bit of wiring. ~10 mV sag at 100 mA,
# but ~0.3 V at 3 A — enough to brown out a 3.3 V part on a heavy/shorted rail.
_DEFAULT_RSRC = 0.1
_GND_NETS = {"GND", "AGND", "DGND", "PGND", "VSS", "0"}


def _entry(val) -> tuple[float, float]:
    if isinstance(val, dict):
        v = float(val.get("v", val.get("voltage", 0.0)))
        return v, float(val.get("r_src", _DEFAULT_RSRC))
    return float(val), _DEFAULT_RSRC


def parse_power(circuit: dict) -> dict[str, tuple[float, float]]:
    """net → (voltage, source_resistance_ohms). Ground nets get 0 Ω."""
    out: dict[str, tuple[float, float]] = {}
    for net, val in (circuit.get("power") or {}).items():
        v, r = _entry(val)
        out[net] = (v, 0.0 if net in _GND_NETS else r)
    return out


def voltages(circuit: dict) -> dict[str, float]:
    """net → nominal voltage (drop-in for the old `power.items()` usage)."""
    return {net: v for net, (v, _r) in parse_power(circuit).items()}


def rail_source_devices(circuit: dict, rail_v: dict | None = None):
    """MNA devices modelling each rail as VSource(v) behind its source impedance.

    `rail_v` optionally overrides the nominal voltage per rail (e.g. the live,
    rippled value from the bus) so ripple flows through the solve."""
    from physics.mna import VSource, Resistor
    devs = []
    for net, (v0, r) in parse_power(circuit).items():
        if net in _GND_NETS:
            continue
        v = rail_v.get(net, v0) if rail_v else v0
        if r > 0:
            src = f"_railsrc_{net}"
            devs.append(VSource(f"_railvs_{net}", v, net_pos=src, net_neg="GND"))
            devs.append(Resistor(f"_railr_{net}", r, src, net))
        else:
            devs.append(VSource(f"_railvs_{net}", v, net_pos=net, net_neg="GND"))
    return devs


def solve_loaded_rails(circuit: dict, descriptors: dict) -> dict[str, float]:
    """
    DC-solve the rails under their static loads (IC quiescent current + passive
    loads), returning each rail's sagged voltage.
    """
    from physics.mna import build_devices, MNASolver, ISource
    from core.contracts import load_pin_contracts, PinRole

    devices = build_devices(circuit, {})          # passives only, no ideal rails
    devices += rail_source_devices(circuit)

    # IC quiescent current as a sink from each powered part's VCC to GND
    for ref, pdef in circuit.get("parts", {}).items():
        idd = float(descriptors.get(ref, {}).get("idd_ma", 0.0)) / 1000.0
        if idd <= 0:
            continue
        contracts = load_pin_contracts(descriptors.get(ref, {}))
        for pin, net in (pdef.get("pins") or {}).items():
            c = contracts.get(pin)
            if c and c.role == PinRole.POWER_IN and net not in _GND_NETS:
                # sink idd out of the rail (pos=GND draws current from `net`)
                devices.append(ISource(f"_idd_{ref}", idd, net_pos="GND", net_neg=net))
                break

    solver = MNASolver()
    solver.load(devices)
    v = solver.solve_dc()
    for net, (volt, _r) in parse_power(circuit).items():
        v.setdefault(net, volt)
    return v
