"""
Passive component physics — resistors, capacitors, inductors, diodes.

PassiveModel.load(netlist) auto-instantiates every R, C, L, D in the netlist.
PassiveModel.tick(dt_ms, gpio_bus) runs physics and writes results back to
the GPIO bus.

Value string parsing ("10k", "100nF", "10uH" etc.) handles the common
engineering notation used in KiCad value fields.
"""

from __future__ import annotations
import math
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.netlist import NetList
    from core.protocols.gpio import GPIOBus


# ------------------------------------------------------------ value parser ----

_SUFFIX = {
    "G": 1e9, "M": 1e6, "k": 1e3, "K": 1e3,
    "m": 1e-3, "u": 1e-6, "µ": 1e-6, "n": 1e-9, "p": 1e-12,
    "R": 1.0,  "r": 1.0,  "F": 1.0,  "H": 1.0,
}

def _parse_value(s: str) -> float | None:
    """
    Parse a KiCad component value string to a float.
    Examples: "10k"→10000, "4.7k"→4700, "100nF"→1e-7, "10µH"→1e-5, "0.1"→0.1
    Returns None if unparseable.
    """
    s = s.strip()
    # Strip unit suffixes we don't need (Ω, F, H, Ohm, ohm, etc.)
    s = re.sub(r'(?i)(ohm|Ω|farad|henry|henries)s?$', '', s).strip()

    # Match number + optional multiplier + optional unit letter
    m = re.match(r'^([0-9]*\.?[0-9]+)\s*([GMkmµunpRrFH]?)', s)
    if not m:
        return None
    num = float(m.group(1))
    mul = _SUFFIX.get(m.group(2), 1.0)
    return num * mul


def _parse_r(s: str) -> float | None:
    v = _parse_value(s)
    return v if v and v > 0 else None


def _parse_c(s: str) -> float | None:
    # Strip leading unit markers like "C" in "C100nF" or just parse the number
    s = re.sub(r'(?i)^c\s*', '', s)
    v = _parse_value(s)
    return v if v and v > 0 else None


def _parse_l(s: str) -> float | None:
    s = re.sub(r'(?i)^l\s*', '', s)
    v = _parse_value(s)
    return v if v and v > 0 else None


# ---------------------------------------------------------------- Resistor ----

class Resistor:
    """
    Ideal resistor between two nets.
        I = (V_a - V_b) / R
        P = I² · R  (→ thermal model)
    """

    def __init__(self, instance_id: str, resistance_ohm: float,
                 net_a: str = "", net_b: str = ""):
        if resistance_ohm <= 0:
            raise ValueError(f"{instance_id}: resistance must be > 0 Ω")
        self.id = instance_id
        self.R = resistance_ohm
        self.net_a = net_a          # pin 1 net name
        self.net_b = net_b          # pin 2 net name

        self.current: float = 0.0        # A (positive: a→b)
        self.voltage_drop: float = 0.0   # V
        self.power: float = 0.0          # W

    def tick(self, v_a: float, v_b: float):
        self.voltage_drop = v_a - v_b
        self.current = self.voltage_drop / self.R
        self.power = self.current ** 2 * self.R

    def __repr__(self):
        return (f"<R {self.id} {self.R:.0f}Ω  "
                f"I={self.current*1e3:.2f}mA  P={self.power*1e3:.2f}mW>")


# --------------------------------------------------------------- Capacitor ----

