"""
SPICE BJT model — Ebers-Moll transport form + Gummel-Poon extensions.
Ported from ngspice src/spicelib/devices/bjt/bjtload.c

Implements:
  - Ebers-Moll transport form (Level 1 baseline)
  - Gummel-Poon base charge Qb (Early effect + high-level injection)
  - Ohmic terminal resistances RB, RC, RE
  - Junction capacitances CJE, CJC (trapezoidal companion)
  - Transit time diffusion capacitances TF, TR

NPN/PNP polarity is handled by a polarity multiplier p = +1 (NPN) / -1 (PNP).

SPICE .model parameters (NPN/PNP card):
  IS   = 1e-16 A      transport saturation current
  BF   = 100          ideal max forward beta
  NF   = 1.0          forward emission coefficient
  VAF  = inf V        forward Early voltage
  IKF  = inf A        high-injection forward knee current
  ISE  = 0 A          B-E leakage saturation current
  NE   = 1.5          B-E leakage emission coefficient
  BR   = 1.0          ideal max reverse beta
  NR   = 1.0          reverse emission coefficient
  VAR  = inf V        reverse Early voltage
  IKR  = inf A        high-injection reverse knee current
  ISC  = 0 A          B-C leakage saturation current
  NC   = 2.0          B-C leakage emission coefficient
  RB   = 0 Ω          zero-bias base resistance
  RC   = 0 Ω          collector resistance
  RE   = 0 Ω          emitter resistance
  CJE  = 0 F          B-E zero-bias junction cap
  VJE  = 0.75 V       B-E built-in potential
  MJE  = 0.33         B-E grading coefficient
  CJC  = 0 F          B-C zero-bias junction cap
  VJC  = 0.75 V       B-C built-in potential
  MJC  = 0.33         B-C grading coefficient
  TF   = 0 s          ideal forward transit time
  TR   = 0 s          ideal reverse transit time
"""
from __future__ import annotations
import numpy as np
from .base import Device, _stamp_g, _stamp_vccs, _stamp_i, pnjlim
from .kernels import bjt_gummel_poon as _bjt_gp

_K  = 1.380649e-23
_Q  = 1.602176634e-19
_T0 = 300.15


def _vt(temp_k: float) -> float:
    return _K * temp_k / _Q


