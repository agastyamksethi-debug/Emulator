"""
MNA (Modified Nodal Analysis) solver.

Implements the same core algorithm used in SPICE:
  - Build  [G B; C D] * [v; j] = [i; e]  each Newton-Raphson iteration
  - Solve  with numpy.linalg.solve (dense; fast for N ≤ 200)
  - Iterate Newton-Raphson until VNTOL / ABSTOL / RELTOL convergence
  - Apply SPICE junction voltage limiting to guarantee convergence

Public API:
  solver = MNASolver()
  solver.load(devices, gnd_nets={"GND","0"})
  voltages = solver.solve_dc()         # dict[net→V]
  voltages = solver.step_tran(dt_ms)   # dict[net→V], updates companion history
"""
from __future__ import annotations
import numpy as np
from typing import TYPE_CHECKING

from .devices.base import Device
from .devices.linear import Capacitor, Inductor

try:
    from scipy.sparse import csc_matrix
    from scipy.sparse.linalg import spsolve as _spsolve
    _HAS_SCIPY = True
except ImportError:                           # pragma: no cover
    _HAS_SCIPY = False

_SPARSE_THRESHOLD = 50   # nodes+branches: use sparse above this

# ── SPICE convergence parameters (SPICE3 defaults) ───────────────────────────
VNTOL   = 1e-6     # node voltage absolute tolerance  (V)
ABSTOL  = 1e-12    # branch current absolute tolerance (A)
RELTOL  = 1e-3     # relative tolerance (0.1%)
ITL1    = 150      # max DC NR iterations
ITL4    = 40       # max transient NR iterations per timestep
GMIN    = 1e-12    # minimum shunt conductance (prevents floating-node singularity)

_GND_DEFAULT = frozenset({"GND", "AGND", "DGND", "PGND", "VSS", "0"})


