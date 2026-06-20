"""
Numba-compiled numerical kernels for hot MNA device evaluation paths.

Falls back to plain numpy if numba is unavailable (identical behaviour,
just slower). Each kernel is a pure function of scalar floats — no Python
objects, so numba can compile to native CPU code.

First call per session triggers JIT compilation (~0.3s).  Subsequent calls
run at C speed.  `cache=True` persists compiled objects across sessions.
"""
from __future__ import annotations
import numpy as np

try:
    from numba import njit as _njit
    _HAS_NUMBA = True
except ImportError:                          # pragma: no cover
    def _njit(*a, **kw):                     # type: ignore[misc]
        def _wrap(fn): return fn
        return _wrap
    _HAS_NUMBA = False


# ── Diode ─────────────────────────────────────────────────────────────────────

@_njit(cache=True, fastmath=True)
def diode_eval(vd: float, IS: float, N: float, Vt: float,
               BV: float, IBV: float) -> tuple[float, float]:
    """
    Shockley diode (Id, Gd=dId/dVd).
    Ported from ngspice diodeload.c.
    """
    NVt = N * Vt

    if vd < -(BV - 0.1 * NVt):
        # breakdown region
        evrev = np.exp(-(BV + vd) / NVt)
        return -IBV * evrev, IBV / NVt * evrev

    arg = vd / NVt
    if arg > 709.0:
        arg = 709.0

    if arg > -5.0:
        ev  = np.exp(arg)
        Id  = IS * (ev - 1.0)
        Gd  = IS * ev / NVt
    else:
        Id  = -IS
        Gd  = IS / NVt * np.exp(arg)

    return Id, Gd


@_njit(cache=True, fastmath=True)
def diode_cj(vd: float, CJ0: float, FC: float, VJ: float, M: float) -> float:
    """Junction capacitance Cj(Vd) with FC linearisation."""
    if CJ0 == 0.0:
        return 0.0
    if vd < FC * VJ:
        return CJ0 / ((1.0 - vd / VJ) ** M)
    F2 = (1.0 - FC) ** (1.0 + M)
    F3 = 1.0 - FC * (1.0 + M)
    return CJ0 / F2 * (F3 + M * vd / VJ)


# ── BJT ───────────────────────────────────────────────────────────────────────

@_njit(cache=True, fastmath=True)
def bjt_gummel_poon(vbe: float, vbc: float,
                    IS: float, BF: float, NF: float, VAF: float, IKF: float,
                    ISE: float, NE: float,
                    BR: float, NR: float, VAR: float, IKR: float,
                    ISC: float, NC: float,
                    Vt: float) -> tuple[float, float, float, float, float, float]:
    """
    Ebers-Moll + Gummel-Poon base charge.
    Returns (Ic, Ib, Gm, Go, Gpi, Gmu).
    Ported from ngspice bjtload.c.
    """
    NFVt  = NF * Vt
    NRVt  = NR * Vt
    NEVt  = NE * Vt
    NCVt  = NC * Vt

    arg_f = vbe / NFVt
    if arg_f > 709.0: arg_f = 709.0
    arg_r = vbc / NRVt
    if arg_r > 709.0: arg_r = 709.0

    expf = np.exp(arg_f)
    expr = np.exp(arg_r)
    If   = IS * (expf - 1.0)
    Ir   = IS * (expr - 1.0)
    Gdf  = IS * expf / NFVt
    Gdr  = IS * expr / NRVt

    # Gummel-Poon base charge
    q1   = 1.0 / max(1.0 - vbc / VAF - vbe / VAR, 1e-10)
    q2   = max(0.0, If / IKF + Ir / IKR)
    sq   = max(1.0 + 4.0 * q2, 0.0) ** 0.5
    Qb   = q1 / 2.0 * (1.0 + sq)

    dQb_dVbe = q1 * (q1 * Gdf / (IKF * max(sq, 1e-30))
                     - If / (VAR * Qb))
    dQb_dVbc = q1 * (q1 * Gdr / (IKR * max(sq, 1e-30))
                     - If / (VAF * Qb) - Ir / (VAR * Qb))

    # leakage
    arg_e = vbe / NEVt
    if arg_e > 709.0: arg_e = 709.0
    arg_c = vbc / NCVt
    if arg_c > 709.0: arg_c = 709.0
    Ibe_leak = ISE * (np.exp(arg_e) - 1.0)
    Ibc_leak = ISC * (np.exp(arg_c) - 1.0)
    Gbe_leak = ISE * np.exp(arg_e) / NEVt
    Gbc_leak = ISC * np.exp(arg_c) / NCVt

    It  = (If - Ir) / Qb
    Ic  = It - Ir / BR - Ibc_leak
    Ib  = If / BF + Ir / BR + Ibe_leak + Ibc_leak

    Gm  = Gdf / Qb - It * dQb_dVbe / Qb
    Go  = (-Gdr / Qb - Gdr / BR - Gbc_leak - It * dQb_dVbc / Qb)
    Gpi = Gdf / BF + Gbe_leak + dQb_dVbe * Ir / (Qb * BR)
    Gmu = Gdr / BR + Gbc_leak + dQb_dVbc * Ir / (Qb * BR)

    return Ic, Ib, Gm, Go, Gpi, Gmu


# ── MOSFET ────────────────────────────────────────────────────────────────────

@_njit(cache=True, fastmath=True)
def mosfet_ids(vgs: float, vds: float, vbs: float,
               VTO: float, beta: float,
               GAMMA: float, PHI: float, LAMBDA: float
               ) -> tuple[float, float, float, float]:
    """
    Shichman-Hodges Level 1 MOSFET. Returns (Id, Gm, Gds, Gmbs).
    Ported from ngspice mos1load.c.
    NMOS polarity assumed; caller handles PMOS sign flip.
    """
    body_arg = max(2.0 * PHI - vbs, 0.0)
    sqrt_body = body_arg ** 0.5
    Vth  = VTO + GAMMA * (sqrt_body - (2.0 * PHI) ** 0.5)
    Vdsat = max(vgs - Vth, 0.0)

    if vgs - Vth <= 0.0:
        return 0.0, 0.0, 0.0, 0.0

    lam_vds = 1.0 + LAMBDA * vds

    if vds < Vdsat:
        # linear region
        Id   = beta * ((vgs - Vth) * vds - 0.5 * vds * vds) * lam_vds
        Gm   = beta * vds * lam_vds
        Gds  = (beta * ((vgs - Vth) - vds) * lam_vds
                + beta * ((vgs - Vth) * vds - 0.5 * vds * vds) * LAMBDA)
        if GAMMA != 0.0 and body_arg > 0.0:
            Gmbs = -Gm * GAMMA / (2.0 * sqrt_body)
        else:
            Gmbs = 0.0
    else:
        # saturation
        Id   = 0.5 * beta * Vdsat * Vdsat * lam_vds
        Gm   = beta * Vdsat * lam_vds
        Gds  = 0.5 * beta * Vdsat * Vdsat * LAMBDA
        if GAMMA != 0.0 and body_arg > 0.0:
            Gmbs = -Gm * GAMMA / (2.0 * sqrt_body)
        else:
            Gmbs = 0.0

    return Id, Gm, Gds, Gmbs