class Capacitor:
    """
    Ideal capacitor between a net and reference (usually GND).
    RC charge/discharge:  V(t) = V_target − (V_target − V_0)·exp(−t/τ)
    """

    def __init__(self, instance_id: str, capacitance_f: float,
                 net_pos: str = "", net_neg: str = "GND",
                 initial_voltage: float = 0.0):
        if capacitance_f <= 0:
            raise ValueError(f"{instance_id}: capacitance must be > 0 F")
        self.id = instance_id
        self.C = capacitance_f
        self.net_pos = net_pos      # positive terminal net
        self.net_neg = net_neg      # negative terminal net (often GND)

        self.voltage: float = initial_voltage
        self.current: float = 0.0
        self.energy: float = 0.5 * self.C * self.voltage ** 2

    def tick(self, v_target: float, r_series_ohm: float, dt_s: float):
        """
        Charge/discharge toward v_target through r_series_ohm.
        v_target is the voltage across the cap (v_pos − v_neg).
        """
        v_prev = self.voltage
        tau = r_series_ohm * self.C
        if tau > 1e-15 and dt_s > 0:
            self.voltage = v_target - (v_target - v_prev) * math.exp(-dt_s / tau)
        else:
            self.voltage = v_target
        dv = self.voltage - v_prev
        self.current = (self.C * dv / dt_s) if dt_s > 0 else 0.0
        self.energy = 0.5 * self.C * self.voltage ** 2

    def charge_pct(self, v_supply: float) -> float:
        if v_supply == 0:
            return 0.0
        return max(0.0, min(100.0, 100.0 * self.voltage / v_supply))

    def __repr__(self):
        c_str = f"{self.C*1e6:.3f}µF" if self.C >= 1e-6 else f"{self.C*1e9:.3f}nF"
        return (f"<C {self.id} {c_str}  "
                f"V={self.voltage:.3f}V  I={self.current*1e3:.3f}mA>")


# ---------------------------------------------------------------- Inductor ----

class Inductor:
    """
    Ideal inductor with optional DC winding resistance (DCR).
    Euler integration of V_L = L · dI/dt, corrected for DCR drop.
    Use small dt_ms (≤1 ms) for switching-frequency accuracy.
    """

    def __init__(self, instance_id: str, inductance_h: float,
                 dcr_ohm: float = 0.0,
                 net_a: str = "", net_b: str = "",
                 initial_current: float = 0.0):
        if inductance_h <= 0:
            raise ValueError(f"{instance_id}: inductance must be > 0 H")
        self.id = instance_id
        self.L = inductance_h
        self.DCR = dcr_ohm
        self.net_a = net_a
        self.net_b = net_b

        self.current: float = initial_current
        self.voltage_drop: float = 0.0
        self.energy: float = 0.5 * self.L * self.current ** 2
        self.power: float = 0.0     # DCR copper loss → heat

    def tick(self, v_a: float, v_b: float, dt_s: float):
        v_net = (v_a - v_b) - self.current * self.DCR
        di_dt = v_net / self.L if self.L > 0 else 0.0
        self.current += di_dt * dt_s
        self.voltage_drop = v_a - v_b
        self.energy = 0.5 * self.L * self.current ** 2
        self.power = self.current ** 2 * self.DCR

    def __repr__(self):
        l_str = f"{self.L*1e6:.3f}µH" if self.L >= 1e-6 else f"{self.L*1e9:.3f}nH"
        return (f"<L {self.id} {l_str}  DCR={self.DCR:.3f}Ω  "
                f"I={self.current*1e3:.3f}mA  E={self.energy*1e9:.3f}nJ>")


# ------------------------------------------------------------------ Diode ----

# Forward voltage lookup for common part families identified from value/lib_id.
# Key = lowercase substring to match; value = Vf in volts.
_VF_PATTERNS: list[tuple[str, float]] = [
    ("schottky", 0.3),
    ("bat54",    0.3),
    ("bat46",    0.3),
    ("sb",       0.3),
    ("1n5817",   0.3),
    ("1n5818",   0.3),
    ("1n5819",   0.3),
    ("led",      2.0),
]
_VF_DEFAULT_SILICON  = 0.7
_VF_SKIP_KEYWORDS    = ("zener", "tvs", "bz", "1n47", "1n48", "1n49", "1n50",
                         "1n51", "1n52", "bzt", "bzx")


def _diode_vf(value_str: str, lib_id: str) -> float | None:
    """
    Determine forward voltage (Vf) from the KiCad value string and lib_id.
    Returns None for parts that need a non-diode model (Zener, TVS).
    """
    combined = (value_str + " " + lib_id).lower()
    for kw in _VF_SKIP_KEYWORDS:
        if kw in combined:
            return None
    for kw, vf in _VF_PATTERNS:
        if kw in combined:
            return vf
    return _VF_DEFAULT_SILICON


