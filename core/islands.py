"""
Advanced "analog island" tier (Phase 2a).

The Standard tier propagates voltages with simple series rules, which is wrong
for coupled analog regions — resistor dividers, pull networks, RC nodes, diode
clamps.  This module finds those islands and solves each accurately with the
MNA solver, stitching the island's boundary nets (power rails and other known-
voltage nets) as Thévenin (ideal-source) terminals.

  islands  = find_islands(circuit, rails)
  voltages = solve_island(circuit, island, driven_voltages)

Only the device types the MNA adapter understands participate (R/C/L/diode/
LED/BJT/MOSFET); behavioural sensors keep their own models.
"""

from __future__ import annotations

# circuit `type` strings that the MNA adapter (build_devices) can model
_MNA_TYPES = {
    "resistor", "r", "device:r",
    "capacitor", "c", "device:c",
    "inductor", "l", "device:l",
    "led", "device:led", "device:led_alt", "ir_led",
    "diode", "d", "device:d",
    "npn", "pnp", "bjt", "device:q_npn", "device:q_pnp",
    "nmos", "pmos", "mosfet", "device:nmos", "device:pmos",
}


# ground nets are the solver's implicit reference — never pin them as a source
_GND_NETS = {"GND", "AGND", "DGND", "PGND", "VSS", "0"}


def _is_mna_part(part_def: dict) -> bool:
    return part_def.get("type", "").lower() in _MNA_TYPES


def _part_nets(part_def: dict) -> set[str]:
    return {n for n in (part_def.get("pins") or {}).values() if n}


def find_islands(circuit: dict, rails: set[str]) -> list[dict]:
    """
    Connected components of MNA-modellable parts joined by non-rail nets.

    Rails terminate traversal (they're boundaries shared by everything), so an
    island is a genuinely coupled analog cluster.  Returns dicts with
    `parts`, `internal_nets`, `boundary_nets`.
    """
    parts = circuit.get("parts", {})
    analog = {ref: p for ref, p in parts.items() if _is_mna_part(p)}

    net_parts: dict[str, set[str]] = {}
    for ref, p in analog.items():
        for net in _part_nets(p):
            if net not in rails:
                net_parts.setdefault(net, set()).add(ref)

    seen: set[str] = set()
    islands: list[dict] = []
    for start in analog:
        if start in seen:
            continue
        comp: set[str] = set()
        stack = [start]
        while stack:
            r = stack.pop()
            if r in seen:
                continue
            seen.add(r)
            comp.add(r)
            for net in _part_nets(analog[r]):
                if net in rails:
                    continue
                for nb in net_parts.get(net, ()):
                    if nb not in seen:
                        stack.append(nb)

        nets: set[str] = set()
        for r in comp:
            nets |= _part_nets(analog[r])
        boundary = {n for n in nets if n in rails}
        islands.append({
            "parts": comp,
            "internal_nets": nets - boundary,
            "boundary_nets": boundary,
            "nets": nets,
        })
    return islands


def solve_island(circuit: dict, island: dict,
                 driven_voltages: dict[str, float]) -> dict[str, float]:
    """
    DC-solve one island with the MNA solver.

    Boundary nets with a known voltage (rails / externally driven nets) are
    pinned as ideal Thévenin sources; internal nets are solved.  Returns
    {net: volts} for the island's nets (boundaries echoed back).
    """
    from physics.mna import build_devices, MNASolver

    sub = {"parts": {ref: circuit["parts"][ref] for ref in island["parts"]}}
    # pin known boundary voltages as Thévenin sources — but NOT ground (it is the
    # solver's implicit reference; a GND→GND source is degenerate/singular)
    boundary = {n: driven_voltages[n]
                for n in island["boundary_nets"]
                if n in driven_voltages and n not in _GND_NETS}

    devices = build_devices(sub, boundary)
    solver = MNASolver()
    solver.load(devices)
    v = solver.solve_dc()
    v.update(boundary)         # echo the pinned boundary voltages
    return v
