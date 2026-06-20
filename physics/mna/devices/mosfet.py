"""
SPICE MOSFET Level 1 (Shichman-Hodges) model.
Ported from ngspice src/spicelib/devices/mos1/mos1load.c

Covers all three operating regions:
  - Cutoff:     Vgs < Vth   → Id = 0
  - Linear:     Vds < Vdsat → Id = beta*((Vgs-Vth)*Vds - Vds²/2)*(1+lambda*Vds)
  - Saturation: Vds ≥ Vdsat → Id = beta/2*(Vgs-Vth)²*(1+lambda*Vds)

Body effect on threshold:  Vth = VTO + GAMMA*(sqrt(|2PHI - Vbs|) - sqrt(2PHI))

NR stamp:
  Id = Gm*(Vgs-Vgs0) + Gds*(Vds-Vds0) + Gmbs*(Vbs-Vbs0) + Id0
  → 4-terminal linearized conductance matrix

Gate is ideal (no gate current for Level 1).
Drain/source/body capacitances (CBD, CBS) use diode junction model.

SPICE .model parameters (NMOS/PMOS):
  VTO    = 1.0 V      threshold voltage at Vbs=0 (NMOS positive, PMOS negative)
  KP     = 2e-5 A/V²  transconductance parameter (µ0*Cox)
  GAMMA  = 0.0        body-effect coefficient √V
  PHI    = 0.6 V      surface potential at strong inversion
  LAMBDA = 0.0        channel-length modulation 1/V
  RD     = 0.0 Ω      drain ohmic resistance
  RS     = 0.0 Ω      source ohmic resistance
  CBD    = 0.0 F      bulk-drain zero-bias cap
  CBS    = 0.0 F      bulk-source zero-bias cap
  IS     = 1e-14 A    bulk junction saturation current
  W      = 1e-4 m     channel width
  L      = 1e-4 m     channel length
  LD     = 0.0 m      lateral diffusion
  TOX    = 1e-7 m     oxide thickness (for Cox calculation if KP not given)
  NSUB   = 0.0        substrate doping (for PHI/GAMMA auto-calc)
"""
from __future__ import annotations
import numpy as np
from .base import Device, _stamp_g, _stamp_vccs, _stamp_i
from .kernels import mosfet_ids as _mosfet_ids

_EPS0   = 8.854e-12   # F/m  vacuum permittivity
_EPS_SI = 11.7        # silicon relative permittivity
_EPS_OX = 3.9         # SiO2 relative permittivity
_K      = 1.380649e-23
_Q      = 1.602176634e-19
_NI     = 1.45e16     # intrinsic carrier density /m³ at 300K