class Diode:
    """
    Ideal diode with forward voltage drop.

    Conducts when V_anode − V_cathode > Vf:
      → drives cathode net to V_anode − Vf
    Blocks otherwise:
      → releases cathode net (other elements determine its voltage)
    """

    def __init__(self, instance_id: str, vf: float,
                 net_anode: str = "", net_cathode: str = ""):
        if vf < 0:
            raise ValueError(f"{instance_id}: Vf must be >= 0 V")
        self.id          = instance_id
        self.Vf          = vf
        self.net_anode   = net_anode
        self.net_cathode = net_cathode

        self.conducting:       bool  = False
        self.current:          float = 0.0   # A (estimated)
        self.power:            float = 0.0   # W (I × Vf)
        self._cathode_voltage: float = 0.0   # driven value when conducting

    def tick(self, v_anode: float, v_cathode: float) -> None:
        if v_anode - v_cathode > self.Vf:
            self.conducting       = True
            self._cathode_voltage = v_anode - self.Vf
            # Estimate current assuming ~10 Ω source impedance (conservative)
            self.current          = (v_anode - v_cathode - self.Vf) / 10.0
            self.power            = self.current * self.Vf
        else:
            self.conducting       = False
            self._cathode_voltage = 0.0
            self.current          = 0.0
            self.power            = 0.0

    def __repr__(self):
        state = f"Vf={self.Vf}V CONDUCTING" if self.conducting else "BLOCKING"
        return f"<D {self.id}  {state}  I={self.current*1e3:.2f}mA>"


# ---------------------------------------------------------- PassiveModel ------

# Default series resistance used for capacitor tick when the driving net
# has no explicit Thevenin resistance (ideal voltage source assumption).
_DEFAULT_R_SERIES = 1.0   # Ω


# Nets that are power rails — caps between these and GND are decoupling only.
_POWER_NETS = frozenset({
    "VCC", "VDD", "3V3", "+3V3", "3.3V", "VDDI", "VBUS",
    "5V", "+5V", "VUSB", "1V8", "+1V8", "1.2V", "+1.2V",
    "PWR", "POWER", "AVCC", "AVDD", "DVCC", "DVDD",
})
_GND_NETS = frozenset({
    "GND", "AGND", "DGND", "PGND", "VSS", "GNDA",
})


def _is_power(net: str) -> bool:
    return net.upper() in _POWER_NETS


def _is_gnd(net: str) -> bool:
    return net.upper() in _GND_NETS


def _classify(net_a: str, net_b: str) -> str:
    """
    Classify a two-terminal passive by its net connections.

    Returns one of:
      "decouple"   — power→GND cap, skip physics, validate only
      "pull"       — one rail pin + one signal pin, simulate
      "signal"     — both pins on signal nets, simulate
    """
    a_pwr = _is_power(net_a) or _is_gnd(net_a)
    b_pwr = _is_power(net_b) or _is_gnd(net_b)
    if a_pwr and b_pwr:
        return "decouple"
    if a_pwr or b_pwr:
        return "pull"
    return "signal"


