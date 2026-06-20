"""
Real-World Bus — physical-domain signal routing.

Manages non-electrical couplings between components:
  light   : luminous intensity (0.0 → 1.0, where 1.0 = full brightness)
  heat    : thermal power (watts, relative)
  sound   : acoustic pressure (0.0 → 1.0)
  ir      : infrared intensity (0.0 → 1.0)
  force   : mechanical force (0.0 → 1.0)

Usage:
    bus = RWBus()
    bus.set("D1:light", 0.85)           # LED emits 85% light
    bus.connect("D1:light", "R1:light") # wire LED → LDR
    lux = bus.get("R1:light")           # LDR reads 0.85
"""

from __future__ import annotations
from dataclasses import dataclass, field


RW_TYPES = {"light", "heat", "sound", "ir", "force"}


@dataclass
class RWConnection:
    src:  str           # port id  e.g. "D1:light"
    dst:  str           # port id  e.g. "R1:light"
    loss: float = 1.0   # output multiplier: 1.0 = lossless, 0.0 = total loss


class RWBus:
    def __init__(self):
        self._values:      dict[str, float]        = {}
        self._connections: list[RWConnection]      = []
        self._listeners:   dict[str, list]         = {}  # dst → [callable]

    # ── write / read ──────────────────────────────────────────────────────────

    def set(self, port_id: str, value: float):
        """Component writes its output value (call once per sim tick)."""
        self._values[port_id] = max(0.0, float(value))

    def get(self, port_id: str) -> float:
        """Return the most recently propagated value for this port (call after tick)."""
        return min(1.0, self._values.get(port_id, 0.0))

    # ── wiring ────────────────────────────────────────────────────────────────

    def connect(self, src: str, dst: str, loss: float = 1.0):
        """Create a connection from output port → input port with optional attenuation."""
        if not any(c.src == src and c.dst == dst for c in self._connections):
            self._connections.append(
                RWConnection(src=src, dst=dst, loss=max(0.0, min(1.0, loss)))
            )

    def disconnect(self, src: str, dst: str):
        self._connections = [
            c for c in self._connections
            if not (c.src == src and c.dst == dst)
        ]

    def disconnect_all(self, port_id: str):
        """Remove every connection touching this port."""
        self._connections = [
            c for c in self._connections
            if c.src != port_id and c.dst != port_id
        ]

    def connections(self) -> list[RWConnection]:
        return list(self._connections)

    # ── propagate ─────────────────────────────────────────────────────────────

    def tick(self, max_hops: int = 8):
        """
        Propagate values through the connection graph with loss applied.

        Uses Jacobi relaxation so multi-hop chains (e.g. LED → LossNode → LDR)
        converge in N+1 waves for a chain of depth N.  After propagation fires
        registered on_update callbacks.
        """
        for _ in range(max_hops):
            updates: dict[str, float] = {}
            for conn in self._connections:
                v = self._values.get(conn.src, 0.0) * conn.loss
                updates[conn.dst] = updates.get(conn.dst, 0.0) + v
            changed = False
            for k, v in updates.items():
                if abs(self._values.get(k, 0.0) - v) > 1e-9:
                    self._values[k] = v
                    changed = True
            if not changed:
                break
        for conn in self._connections:
            for cb in self._listeners.get(conn.dst, []):
                cb(self._values.get(conn.dst, 0.0))

    def on_update(self, dst_port_id: str, callback):
        """Register a callback invoked on tick whenever dst port receives a value."""
        self._listeners.setdefault(dst_port_id, []).append(callback)

    # ── helpers ───────────────────────────────────────────────────────────────

    def clear(self):
        self._values.clear()
        self._connections.clear()
        self._listeners.clear()

    def __repr__(self):
        return (f"<RWBus  ports={len(self._values)}"
                f"  connections={len(self._connections)}>")
