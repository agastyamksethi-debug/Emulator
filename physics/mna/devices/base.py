"""
Device base class and low-level MNA stamp helpers.

Every device reduces to three primitive operations:
  _stamp_g  — conductance between two nodes
  _stamp_i  — current injection into a node
  _stamp_v  — ideal voltage source branch

These mirror the stamp rules in ngspice's DEVload() functions exactly.
GND is represented as None — its row/column is implicitly excluded.
"""
from __future__ import annotations
import numpy as np


# ── primitive stamp operations ────────────────────────────────────────────────

def _stamp_g(A: np.ndarray, na: int | None, nb: int | None, g: float):
    """Stamp conductance g between nodes na and nb (None = GND)."""
    if na is not None:
        A[na, na] += g
        if nb is not None:
            A[na, nb] -= g
    if nb is not None:
        A[nb, nb] += g
        if na is not None:
            A[nb, na] -= g


def _stamp_vccs(A: np.ndarray,
                n_out_p: int | None, n_out_n: int | None,
                n_ctrl_p: int | None, n_ctrl_n: int | None,
                gm: float):
    """
    Stamp a voltage-controlled current source gm*(V_ctrl_p - V_ctrl_n)
    flowing from n_out_n to n_out_p (INTO n_out_p).
    Asymmetric: does NOT touch the controlling nodes' rows.
    """
    if n_out_p is not None:
        if n_ctrl_p is not None: A[n_out_p, n_ctrl_p] += gm
        if n_ctrl_n is not None: A[n_out_p, n_ctrl_n] -= gm
    if n_out_n is not None:
        if n_ctrl_p is not None: A[n_out_n, n_ctrl_p] -= gm
        if n_ctrl_n is not None: A[n_out_n, n_ctrl_n] += gm


def _stamp_i(b: np.ndarray, n: int | None, i: float):
    """Inject current i into node n (positive = current flowing INTO node)."""
    if n is not None:
        b[n] += i


def _stamp_v(A: np.ndarray, b: np.ndarray,
             n_pos: int | None, n_neg: int | None,
             k: int, v: float):
    """
    Stamp ideal voltage source V(n_pos) - V(n_neg) = v, branch index k.
    k is an absolute index into A (already offset by n_nodes).
    """
    if n_pos is not None:
        A[n_pos, k] += 1.0
        A[k, n_pos] += 1.0
    if n_neg is not None:
        A[n_neg, k] -= 1.0
        A[k, n_neg] -= 1.0
    b[k] += v


# ── SPICE junction voltage limiter ────────────────────────────────────────────
# Ported from ngspice/src/spicelib/analysis/cktpnjlim.c

def pnjlim(vnew: float, vold: float, vt: float, vcrit: float) -> tuple[float, bool]:
    """
    SPICE PN junction voltage limiter.
    Prevents NR from moving the junction voltage by more than a few Vt
    per iteration, keeping exp() from overflowing and ensuring convergence.

    Returns (limited_voltage, was_limited).
    """
    limited = False
    if vnew > vcrit and abs(vnew - vold) > 2.0 * vt:
        limited = True
        if vold > 0.0:
            arg = 1.0 + (vnew - vold) / vt
            if arg > 0.0:
                vnew = vold + vt * np.log(arg)
            else:
                vnew = vcrit
        else:
            vnew = vt * np.log(max(vnew / vt, 1e-300))
    elif vnew < -10.0 * abs(vold) - 10.0:
        limited = True
        vnew = -10.0 * abs(vold) - 10.0
    return vnew, limited


# ── Device base class ─────────────────────────────────────────────────────────

class Device:
    """
    Abstract base for MNA-stampable circuit elements.

    Three-phase protocol per timestep:
      1. stamp()         — called each NR iteration; stamps Geq/Ieq into A, b
      2. limit()         — SPICE-style voltage limiting after each NR solve
      3. update_state()  — save history after convergence (companion models)
    """

    def __init__(self, device_id: str):
        self.device_id = device_id

    def nets(self) -> list[str]:
        """All net names this device connects to (excluding GND / empty strings)."""
        return []

    def branches(self) -> list[str]:
        """Branch labels for voltage-source-like rows in the MNA matrix."""
        return []

    def stamp(self, A: np.ndarray, b: np.ndarray, V: np.ndarray,
              node_map: dict[str, int], branch_map: dict[str, int],
              n_nodes: int, dt_ms: float | None):
        """
        Stamp contributions into MNA matrices.
        V is the current estimate of [node_voltages, branch_currents].
        dt_ms is None during DC solve.
        """

    def limit(self, V_new: np.ndarray, V_old: np.ndarray,
              node_map: dict[str, int], n_nodes: int) -> bool:
        """
        Apply SPICE voltage limiting to V_new in-place.
        Returns True if any limiting was applied (NR must not declare convergence).
        """
        return False

    def update_state(self, V: np.ndarray, node_map: dict[str, int], dt_ms: float):
        """Save history variables after NR converges (for companion models)."""

    # convenience -----------------------------------------------------------

    def _n(self, net: str, node_map: dict[str, int]) -> int | None:
        return node_map.get(net)

    def _v(self, net: str, V: np.ndarray, node_map: dict[str, int]) -> float:
        idx = node_map.get(net)
        return float(V[idx]) if idx is not None else 0.0

    def _bk(self, branch: str, branch_map: dict[str, int], n_nodes: int) -> int | None:
        k = branch_map.get(f"{self.device_id}:{branch}")
        return n_nodes + k if k is not None else None
