"""
Converts circuit.json parts + live GPIO bus state → MNA Device list.

The MCU's GPIO output pins become VSource devices (ideal voltage sources).
Power rails (3V3, GND) are also VSource devices.
Passive components are mapped by type string to their MNA device class.
Diodes/LEDs get SPICE Shockley models with sensible defaults per color.
BJTs and MOSFETs are created from descriptor fields.
"""
from __future__ import annotations
from .devices import Resistor, Capacitor, Inductor, VSource, Diode, BJT, MOSFET
from .devices.base import Device

# Forward voltage presets per LED color (matches real-world typical Vf)
_LED_VF: dict[str, float] = {
    "red":    2.0,
    "orange": 2.1,
    "yellow": 2.2,
    "green":  3.3,
    "blue":   3.3,
    "white":  3.2,
    "ir":     1.2,
}

# LED ideality factor (slightly higher than silicon diode due to recombination)
_LED_N = 2.0


def build_devices(circuit: dict,
                  gpio_voltages: dict[str, float]) -> list[Device]:
    """
    Build a complete MNA device list from a circuit dict and current GPIO state.

    gpio_voltages: {net_name: voltage} for every net that is actively driven
                  (includes power rails and MCU outputs).
    """
    devices: list[Device] = []

    # ── power rails and GPIO outputs as ideal voltage sources ─────────────────
    for net, v in gpio_voltages.items():
        devices.append(VSource(f"_pwr_{net}", voltage=v,
                               net_pos=net, net_neg="GND"))

    # ── circuit parts ─────────────────────────────────────────────────────────
    parts = circuit.get("parts", {})
    for ref, part_def in parts.items():
        ptype = part_def.get("type", "").lower()
        pins  = part_def.get("pins", {})
        val   = str(part_def.get("value", ""))

        # ── resistor ─────────────────────────────────────────────────────────
        if ptype in ("resistor", "r", "device:r", "device:r_us"):
            ohm = _parse_value(val)
            if ohm and ohm > 0:
                net_a = pins.get("1", pins.get("A", pins.get("+", "")))
                net_b = pins.get("2", pins.get("B", pins.get("-", "")))
                if net_a and net_b:
                    devices.append(Resistor(ref, ohm, net_a, net_b))

        # ── capacitor ─────────────────────────────────────────────────────────
        elif ptype in ("capacitor", "c", "device:c"):
            farads = _parse_value(val)
            if farads and farads > 0:
                net_p = pins.get("+", pins.get("1", ""))
                net_n = pins.get("-", pins.get("2", "GND"))
                if net_p:
                    devices.append(Capacitor(ref, farads, net_p, net_n))

        # ── inductor ──────────────────────────────────────────────────────────
        elif ptype in ("inductor", "l", "device:l"):
            henry = _parse_value(val)
            if henry and henry > 0:
                net_a = pins.get("1", pins.get("A", ""))
                net_b = pins.get("2", pins.get("B", ""))
                if net_a and net_b:
                    devices.append(Inductor(ref, henry, net_a, net_b))

        # ── LED ───────────────────────────────────────────────────────────────
        elif ptype in ("led", "device:led", "device:led_alt"):
            color = part_def.get("color", "red").lower()
            vf    = float(part_def.get("vf", _LED_VF.get(color, 2.0)))
            # Compute Is from Vf: Is = If / (exp(Vf/(N*Vt)) - 1) at rated current
            if_ma = float(part_def.get("if_ma", 20.0)) * 1e-3
            Vt    = 0.02585
            IS    = if_ma / (np.exp(vf / (_LED_N * Vt)) - 1.0)
            # `series_r` is the *external* current-limit resistor (a separate R
            # device in the netlist); don't double-count it as the diode's bulk
            # resistance. Use an explicit "rs" only if a part declares one.
            RS    = float(part_def.get("rs", 0.0))

            net_a = pins.get("A", pins.get("+", pins.get("1", "")))
            net_k = pins.get("K", pins.get("-", pins.get("2", "")))
            if net_a and net_k:
                devices.append(Diode(ref, net_a, net_k,
                                     IS=max(IS, 1e-20), N=_LED_N, RS=RS))

        # ── generic diode ─────────────────────────────────────────────────────
        elif ptype in ("diode", "d", "device:d"):
            IS = float(part_def.get("IS", 1e-14))
            N  = float(part_def.get("N",  1.0))
            RS = float(part_def.get("RS", 0.0))
            net_a = pins.get("A", pins.get("+", pins.get("1", "")))
            net_k = pins.get("K", pins.get("-", pins.get("2", "")))
            if net_a and net_k:
                devices.append(Diode(ref, net_a, net_k, IS=IS, N=N, RS=RS))

        # ── BJT ───────────────────────────────────────────────────────────────
        elif ptype in ("npn", "pnp", "bjt", "device:q_npn", "device:q_pnp",
                       "transistor_npn", "transistor_pnp"):
            polarity = "PNP" if "pnp" in ptype else "NPN"
            params = {k: float(v) for k, v in part_def.items()
                      if k in ("IS","BF","NF","VAF","IKF","ISE","NE",
                               "BR","NR","VAR","IKR","ISC","NC",
                               "RB","RC","RE","CJE","VJE","MJE",
                               "CJC","VJC","MJC","TF","TR")}
            nc = pins.get("C", pins.get("collector", ""))
            nb = pins.get("B", pins.get("base",      ""))
            ne = pins.get("E", pins.get("emitter",   ""))
            if nc and nb and ne:
                devices.append(BJT(ref, nc, nb, ne, polarity, **params))

        # ── MOSFET ────────────────────────────────────────────────────────────
        elif ptype in ("nmos", "pmos", "mosfet", "device:nmos", "device:pmos"):
            polarity = "PMOS" if "pmos" in ptype else "NMOS"
            params = {k: float(v) for k, v in part_def.items()
                      if k in ("VTO","KP","GAMMA","PHI","LAMBDA",
                               "RD","RS","CBD","CBS","W","L","LD")}
            nd = pins.get("D", pins.get("drain",  ""))
            ng = pins.get("G", pins.get("gate",   ""))
            ns = pins.get("S", pins.get("source", ""))
            nb = pins.get("B", pins.get("bulk",   ""))
            if nd and ng and ns:
                devices.append(MOSFET(ref, nd, ng, ns, nb, polarity, **params))

    return devices


def update_vsources(devices: list[Device], gpio_voltages: dict[str, float]):
    """
    Update VSource voltage values in-place without rebuilding the device list.
    Called every tick when GPIO state changes.
    """
    for dev in devices:
        if isinstance(dev, VSource) and dev.device_id.startswith("_pwr_"):
            net = dev.device_id[5:]   # strip "_pwr_"
            if net in gpio_voltages:
                dev.set_voltage(gpio_voltages[net])


# ── value parser (shared with PassiveModel) ───────────────────────────────────

import re
import numpy as np

_SUFFIX: dict[str, float] = {
    "G": 1e9,  "M": 1e6, "k": 1e3, "K": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
    "R": 1.0,  "r": 1.0,  "F": 1.0, "H": 1.0,
}


def _parse_value(s: str) -> float | None:
    s = s.strip()
    s = re.sub(r'(?i)(ohm|Ω|farad|henry|henries)s?$', '', s).strip()
    m = re.match(r'^([0-9]*\.?[0-9]+)\s*([GMkmµunpRrFH]?)', s)
    if not m:
        return None
    num = float(m.group(1))
    mul = _SUFFIX.get(m.group(2), 1.0)
    return num * mul
