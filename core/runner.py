"""
SimRunner — the top-level simulation orchestrator.

Usage:
    runner = SimRunner()
    runner.load("path/to/board.kicad_sch")
    runner.tick(dt_ms=1.0)          # single step
    runner.run(duration_ms=1000)    # run for 1 second of simulated time

The runner owns the bus and physics engine and sequences them correctly:
  1. bus.tick_all()       — advance all IC nodes (execute firmware stubs)
  2. physics.tick()       — R/C/L transients, then heat spread
"""

from __future__ import annotations
from pathlib import Path
from typing import Callable

from core.bus import SimBus
from core.netlist import NetList, parse as parse_netlist
from core.node import Node
from physics.engine import PhysicsEngine
import core.registry as registry


class SimRunner:
    def __init__(self, v_supply: float = 3.3, ambient_c: float = 25.0,
                 dt_ms: float = 1.0):
        self.bus = SimBus(v_supply=v_supply)
        self.physics = PhysicsEngine(ambient_c=ambient_c)
        self.dt_ms = dt_ms              # default timestep
        self.elapsed_ms: float = 0.0   # total simulated time
        self._netlist: NetList | None = None
        self._on_tick: list[Callable[[float], None]] = []

    # ----------------------------------------------------------------- load ---

    def load(self, schematic_path: str | Path):
        """
        Parse a KiCad schematic and fully wire the simulation:
          1. Parse netlist
          2. Load bus routing (nets, CS maps, power rails)
          3. Auto-instantiate IC nodes for registered parts
          4. Load physics engine (passives + thermal)
        """
        self._netlist = parse_netlist(schematic_path)
        self.bus.load_netlist(self._netlist)
        self._auto_instantiate()
        nodes = list(self.bus._nodes.values())
        self.physics.load(nodes, self._netlist)

    def _auto_instantiate(self):
        """
        For every IC component in the netlist, instantiate its Node subclass
        (if registered) and add it to the bus.
        """
        if not self._netlist:
            return
        for ref, comp in self._netlist.components.items():
            lib_id = comp.get("part", "")
            node_class = registry.resolve(ref, lib_id)
            if node_class is None:
                continue    # passive or unregistered part
            node = node_class(instance_id=ref, descriptor=comp)
            self.bus.register(node)

    # -------------------------------------------------------------- manual ---

    def add_node(self, node: Node):
        """Manually add a node (e.g. for a part not yet in the registry)."""
        self.bus.register(node)
        nodes = list(self.bus._nodes.values())
        if self._netlist:
            self.physics.load(nodes, self._netlist)

    # ----------------------------------------------------------------- tick ---

    def tick(self, dt_ms: float | None = None):
        """Advance the simulation by one timestep."""
        dt = dt_ms if dt_ms is not None else self.dt_ms
        self.bus.tick_all(dt)
        self.physics.tick(dt, self.bus.gpio)
        self.elapsed_ms += dt
        for cb in self._on_tick:
            cb(self.elapsed_ms)

    def run(self, duration_ms: float, dt_ms: float | None = None):
        """Run the simulation for duration_ms of simulated time."""
        dt = dt_ms if dt_ms is not None else self.dt_ms
        steps = max(1, int(duration_ms / dt))
        for _ in range(steps):
            self.tick(dt)

    # -------------------------------------------------------------- hooks ----

    def on_tick(self, callback: Callable[[float], None]):
        """Register a callback invoked after every tick with elapsed_ms."""
        self._on_tick.append(callback)

    # --------------------------------------------------------------- state ---

    def net_voltage(self, net_name: str) -> float:
        return self.bus.read_voltage(net_name)

    def inject_voltage(self, net_name: str, voltage: float):
        """Force a net to a voltage — useful for injecting test signals."""
        self.bus.drive(net_name, "_inject", voltage)

    def inject_digital(self, net_name: str, high: bool):
        self.bus.drive_digital(net_name, "_inject", high)

    def node(self, reference: str) -> Node | None:
        return self.bus._nodes.get(reference)

    def reset(self):
        """Reset all nodes and clear elapsed time."""
        self.elapsed_ms = 0.0
        for node in self.bus._nodes.values():
            node.reset()

    def __repr__(self):
        return (f"<SimRunner  t={self.elapsed_ms:.1f}ms  "
                f"nodes={len(self.bus._nodes)}  "
                f"nets={len(self.bus.gpio._nets)}>")
