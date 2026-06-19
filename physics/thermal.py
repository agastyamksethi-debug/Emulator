"""
Thermal model.

Each node has a thermal_resistance (°C/W) from its descriptor.
Power dissipation heats the node; heat spreads to adjacent nodes
proportional to 1/thermal_resistance between them.

Simple lumped-capacitance model — good enough for overtemp detection
and thermal throttling flags, not a substitute for FEA.
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.node import Node
    from core.netlist import NetList

AMBIENT_C = 25.0
DEFAULT_THERMAL_CAPACITANCE = 1.0   # J/°C — generic PCB component


class ThermalModel:
    def __init__(self, ambient_c: float = AMBIENT_C):
        self.ambient_c = ambient_c

    def load(self, nodes: list[Node], netlist: NetList):
        self._nodes = nodes
        # TODO: build adjacency graph from netlist for heat spreading

    def tick(self, dt_ms: float, nodes: list[Node]):
        dt_s = dt_ms / 1000.0
        for node in nodes:
            resistance = node.descriptor.get("thermal_resistance_c_per_w", 50.0)
            capacitance = node.descriptor.get("thermal_capacitance_j_per_c", DEFAULT_THERMAL_CAPACITANCE)

            # Heat generated this tick
            heat_in = node.power_dissipation * dt_s                    # joules

            # Convective cooling toward ambient
            heat_out = ((node.temperature - self.ambient_c) / resistance) * dt_s

            node.temperature += (heat_in - heat_out) / capacitance

        # TODO: spread heat between adjacent nodes via their shared nets