class MOSFET(Device):
    """
    SPICE Level 1 MOSFET (Shichman-Hodges).

    Polarity: "NMOS" (default) or "PMOS".
    For PMOS, all voltages are negated internally (p-channel equivalent circuit).
    """

    def __init__(self, device_id: str,
                 net_d: str, net_g: str, net_s: str, net_b: str = "",
                 polarity: str = "NMOS",
                 VTO:    float = 1.0,
                 KP:     float = 2e-5,
                 GAMMA:  float = 0.0,
                 PHI:    float = 0.6,
                 LAMBDA: float = 0.0,
                 RD:     float = 0.0,
                 RS:     float = 0.0,
                 CBD:    float = 0.0,
                 CBS:    float = 0.0,
                 W:      float = 1e-4,
                 L:      float = 1e-4,
                 LD:     float = 0.0):
        super().__init__(device_id)
        self.net_d = net_d
        self.net_g = net_g
        self.net_s = net_s
        self.net_b = net_b      # bulk; if "" treated as tied to source

        self.p = 1.0 if polarity.upper() == "NMOS" else -1.0

        self.VTO    = float(VTO)
        self.KP     = float(KP)
        self.GAMMA  = float(GAMMA)
        self.PHI    = float(PHI)
        self.LAMBDA = float(LAMBDA)
        self.RD     = float(RD)
        self.RS     = float(RS)
        self.CBD    = float(CBD)
        self.CBS    = float(CBS)

        Leff        = max(L - 2.0 * LD, 1e-9)
        self.beta   = KP * (W / Leff)   # process transconductance × W/L

        # capacitor companion state (drain-bulk, source-bulk)
        self._vc_db: float = 0.0;  self._ic_db: float = 0.0
        self._vc_sb: float = 0.0;  self._ic_sb: float = 0.0

        # NR history for voltage limiting
        self._vgs_prev: float = 0.0
        self._vds_prev: float = 0.0

    def nets(self):
        return [n for n in (self.net_d, self.net_g, self.net_s, self.net_b) if n]

    def _ids(self, vgs: float, vds: float, vbs: float):
        """Returns (Id, Gm, Gds, Gmbs). NMOS convention, Vds ≥ 0."""
        return _mosfet_ids(vgs, vds, vbs,
                           self.VTO, self.beta,
                           self.GAMMA, self.PHI, self.LAMBDA)

    def stamp(self, A, b, V, node_map, branch_map, n_nodes, dt_ms):
        p  = self.p
        nd = self._n(self.net_d, node_map)
        ng = self._n(self.net_g, node_map)
        ns = self._n(self.net_s, node_map)
        # bulk defaults to source if no net given
        nb = (self._n(self.net_b, node_map)
              if self.net_b else ns)

        vd = self._v(self.net_d, V, node_map)
        vg = self._v(self.net_g, V, node_map)
        vs = self._v(self.net_s, V, node_map)
        vb = (self._v(self.net_b, V, node_map) if self.net_b else vs)

        # PMOS: negate terminal voltages to reduce to NMOS equivalent
        vgs = p * (vg - vs)
        vds = p * (vd - vs)
        vbs = p * (vb - vs)

        # Drain/source swap for negative Vds (Level 1 model assumes Vds ≥ 0)
        swapped = False
        if vds < 0.0:
            nd, ns = ns, nd
            vd, vs = vs, vd
            vgs = p * (vg - vs)   # recompute with new source
            vds = p * (vd - vs)   # now > 0
            vbs = p * (vb - vs)
            swapped = True

        Id, Gm, Gds, Gmbs = self._ids(vgs, vds, vbs)

        # Norton current: Id_eq = Id - Gm*Vgs - Gds*Vds - Gmbs*Vbs
        Id_eq = Id - Gm * vgs - Gds * vds - Gmbs * vbs

        # ── MNA stamp: correct VCCS form ──────────────────────────────────────
        # Id = Gm*(Vg-Vs) + Gds*(Vd-Vs) + Gmbs*(Vb-Vs) flows FROM nd INTO ns.
        # Gm  is VCCS controlled by Vgs = Vg-Vs  → _stamp_vccs
        # Gds is passive D-S conductance           → _stamp_g
        # Gmbs is VCCS controlled by Vbs = Vb-Vs  → _stamp_vccs

        _stamp_vccs(A, nd, ns, ng, ns, Gm)        # Gm*(Vg-Vs): nd←, ns→
        _stamp_g(A, nd, ns, Gds)                   # Gds passive D-S
        if Gmbs != 0.0:
            _stamp_vccs(A, nd, ns, nb if self.net_b else ns, ns, Gmbs)

        # Norton current injection (polarity: Id flows nd→ns for NMOS)
        _stamp_i(b, nd, -p * Id_eq)
        _stamp_i(b, ns,  p * Id_eq)

        # Bulk-drain and bulk-source junction capacitances (trapezoidal)
        if dt_ms and dt_ms > 0:
            vdb = p * (vd - (vb if vb else vs))
            vsb = p * (vs - (vb if vb else vs))
            if self.CBD > 0:
                Gc_db = 2.0 * self.CBD / (dt_ms * 1e-3)
                Ic_db = Gc_db * self._vc_db + self._ic_db
                _stamp_g(A, nd, nb, Gc_db)
                _stamp_i(b, nd,  Ic_db)
                _stamp_i(b, nb, -Ic_db)
            if self.CBS > 0:
                Gc_sb = 2.0 * self.CBS / (dt_ms * 1e-3)
                Ic_sb = Gc_sb * self._vc_sb + self._ic_sb
                _stamp_g(A, ns, nb, Gc_sb)
                _stamp_i(b, ns,  Ic_sb)
                _stamp_i(b, nb, -Ic_sb)

    def limit(self, V_new, V_old, node_map, n_nodes):
        """
        MOSFET NR voltage limiting.
        Clamp Vgs and Vds changes to ≤2V per iteration to prevent divergence
        when the MOSFET switches regions.  Gate is ideal (no pnjlim needed),
        but large Vgs/Vds jumps during the first few NR steps cause exp overflow
        in the region-detection logic and runaway in _ids.
        """
        nd = node_map.get(self.net_d)
        ng = node_map.get(self.net_g)
        ns = node_map.get(self.net_s)

        p = self.p
        vg  = float(V_new[ng]) if ng is not None else 0.0
        vd  = float(V_new[nd]) if nd is not None else 0.0
        vs  = float(V_new[ns]) if ns is not None else 0.0
        vg0 = float(V_old[ng]) if ng is not None else 0.0
        vd0 = float(V_old[nd]) if nd is not None else 0.0
        vs0 = float(V_old[ns]) if ns is not None else 0.0

        vgs_new = p * (vg - vs);  vgs_old = p * (vg0 - vs0)
        vds_new = p * (vd - vs);  vds_old = p * (vd0 - vs0)

        _MAX_STEP = 2.0     # V per NR iteration
        limited = False

        if abs(vgs_new - vgs_old) > _MAX_STEP:
            limited = True
            vgs_lim = vgs_old + _MAX_STEP * np.sign(vgs_new - vgs_old)
            # adjust gate (drain held fixed)
            if ng is not None:
                V_new[ng] = (vs + p * vgs_lim)

        if abs(vds_new - vds_old) > _MAX_STEP:
            limited = True
            vds_lim = vds_old + _MAX_STEP * np.sign(vds_new - vds_old)
            if nd is not None:
                V_new[nd] = (vs + p * vds_lim)

        return limited

    def update_state(self, V, node_map, dt_ms):
        if dt_ms and dt_ms > 0:
            vd = self._v(self.net_d, V, node_map)
            vs = self._v(self.net_s, V, node_map)
            vb = (self._v(self.net_b, V, node_map) if self.net_b else vs)
            p  = self.p
            vdb = p * (vd - vb)
            vsb = p * (vs - vb)
            if self.CBD > 0:
                Gc = 2.0 * self.CBD / (dt_ms * 1e-3)
                self._ic_db = Gc * (vdb - self._vc_db) - self._ic_db
                self._vc_db = vdb
            if self.CBS > 0:
                Gc = 2.0 * self.CBS / (dt_ms * 1e-3)
                self._ic_sb = Gc * (vsb - self._vc_sb) - self._ic_sb
                self._vc_sb = vsb
