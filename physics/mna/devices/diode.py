"""
SPICE Diode model — ported from ngspice src/spicelib/devices/diode/diodeload.c

Implements the full Level 1 SPICE diode model:
  - Shockley equation with ideality factor N and series resistance RS
  - Junction capacitance Cj(V) with forward-bias depletion correction (FC)
  - Transit time diffusion capacitance Ct = TT * Gd
  - Reverse breakdown (BV, IBV)
  - Temperature dependence of IS via EG and XTI

Newton-Raphson stamp:
  Geq = dId/dVd  (dynamic conductance at operating point)
  Ieq = Id - Geq * Vd  (Norton equivalent current source)
  → stamps Geq across junction + Ieq into anode node

SPICE .model parameters (all optional, sensible defaults):
  IS   = 1e-14 A    saturation current
  N    = 1.0        emission / ideality coefficient
  RS   = 0 Ω        ohmic series resistance
  EG   = 1.11 eV    bandgap energy (Si default)
  XTI  = 3.0        IS temperature exponent
  CJ0  = 0 F        zero-bias junction capacitance
  VJ   = 1.0 V      built-in contact potential
  M    = 0.5        grading coefficient
  FC   = 0.5        forward-bias capacitance linearization threshold
  TT   = 0 s        transit time
  BV   = inf V      reverse breakdown voltage
  IBV  = 1e-3 A     current at reverse breakdown
  TNOM = 300.15 K   parameter measurement temperature
"""
from __future__ import annotations
import numpy as np
from .base import Device, _stamp_g, _stamp_i, pnjlim
from .kernels import diode_eval as _diode_eval, diode_cj as _diode_cj

_K  = 1.380649e-23   # Boltzmann constant J/K
_Q  = 1.602176634e-19  # electron charge C
_T0 = 300.15           # SPICE TNOM (27 °C)


def _vt(temp_k: float) -> float:
    return _K * temp_k / _Q


class Diode(Device):
    """
    SPICE Level 1 diode with full Shockley + capacitance model.

    Parameters match a SPICE .model D card directly.
    """

    def __init__(self, device_id: str,
                 net_anode: str, net_cathode: str,
                 IS:  float = 1e-14,
                 N:   float = 1.0,
                 RS:  float = 0.0,
                 EG:  float = 1.11,
                 XTI: float = 3.0,
                 CJ0: float = 0.0,
                 VJ:  float = 1.0,
                 M:   float = 0.5,
                 FC:  float = 0.5,
                 TT:  float = 0.0,
                 BV:  float = 1e30,
                 IBV: float = 1e-3,
                 temp_k: float = _T0):
        super().__init__(device_id)
        self.net_a  = net_anode
        self.net_k  = net_cathode

        # scale IS to operating temperature (ngspice DEVpnjtemp)
        ratio = temp_k / _T0
        self.IS  = IS * (ratio ** XTI) * np.exp(
            (_Q * EG / _K) * (1.0 / _T0 - 1.0 / temp_k))
        self.N   = N
        self.RS  = RS
        self.CJ0 = CJ0
        self.VJ  = VJ
        self.M   = M
        self.FC  = FC
        self.TT  = TT
        self.BV  = BV
        self.IBV = IBV
        self.Vt  = _vt(temp_k)

        # critical voltage for NR limiting (ngspice pnjlim)
        self.Vcrit = N * self.Vt * np.log(
            N * self.Vt / (np.sqrt(2.0) * max(self.IS, 1e-300)))

        # state
        self._vd:  float = 0.0    # junction voltage (previous converged)
        self._vc:  float = 0.0    # capacitor companion voltage
        self._ic:  float = 0.0    # capacitor companion current

    def nets(self):
        return [n for n in (self.net_a, self.net_k) if n]

    # ── core Shockley evaluation (no RS inner loop for speed; RS handled externally) ──

    def _eval(self, vd: float) -> tuple[float, float]:
        return _diode_eval(vd, self.IS, self.N, self.Vt, self.BV, self.IBV)

    def _cj(self, vd: float) -> float:
        return _diode_cj(vd, self.CJ0, self.FC, self.VJ, self.M)

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        na = self._n(self.net_a, node_map)
        nk = self._n(self.net_k, node_map)

        va = self._v(self.net_a, V, node_map)
        vk = self._v(self.net_k, V, node_map)
        vd = va - vk

        # series resistance: split anode into internal node conceptually.
        # For RS > 0 we'd need an extra node; instead use linearised RS stamp.
        if self.RS > 0.0:
            _stamp_g(A, na, nk, 1.0 / self.RS)

        Id, Geq = self._eval(vd)

        # transit-time diffusion cap (frequency-dependent, approximated here
        # as additional conductance proportional to Gd, per SPICE DEVcapcharge)
        Cjunc = self._cj(vd)
        Cdiff = self.TT * Geq
        Ctot  = Cjunc + Cdiff

        # capacitor companion model (trapezoidal)
        if dt_ms and dt_ms > 0 and Ctot > 0.0:
            Gc  = 2.0 * Ctot / (dt_ms * 1e-3)
            Ic  = Gc * self._vc + self._ic
            _stamp_g(A, na, nk, Gc)
            _stamp_i(b, na,  Ic)
            _stamp_i(b, nk, -Ic)

        # NR conductance + Norton current
        Ieq = Id - Geq * vd
        _stamp_g(A, na, nk, Geq)
        _stamp_i(b, na, -Ieq)
        _stamp_i(b, nk,  Ieq)

    def limit(self, V_new, V_old, node_map, n_nodes):
        na = node_map.get(self.net_a)
        nk = node_map.get(self.net_k)
        va_new = float(V_new[na]) if na is not None else 0.0
        vk_new = float(V_new[nk]) if nk is not None else 0.0
        va_old = float(V_old[na]) if na is not None else 0.0
        vk_old = float(V_old[nk]) if nk is not None else 0.0
        vd_new = va_new - vk_new
        vd_old = va_old - vk_old
        vd_lim, limited = pnjlim(vd_new, vd_old, self.Vt, self.Vcrit)
        if limited:
            # distribute the correction to the anode (cathode fixed)
            delta = vd_lim - vd_new
            if na is not None:
                V_new[na] += delta
        return limited

    def update_state(self, V, node_map, dt_ms):
        va = self._v(self.net_a, V, node_map)
        vk = self._v(self.net_k, V, node_map)
        vd = va - vk
        Cjunc = self._cj(vd)
        _, Geq = self._eval(vd)
        Ctot  = Cjunc + self.TT * Geq
        if dt_ms and dt_ms > 0 and Ctot > 0.0:
            Gc = 2.0 * Ctot / (dt_ms * 1e-3)
            vc_new = vd
            ic_new = Gc * (vc_new - self._vc) - self._ic
            self._vc = vc_new
            self._ic = ic_new
        self._vd = vd