class MNASolver:
    """
    Newton-Raphson MNA solver for arbitrary analog circuits.

    Device objects stamp themselves into the matrix via device.stamp().
    The solver owns the node/branch numbering; devices never allocate indices.
    """

    def __init__(self):
        self._devices:    list[Device]        = []
        self._node_map:   dict[str, int]      = {}
        self._branch_map: dict[str, int]      = {}
        self._n: int = 0
        self._m: int = 0
        self._V: np.ndarray | None = None

        # adaptive stepping state
        self._has_reactive: bool = False   # any C or L in circuit
        self._stable:       bool = False   # solution not changing
        self._stable_count: int  = 0       # consecutive stable steps

    # ── setup ──────────────────────────────────────────────────────────────────

    def load(self, devices: list[Device], gnd_nets: set[str] | None = None):
        """
        Register devices and build node / branch index maps.

        Must be called once before any solve.  Call again if the device list
        changes (e.g. a switch opens/closes creating a new topology).
        """
        self._devices = list(devices)
        gnd = gnd_nets if gnd_nets is not None else _GND_DEFAULT

        # collect unique non-ground nets and voltage-source branches
        nets: set[str] = set()
        branches: list[tuple[str, str]] = []  # (device_id, branch_label)

        for dev in self._devices:
            for net in dev.nets():
                if net and net.strip() not in gnd and net.strip():
                    nets.add(net.strip())
            for br in dev.branches():
                branches.append((dev.device_id, br))

        # deterministic ordering
        self._node_map   = {net: i for i, net in enumerate(sorted(nets))}
        self._branch_map = {
            f"{did}:{br}": j for j, (did, br) in enumerate(branches)
        }
        self._n = len(self._node_map)
        self._m = len(branches)

        self._V = np.zeros(self._n + self._m)
        self._has_reactive = any(isinstance(d, (Capacitor, Inductor))
                                 for d in self._devices)
        self._stable = False
        self._stable_count = 0

    def reset(self):
        """Clear solution history (use before a new simulation run)."""
        if self._V is not None:
            self._V = np.zeros_like(self._V)

    # ── public solve API ───────────────────────────────────────────────────────

    def solve_dc(self) -> dict[str, float]:
        """
        Compute DC operating point.
        Companion models (C, L) are inactive (dt_ms=None).
        """
        self._V = self._nr_solve(max_iter=ITL1, dt_ms=None)
        return self.node_voltages()

    def step_tran(self, dt_ms: float) -> dict[str, float]:
        """Advance one transient timestep, update companion history."""
        self._V = self._nr_solve(max_iter=ITL4, dt_ms=dt_ms)
        V_nodes = self._V[:self._n]
        for dev in self._devices:
            dev.update_state(V_nodes, self._node_map, dt_ms)
        return self.node_voltages()

    def solve_interval(self, duration_ms: float,
                       gpio_changed: bool = False,
                       dt_max_ms: float = 1.0,
                       dt_min_ms: float = 0.05) -> dict[str, float]:
        """
        Advance circuit by duration_ms with adaptive accuracy.

        Rules:
          • No reactive devices (no C/L): one DC solve on GPIO change, then
            skip all further solves until something changes again.
          • Reactive devices present: step with dt up to dt_max_ms, shrink when
            solution changes fast, grow when stable.  Stop early once the
            solution has settled (saves all the steps inside a long delay()).
          • gpio_changed=True forces at least one solve and resets stability.
        """
        if gpio_changed:
            self._stable = False
            self._stable_count = 0

        # ── pure-resistive circuit ────────────────────────────────────────────
        if not self._has_reactive:
            if self._stable and not gpio_changed:
                return self.node_voltages()   # already solved, nothing changed
            self._V = self._nr_solve(ITL1, None)
            self._stable = True
            return self.node_voltages()

        # ── reactive circuit: adaptive transient stepping ─────────────────────
        if self._stable and not gpio_changed:
            return self.node_voltages()       # settled — skip entire interval

        remaining = duration_ms
        dt = dt_max_ms

        while remaining > 1e-6:
            dt = min(dt, remaining)
            V_before = self._V.copy()

            self._V = self._nr_solve(ITL4, dt)
            V_nodes = self._V[:self._n]
            for dev in self._devices:
                dev.update_state(V_nodes, self._node_map, dt)

            remaining -= dt

            # measure how much the node voltages changed this step
            max_dv = float(np.max(np.abs(self._V[:self._n] - V_before[:self._n])))

            if max_dv < VNTOL * 1000:        # ~1mV — essentially settled
                self._stable_count += 1
                if self._stable_count >= 3:
                    self._stable = True
                    break                     # skip remaining duration
                dt = min(dt * 2.0, dt_max_ms)
            elif max_dv > 0.05:              # >50mV change — shrink step
                self._stable_count = 0
                self._stable = False
                dt = max(dt * 0.5, dt_min_ms)
            else:
                self._stable_count = 0

        return self.node_voltages()

    def node_voltages(self) -> dict[str, float]:
        """Return {net_name: voltage} from the last solve."""
        if self._V is None or self._n == 0:
            return {}
        return {net: float(self._V[idx])
                for net, idx in self._node_map.items()}

    def branch_current(self, device_id: str, branch: str = "v") -> float:
        """Return the current through a voltage source branch (A)."""
        if self._V is None:
            return 0.0
        k = self._branch_map.get(f"{device_id}:{branch}")
        if k is None:
            return 0.0
        return float(self._V[self._n + k])

    # ── Newton-Raphson core ────────────────────────────────────────────────────

    def _nr_solve(self, max_iter: int, dt_ms: float | None) -> np.ndarray:
        """
        Newton-Raphson iteration.

        1. Stamp all devices (linear + nonlinear companion) into A, b
        2. Solve A*x = b
        3. Apply SPICE junction voltage limiting (prevents exp() overflow)
        4. Check VNTOL / ABSTOL / RELTOL convergence
        5. Repeat until converged or max_iter reached
        """
        size = self._n + self._m
        if size == 0:
            return np.zeros(0)

        # warm start from last converged solution
        V = self._V.copy() if self._V is not None else np.zeros(size)

        prev_V = None
        for iteration in range(max_iter):
            A = np.zeros((size, size))
            b = np.zeros(size)

            # Gmin shunt: tiny conductance from every node to ground.
            # Prevents singular matrix from floating nodes (SPICE trick #1).
            for i in range(self._n):
                A[i, i] += GMIN

            # stamp all devices at current voltage estimate V
            for dev in self._devices:
                dev.stamp(A, b, V, self._node_map, self._branch_map,
                          self._n, dt_ms)

            # solve linear system — sparse for large circuits
            try:
                if _HAS_SCIPY and size >= _SPARSE_THRESHOLD:
                    V_new = _spsolve(csc_matrix(A), b)
                else:
                    V_new = np.linalg.solve(A, b)
            except Exception:
                # singular: stronger Gmin stepping (SPICE trick #2)
                for i in range(self._n):
                    A[i, i] += 1e-6
                try:
                    V_new = np.linalg.solve(A, b)
                except np.linalg.LinAlgError:
                    return V

            # junction voltage limiting: prevent large jumps on exponential devices
            any_limited = False
            for dev in self._devices:
                if dev.limit(V_new, V, self._node_map, self._n):
                    any_limited = True

            # convergence check (skip on first two iterations — need baseline)
            if prev_V is not None and not any_limited:
                dV = np.abs(V_new[:self._n] - V[:self._n])
                dJ = np.abs(V_new[self._n:] - V[self._n:])
                v_ok = np.all(dV < VNTOL + RELTOL * np.abs(V_new[:self._n]))
                i_ok = np.all(dJ < ABSTOL + RELTOL * np.abs(V_new[self._n:]))
                if v_ok and i_ok:
                    return V_new

            prev_V = V.copy()
            V = V_new

        # reached max iterations — return best estimate (same as SPICE behaviour)
        return V
