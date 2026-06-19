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
import json
import os
from pathlib import Path
from typing import Callable

from core.bus import SimBus
from core.netlist import NetList, parse as parse_netlist
from core.node import Node
from core.recorder import WaveformRecorder
from physics.engine import PhysicsEngine
import core.registry as registry

_PARTS_DIR = os.path.join(os.path.dirname(__file__), "..", "parts")


def _load_part_descriptor(node_class: type) -> dict:
    """Read the static descriptor.json for a part via its PART_ID class attribute."""
    part_id = getattr(node_class, "PART_ID", None)
    if not part_id:
        return {}
    path = os.path.join(_PARTS_DIR, part_id, "descriptor.json")
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return json.load(f)


class SimRunner:
    def __init__(self, v_supply: float = 3.3, ambient_c: float = 25.0,
                 dt_ms: float = 1.0):
        self.bus      = SimBus(v_supply=v_supply)
        self.physics  = PhysicsEngine(ambient_c=ambient_c)
        self.recorder = WaveformRecorder()
        self.dt_ms    = dt_ms
        self.elapsed_ms: float = 0.0
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

    def load_circuit(self, circuit: dict, skip_refs: set[str] | None = None):
        """
        Wire the simulation from a circuit dict (parsed from a circuit.json).

        Equivalent to load() but takes a hand-written circuit definition instead
        of a KiCad schematic.  skip_refs names parts to skip during
        auto-instantiation — typically the MCU when C++ firmware replaces it.
        """
        from core.circuit import to_netlist
        self._netlist = to_netlist(circuit)
        self.bus.load_netlist(self._netlist)

        # Drive explicit power rails (overrides the bus's auto-detected names)
        for net_name, voltage in circuit.get("power", {}).items():
            self.bus.gpio.drive(net_name, "_pwr", float(voltage))

        self._auto_instantiate(skip_refs=skip_refs)
        nodes = list(self.bus._nodes.values())
        self.physics.load(nodes, self._netlist)

    def _auto_instantiate(self, skip_refs: set[str] | None = None):
        """
        For every IC component in the netlist, instantiate its Node subclass
        (if registered), register it on the bus, then call attach() and reset()
        so MCU nodes can build their PinMap and shim before the first tick.
        skip_refs: references to skip (e.g. the MCU when C++ firmware drives it).
        """
        skip = skip_refs or set()
        if not self._netlist:
            return
        for ref, comp in self._netlist.components.items():
            if ref in skip:
                continue
            lib_id = comp.get("part", "")
            node_class = registry.resolve(ref, lib_id)
            if node_class is None:
                continue

            # Merge static part descriptor with schematic-derived data.
            # Schematic pin→net assignments always take precedence over the
            # static descriptor's pin definitions.
            static = _load_part_descriptor(node_class)
            if static:
                descriptor = {**static, **{k: v for k, v in comp.items() if k != "pins"}}
                descriptor["pins"] = {**static.get("pins", {}), **comp.get("pins", {})}
            else:
                descriptor = comp

            node = node_class(instance_id=ref, descriptor=descriptor)
            self.bus.register(node)
            if hasattr(node, "attach_bus"):
                node.attach_bus(self.bus)
            if hasattr(node, "attach"):
                node.attach(self._netlist, self.bus, self)
            node.reset()

    # -------------------------------------------------------------- manual ---

    def add_node(self, node: Node):
        """
        Manually add a node (voltage sources, unregistered parts, test stubs).
        Calls attach_bus() for VoltageSourceNode subclasses and attach() for
        MCU-style nodes that need netlist + runner context.
        """
        self.bus.register(node)
        if hasattr(node, "attach_bus"):
            node.attach_bus(self.bus)
        if hasattr(node, "attach") and self._netlist:
            node.attach(self._netlist, self.bus, self)
        node.reset()
        nodes = list(self.bus._nodes.values())
        if self._netlist:
            self.physics.load(nodes, self._netlist)

    # ----------------------------------------------------------------- tick ---

    def tick(self, dt_ms: float | None = None):
        """
        Advance the simulation by one timestep.

        Sequence per tick:
          1. Snapshot interrupt net states (before anything changes)
          2. All nodes tick (firmware runs, sensors update output regs)
          3. Physics tick (R/C/L transients + thermal)
          4. Advance elapsed time
          5. Fire any pending interrupt callbacks
          6. Record waveform samples
          7. Invoke on_tick callbacks
        """
        dt = dt_ms if dt_ms is not None else self.dt_ms
        self.bus.interrupt.snapshot(self.bus.gpio)
        self.bus.tick_all(dt)
        self.physics.tick(dt, self.bus.gpio)
        self.elapsed_ms += dt
        self.bus.interrupt.tick(self.bus.gpio)
        if self.recorder:
            self.recorder.record(self.elapsed_ms, self.bus.gpio)
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

    # --------------------------------------------------------------- probing ---

    def probe(self, net_name: str, label: str | None = None):
        """Start recording a net voltage every tick. Returns the channel."""
        return self.recorder.probe(net_name, label)

    def waveform(self, net_name: str) -> list[tuple[float, float]]:
        """Return recorded [(time_ms, voltage)] pairs for a net."""
        return self.recorder.waveform(net_name)

    # --------------------------------------------------------------- state ----

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
        """Reset all nodes, clear elapsed time, and clear waveform data."""
        self.elapsed_ms = 0.0
        self.recorder.clear()
        for node in self.bus._nodes.values():
            node.reset()

    def __repr__(self):
        return (f"<SimRunner  t={self.elapsed_ms:.1f}ms  "
                f"nodes={len(self.bus._nodes)}  "
                f"nets={len(self.bus.gpio._nets)}>")
