"""
Linear MNA devices: Resistor, Capacitor, Inductor, VSource, ISource.

Capacitor and Inductor use trapezoidal integration (SPICE default) which
gives second-order accuracy — better than backward Euler for the same dt.

Trapezoidal companion models:
  Capacitor:  Geq = 2C/dt,   Ieq = Geq*Vc(t-dt) + Ic(t-dt)
  Inductor:   Geq = dt/(2L), Ieq = IL(t-dt) + Geq*(Va-Vb)(t-dt)
"""
from __future__ import annotations
import numpy as np
from .base import Device, _stamp_g, _stamp_i, _stamp_v


class Resistor(Device):
    """Ideal resistor — one linear stamp, no history."""

    def __init__(self, device_id: str, r_ohm: float,
                 net_a: str = "", net_b: str = ""):
        super().__init__(device_id)
        if r_ohm <= 0:
            raise ValueError(f"Resistor {device_id}: R must be > 0 Ω")
        self.R    = float(r_ohm)
        self.net_a = net_a
        self.net_b = net_b

    def nets(self):
        return [n for n in (self.net_a, self.net_b) if n]

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        g = 1.0 / self.R
        _stamp_g(A, self._n(self.net_a, node_map),
                    self._n(self.net_b, node_map), g)


class Capacitor(Device):
    """
    Capacitor with trapezoidal companion model.
    Geq = 2C/dt,  Ieq = Geq*Vc_prev + Ic_prev
    """

    def __init__(self, device_id: str, c_f: float,
                 net_pos: str = "", net_neg: str = ""):
        super().__init__(device_id)
        if c_f <= 0:
            raise ValueError(f"Capacitor {device_id}: C must be > 0 F")
        self.C       = float(c_f)
        self.net_pos = net_pos
        self.net_neg = net_neg
        self._vc: float = 0.0   # voltage at last converged step
        self._ic: float = 0.0   # current at last converged step

    def nets(self):
        return [n for n in (self.net_pos, self.net_neg) if n]

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        if dt_ms is None or dt_ms <= 0:
            return   # no contribution in DC solve
        Geq = 2.0 * self.C / (dt_ms * 1e-3)
        Ieq = Geq * self._vc + self._ic
        na  = self._n(self.net_pos, node_map)
        nb  = self._n(self.net_neg, node_map)
        _stamp_g(A, na, nb, Geq)
        _stamp_i(b, na,  Ieq)
        _stamp_i(b, nb, -Ieq)

    def update_state(self, V, node_map, dt_ms):
        vp = self._v(self.net_pos, V, node_map)
        vn = self._v(self.net_neg, V, node_map)
        vc_new = vp - vn
        if dt_ms and dt_ms > 0:
            Geq = 2.0 * self.C / (dt_ms * 1e-3)
            ic_new = Geq * (vc_new - self._vc) - self._ic
        else:
            ic_new = 0.0
        self._vc = vc_new
        self._ic = ic_new


class Inductor(Device):
    """
    Inductor with trapezoidal companion model.
    Geq = dt/(2L),  Ieq = IL_prev + Geq*(Va-Vb)_prev
    """

    def __init__(self, device_id: str, l_h: float,
                 net_a: str = "", net_b: str = "",
                 dcr_ohm: float = 0.0):
        super().__init__(device_id)
        if l_h <= 0:
            raise ValueError(f"Inductor {device_id}: L must be > 0 H")
        self.L     = float(l_h)
        self.DCR   = float(dcr_ohm)
        self.net_a = net_a
        self.net_b = net_b
        self._il: float   = 0.0   # current through inductor (a→b)
        self._vab: float  = 0.0   # voltage across (last step)

    def nets(self):
        return [n for n in (self.net_a, self.net_b) if n]

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        na = self._n(self.net_a, node_map)
        nb = self._n(self.net_b, node_map)
        if self.DCR > 0:
            _stamp_g(A, na, nb, 1.0 / self.DCR)
        if dt_ms and dt_ms > 0:
            Geq = (dt_ms * 1e-3) / (2.0 * self.L)
            Ieq = self._il + Geq * self._vab
            _stamp_g(A, na, nb, Geq)
            _stamp_i(b, na, -Ieq)
            _stamp_i(b, nb,  Ieq)

    def update_state(self, V, node_map, dt_ms):
        va  = self._v(self.net_a, V, node_map)
        vb  = self._v(self.net_b, V, node_map)
        vab = va - vb
        if dt_ms and dt_ms > 0:
            Geq = (dt_ms * 1e-3) / (2.0 * self.L)
            self._il  = self._il + Geq * (vab + self._vab)
        self._vab = vab


class VSource(Device):
    """
    Ideal independent voltage source (branch in MNA).
    V(net_pos) - V(net_neg) = voltage
    The branch current is solved as an unknown.
    """

    def __init__(self, device_id: str, voltage: float,
                 net_pos: str = "", net_neg: str = ""):
        super().__init__(device_id)
        self.voltage = float(voltage)
        self.net_pos = net_pos
        self.net_neg = net_neg

    def nets(self):
        return [n for n in (self.net_pos, self.net_neg) if n]

    def branches(self):
        return ["v"]

    def set_voltage(self, v: float):
        self.voltage = float(v)

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        k = self._bk("v", branch_map, n_nodes)
        if k is None:
            return
        _stamp_v(A, b,
                 self._n(self.net_pos, node_map),
                 self._n(self.net_neg, node_map),
                 k, self.voltage)


class ISource(Device):
    """Ideal independent current source (Norton; current flows pos→neg internally)."""

    def __init__(self, device_id: str, current: float,
                 net_pos: str = "", net_neg: str = ""):
        super().__init__(device_id)
        self.current = float(current)
        self.net_pos = net_pos
        self.net_neg = net_neg

    def nets(self):
        return [n for n in (self.net_pos, self.net_neg) if n]

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        _stamp_i(b, self._n(self.net_pos, node_map),  self.current)
        _stamp_i(b, self._n(self.net_neg, node_map), -self.current)