class PassiveModel:
    """
    Instantiates and drives all passive components each simulation tick.

    Passives are classified at load time:
      - decouple caps (power→GND): validated but not simulated
      - pull resistors / signal-path R/C/L: fully simulated

    After load(netlist), call tick(dt_ms, gpio_bus) each simulation step.
    """

    def __init__(self):
        self.resistors:  list[Resistor]  = []
        self.capacitors: list[Capacitor] = []
        self.inductors:  list[Inductor]  = []
        self.diodes:     list[Diode]     = []
        self.decouple_caps: list[dict] = []
        self.validation_errors: list[str] = []

    # ---------------------------------------------------------------- load ----

    def load(self, netlist: NetList):
        """
        Instantiate signal-path R/C/L from the netlist.
        Decoupling caps (power→GND) are recorded for DRC but not simulated.
        """
        self.resistors.clear()
        self.capacitors.clear()
        self.inductors.clear()
        self.diodes.clear()
        self.decouple_caps.clear()
        self.validation_errors.clear()

        for ref, comp in netlist.components.items():
            pins  = comp.get("pins", {})
            val_str = comp.get("value", "")
            p1 = pins.get("1", "")
            p2 = pins.get("2", "")
            kind = _classify(p1, p2)

            prefix = ref.rstrip("0123456789").upper()

            if prefix == "R" or prefix == "FB":
                ohm = _parse_r(val_str)
                if ohm is None:
                    continue
                if kind == "decouple":
                    # Power-rail resistor (inrush limiter etc.) — validate, skip
                    self.decouple_caps.append({"ref": ref, "type": "R",
                                               "value": val_str, "nets": (p1, p2)})
                else:
                    self.resistors.append(Resistor(ref, ohm, net_a=p1, net_b=p2))

            elif prefix == "C":
                farads = _parse_c(val_str)
                if farads is None:
                    continue
                if kind == "decouple":
                    # Decoupling cap — record for DRC, do not simulate
                    self.decouple_caps.append({"ref": ref, "type": "C",
                                               "value": val_str, "nets": (p1, p2)})
                else:
                    self.capacitors.append(Capacitor(ref, farads, net_pos=p1, net_neg=p2))

            elif prefix == "L":
                henries = _parse_l(val_str)
                if henries is None:
                    continue
                self.inductors.append(Inductor(ref, henries, net_a=p1, net_b=p2))

            elif prefix in ("D", "LED"):
                # KiCad diode pins are named A (anode) and K (cathode).
                # Some symbols use + / - or AN / CA as alternatives.
                net_a = pins.get("A", pins.get("+", pins.get("AN", "")))
                net_k = pins.get("K", pins.get("-", pins.get("CA", pins.get("C", ""))))
                if not net_a or not net_k:
                    continue
                lib_id = comp.get("part", "")
                vf = _diode_vf(val_str, lib_id)
                if vf is None:
                    continue   # Zener / TVS — skip
                self.diodes.append(Diode(ref, vf, net_anode=net_a, net_cathode=net_k))

    def add_resistor(self, r: Resistor):
        self.resistors.append(r)

    def add_capacitor(self, c: Capacitor):
        self.capacitors.append(c)

    def add_inductor(self, l: Inductor):
        self.inductors.append(l)

    def add_diode(self, d: Diode):
        self.diodes.append(d)

    # --------------------------------------------------------------- tick ----

    def tick(self, dt_ms: float, gpio_bus: GPIOBus):
        """
        Advance all passive physics by dt_ms milliseconds.
        Reads net voltages from gpio_bus; writes back intermediate node
        voltages for passives in series (voltage divider output, etc.).
        """
        dt_s = dt_ms / 1000.0
        vmap = gpio_bus.voltages()

        for r in self.resistors:
            v_a = vmap.get(r.net_a, 0.0)
            v_b = vmap.get(r.net_b, 0.0)
            r.tick(v_a, v_b)

        for c in self.capacitors:
            v_pos = vmap.get(c.net_pos, 0.0)
            v_neg = vmap.get(c.net_neg, 0.0)
            v_target = v_pos - v_neg
            # Find series resistance: sum of R sharing net_pos with this cap
            r_series = sum(
                r.R for r in self.resistors
                if r.net_b == c.net_pos or r.net_a == c.net_pos
            ) or _DEFAULT_R_SERIES
            c.tick(v_target, r_series, dt_s)
            # Write the capacitor junction voltage back to the bus
            if c.net_pos:
                gpio_bus.drive(c.net_pos, f"_cap_{c.id}",
                               v_neg + c.voltage)

        for l in self.inductors:
            v_a = vmap.get(l.net_a, 0.0)
            v_b = vmap.get(l.net_b, 0.0)
            l.tick(v_a, v_b, dt_s)

        for d in self.diodes:
            v_a = vmap.get(d.net_anode,   0.0)
            v_k = vmap.get(d.net_cathode, 0.0)
            d.tick(v_a, v_k)
            if d.conducting and d.net_cathode:
                gpio_bus.drive(d.net_cathode, f"_diode_{d.id}", d._cathode_voltage)
            elif d.net_cathode:
                gpio_bus.release(d.net_cathode, f"_diode_{d.id}")
