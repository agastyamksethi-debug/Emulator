"""
MNA modelling of ICs / MCUs (Phase: MNA of IC and MCU).

Passives alone don't catch the classic pre-production mistakes that involve the
chip itself — most importantly driving a load past a GPIO's current limit
(an LED with no series resistor straight off a pin, a coil/relay direct-driven,
a short to ground).  This module models an MCU output pin as a Thévenin driver
(V_OH behind an output resistance) and solves the load network with MNA to get
the true pin current, plus a per-rail supply-current tally.

Pin states are firmware-dependent, so we evaluate the deterministic worst case:
"if this output is driven HIGH, how much current flows into whatever it's wired
to?"  That's exactly the pre-fab question.
"""

from __future__ import annotations

_GND_NETS = {"GND", "AGND", "DGND", "PGND", "VSS", "0"}

# ESP32-class defaults when a descriptor doesn't specify
_DEF_ROUT_OHM = 25.0
_DEF_IMAX_MA  = 40.0


def mcu_output_pins(circuit: dict, descriptors: dict, rails: set[str]):
    """
    Yield (ref, pin, net, specs) for every MCU GPIO pin wired to a non-rail net.

    An MCU is any part whose descriptor has a gpio_map; its GPIO pin names are
    that map's values.  `specs` = {voh, rout, imax_a}.
    """
    for ref, pdef in circuit.get("parts", {}).items():
        desc = descriptors[ref]
        gpio_map = desc.get("gpio_map")
        if not gpio_map:
            continue
        gpio_pins = set(gpio_map.values())
        vdd = float(desc.get("gpio_voh", 0.0)) or _vdd(circuit)
        specs = {
            "voh":    vdd,
            "rout":   float(desc.get("gpio_rout_ohm", _DEF_ROUT_OHM)),
            "imax_a": float(desc.get("gpio_imax_ma", _DEF_IMAX_MA)) / 1000.0,
        }
        for pin, net in (pdef.get("pins") or {}).items():
            if pin in gpio_pins and net and net not in rails:
                yield ref, pin, net, specs


def gpio_drive_current(circuit: dict, island: dict, pin_net: str,
                       voh: float, rout: float,
                       driven_voltages: dict[str, float]) -> float:
    """
    Worst-case current an MCU output sources when it drives `pin_net` HIGH into
    the island's load network.  Models the driver as VSource(voh) + Rout, solves
    DC, and returns |branch current| (amps).
    """
    from physics.mna import build_devices, MNASolver, VSource, Resistor

    sub = {"parts": {ref: circuit["parts"][ref] for ref in island["parts"]}}
    boundary = {n: driven_voltages[n]
                for n in island["boundary_nets"]
                if n in driven_voltages and n not in _GND_NETS}

    devices = build_devices(sub, boundary)
    devices.append(VSource("_gpio_src", voltage=voh, net_pos="_gpio_drv", net_neg="GND"))
    devices.append(Resistor("_gpio_rout", rout, "_gpio_drv", pin_net))

    solver = MNASolver()
    solver.load(devices)
    solver.solve_dc()
    return abs(solver.branch_current("_gpio_src", "v"))


def supply_currents(circuit: dict, descriptors: dict,
                    power: dict) -> dict[str, float]:
    """Total quiescent/active current (mA) drawn from each rail by parts with idd_ma."""
    rails = set(power)
    totals: dict[str, float] = {r: 0.0 for r in rails}
    from core.contracts import load_pin_contracts, PinRole
    for ref, pdef in circuit.get("parts", {}).items():
        idd = float(descriptors[ref].get("idd_ma", 0.0))
        if idd <= 0:
            continue
        contracts = load_pin_contracts(descriptors[ref])
        for pin, net in (pdef.get("pins") or {}).items():
            c = contracts.get(pin)
            if c and c.role == PinRole.POWER_IN and net in totals:
                totals[net] += idd
                break
    return {r: v for r, v in totals.items() if v > 0}


def _vdd(circuit: dict) -> float:
    return max([v for v in circuit.get("power", {}).values()] + [3.3])