class BJT(Device):
    """
    SPICE BJT: Ebers-Moll + Gummel-Poon base charge model.

    Terminals:  C (collector), B (base), E (emitter), [S (substrate, optional)]
    polarity: "NPN" or "PNP"
    """

    def __init__(self, device_id: str,
                 net_c: str, net_b: str, net_e: str,
                 polarity: str = "NPN",
                 IS:  float = 1e-16,
                 BF:  float = 100.0,
                 NF:  float = 1.0,
                 VAF: float = 1e30,
                 IKF: float = 1e30,
                 ISE: float = 0.0,
                 NE:  float = 1.5,
                 BR:  float = 1.0,
                 NR:  float = 1.0,
                 VAR: float = 1e30,
                 IKR: float = 1e30,
                 ISC: float = 0.0,
                 NC:  float = 2.0,
                 RB:  float = 0.0,
                 RC:  float = 0.0,
                 RE:  float = 0.0,
                 CJE: float = 0.0,
                 VJE: float = 0.75,
                 MJE: float = 0.33,
                 CJC: float = 0.0,
                 VJC: float = 0.75,
                 MJC: float = 0.33,
                 TF:  float = 0.0,
                 TR:  float = 0.0,
                 temp_k: float = _T0):
        super().__init__(device_id)
        self.net_c  = net_c
        self.net_b  = net_b
        self.net_e  = net_e
        self.p      = 1.0 if polarity.upper() == "NPN" else -1.0

        self.IS  = IS
        self.BF  = BF;  self.NF  = NF;  self.VAF = VAF; self.IKF = IKF
        self.ISE = ISE; self.NE  = NE
        self.BR  = BR;  self.NR  = NR;  self.VAR = VAR; self.IKR = IKR
        self.ISC = ISC; self.NC  = NC
        self.RB  = RB;  self.RC  = RC;  self.RE  = RE
        self.CJE = CJE; self.VJE = VJE; self.MJE = MJE
        self.CJC = CJC; self.VJC = VJC; self.MJC = MJC
        self.TF  = TF;  self.TR  = TR
        self.Vt  = _vt(temp_k)

        self.Vcrit_be = NF * self.Vt * np.log(
            NF * self.Vt / (np.sqrt(2.0) * max(IS, 1e-300)))
        self.Vcrit_bc = NR * self.Vt * np.log(
            NR * self.Vt / (np.sqrt(2.0) * max(IS, 1e-300)))

        # companion state (junction caps)
        self._vbe: float = 0.0
        self._vbc: float = 0.0
        self._ic_be: float = 0.0;  self._vc_be: float = 0.0
        self._ic_bc: float = 0.0;  self._vc_bc: float = 0.0

    def nets(self):
        return [n for n in (self.net_c, self.net_b, self.net_e) if n]

    def _cj(self, v: float, CJ0: float, VJ: float, M: float) -> float:
        """Junction capacitance (same formula as diode)."""
        if CJ0 == 0.0:
            return 0.0
        FC = 0.5
        if v < FC * VJ:
            return CJ0 / ((1.0 - v / VJ) ** M)
        F2 = (1.0 - FC) ** (1.0 + M)
        F3 = 1.0 - FC * (1.0 + M)
        return CJ0 / F2 * (F3 + M * v / VJ)

    def _gummel_poon(self, vbe: float, vbc: float):
        """Ebers-Moll + Gummel-Poon. Returns (Ic, Ib, Gm, Go, Gpi, Gmu)."""
        p = self.p
        Ic, Ib, Gm, Go, Gpi, Gmu = _bjt_gp(
            p * vbe, p * vbc,
            self.IS, self.BF, self.NF, self.VAF, self.IKF,
            self.ISE, self.NE,
            self.BR, self.NR, self.VAR, self.IKR,
            self.ISC, self.NC,
            self.Vt,
        )
        return p * Ic, p * Ib, p * Gm, p * Go, p * Gpi, p * Gmu

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        nc = self._n(self.net_c, node_map)
        nb = self._n(self.net_b, node_map)
        ne = self._n(self.net_e, node_map)

        vc  = self._v(self.net_c, V, node_map)
        vb  = self._v(self.net_b, V, node_map)
        ve  = self._v(self.net_e, V, node_map)

        vbe = self.p * (vb - ve)
        vbc = self.p * (vb - vc)

        # terminal resistances
        if self.RB > 0:
            _stamp_g(A, nb, nb, 1.0 / self.RB)   # base resistance (simplified: no split)
        if self.RC > 0:
            _stamp_g(A, nc, nc, 1.0 / self.RC)
        if self.RE > 0:
            _stamp_g(A, ne, ne, 1.0 / self.RE)

        # junction capacitances (trapezoidal companion)
        if dt_ms and dt_ms > 0:
            Cje_t = self._cj(vbe, self.CJE, self.VJE, self.MJE)
            Cjc_t = self._cj(vbc, self.CJC, self.VJC, self.MJC)
            Ic_vals, _, Gm, _, _, _ = self._gummel_poon(vbe, vbc)
            Cdiff_f = self.TF * Gm
            Cdiff_r = self.TR * abs(Ic_vals) / max(abs(vbc), 1e-10)   # approx
            Cbe = Cje_t + Cdiff_f
            Cbc = Cjc_t + Cdiff_r

            if Cbe > 0:
                Gc_be = 2.0 * Cbe / (dt_ms * 1e-3)
                Ic_be = Gc_be * self._vc_be + self._ic_be
                _stamp_g(A, nb, ne, Gc_be)
                _stamp_i(b, nb,  Ic_be)
                _stamp_i(b, ne, -Ic_be)

            if Cbc > 0:
                Gc_bc = 2.0 * Cbc / (dt_ms * 1e-3)
                Ic_bc = Gc_bc * self._vc_bc + self._ic_bc
                _stamp_g(A, nb, nc, Gc_bc)
                _stamp_i(b, nb,  Ic_bc)
                _stamp_i(b, nc, -Ic_bc)

        Ic, Ib, Gm, Go, Gpi, Gmu = self._gummel_poon(vbe, vbc)

        # ── MNA stamp for Gummel-Poon BJT ─────────────────────────────────────
        # Linearised terminal currents (Gummel-Poon convention, polarity p handled
        # by the fact that vbe/vbc are already polarity-corrected above):
        #   Ic_lin = Gm*(Vb-Ve) + Go*(Vb-Vc)   [Go = dIc/dVbc, usually <0 for NPN]
        #   Ib_lin = Gpi*(Vb-Ve) + Gmu*(Vb-Vc)  [Gpi, Gmu > 0 since they are abs conductances]
        #
        # Gpi and Gmu are passive junction conductances → use _stamp_g (symmetric).
        # Gm is a VCCS (Gm*(Vb-Ve) flowing from ne to nc) → use _stamp_vccs.
        # Go is not a simple C-E resistor; it's dIc/dVbc.  We stamp it directly.
        #
        # KCL contributions (current FROM each node through BJT):
        #   nd (collector): (Gm+Go)*Vb - Gm*Ve - Go*Vc
        #   nb (base):      (Gpi+Gmu)*Vb - Gpi*Ve - Gmu*Vc
        #   ne (emitter):   -(Ic_lin + Ib_lin) = −total above

        # --- passive junction conductances (Gpi: B-E, Gmu: B-C) ---------------
        _stamp_g(A, nb, ne, Gpi)
        _stamp_g(A, nb, nc, Gmu)

        # --- Gm VCCS: Gm*(Vb-Ve) flows INTO nc from ne -------------------------
        _stamp_vccs(A, nc, ne, nb, ne, Gm)

        # --- Go contribution (dIc/dVbc): direct matrix entries -----------------
        # At nc: Go*Vb - Go*Vc  →  A[nc,nb] += Go, A[nc,nc] -= Go
        # At ne: -(Go*Vb - Go*Vc) by KCL → A[ne,nb] -= Go, A[ne,nc] += Go
        if nc is not None:
            if nb is not None: A[nc, nb] += Go
            A[nc, nc] -= Go
        if ne is not None:
            if nb is not None: A[ne, nb] -= Go
            if nc is not None: A[ne, nc] += Go

        # --- Norton current injections -----------------------------------------
        Ib_eq = Ib - Gpi * (self.p * vbe) - Gmu * (self.p * vbc)
        Ic_eq = Ic - Gm  * (self.p * vbe) - Go  * (self.p * vbc)

        _stamp_i(b, nb, -Ib_eq)
        _stamp_i(b, nc, -Ic_eq)
        _stamp_i(b, ne,  Ib_eq + Ic_eq)

    def limit(self, V_new, V_old, node_map, n_nodes):
        nc = node_map.get(self.net_c)
        nb = node_map.get(self.net_b)
        ne = node_map.get(self.net_e)

        p = self.p
        vbe_new = p * ((V_new[nb] if nb is not None else 0.0) -
                       (V_new[ne] if ne is not None else 0.0))
        vbc_new = p * ((V_new[nb] if nb is not None else 0.0) -
                       (V_new[nc] if nc is not None else 0.0))
        vbe_old = p * ((V_old[nb] if nb is not None else 0.0) -
                       (V_old[ne] if ne is not None else 0.0))
        vbc_old = p * ((V_old[nb] if nb is not None else 0.0) -
                       (V_old[nc] if nc is not None else 0.0))

        vbe_lim, lbe = pnjlim(vbe_new, vbe_old, self.Vt, self.Vcrit_be)
        vbc_lim, lbc = pnjlim(vbc_new, vbc_old, self.Vt, self.Vcrit_bc)

        limited = lbe or lbc
        if lbe and nb is not None:
            # adjust Vb so Vbe is limited (Ve fixed)
            ve = (V_new[ne] if ne is not None else 0.0)
            V_new[nb] = ve + p * vbe_lim
        if lbc and nc is not None:
            # adjust Vc so Vbc is limited (Vb already adjusted)
            vb = (V_new[nb] if nb is not None else 0.0)
            V_new[nc] = vb - p * vbc_lim
        return limited

    def update_state(self, V, node_map, dt_ms):
        vb  = self._v(self.net_b, V, node_map)
        vc  = self._v(self.net_c, V, node_map)
        ve  = self._v(self.net_e, V, node_map)
        vbe = self.p * (vb - ve)
        vbc = self.p * (vb - vc)
        _, _, Gm, _, Gpi, _ = self._gummel_poon(vbe, vbc)

        if dt_ms and dt_ms > 0:
            Cbe = self._cj(vbe, self.CJE, self.VJE, self.MJE) + self.TF * Gm
            Cbc = self._cj(vbc, self.CJC, self.VJC, self.MJC)
            if Cbe > 0:
                Gc = 2.0 * Cbe / (dt_ms * 1e-3)
                self._ic_be = Gc * (vbe - self._vc_be) - self._ic_be
                self._vc_be = vbe
            if Cbc > 0:
                Gc = 2.0 * Cbc / (dt_ms * 1e-3)
                self._ic_bc = Gc * (vbc - self._vc_bc) - self._ic_bc
                self._vc_bc = vbc

        self._vbe = vbe
        self._vbc = vbc
