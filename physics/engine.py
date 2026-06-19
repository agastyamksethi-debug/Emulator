"""
Physics engine — orchestrates all physics passes each simulation tick.

Order each tick:
  1. PassiveModel.tick()  — solve R/C/L transients, update net voltages
  2. ThermalModel.tick()  — spread heat from power dissipation
"""

from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.netlist import NetList
    from core.node import Node
    from core.protocols.gpio import GPIOBus

from physics.thermal import ThermalModel
from physics.passive import PassiveModel


class PhysicsEngine:
    def __init__(self, ambient_c: float = 25.0):
        self.ambient_c = ambient_c
        self._thermal = ThermalModel(ambient_c)
        self._passive = PassiveModel()
        self._nodes: list[Node] = []

    def load(self, nodes: list[Node], netlist: NetList):
        self._nodes = nodes
        self._passive.load(netlist)
        self._thermal.load(nodes, netlist)

    def tick(self, dt_ms: float, gpio_bus: GPIOBus):
        self._passive.tick(dt_ms, gpio_bus)
        self._thermal.tick(dt_ms, self._nodes)

    @property
    def passive(self) -> PassiveModel:
        return self._passive

    @property
    def thermal(self) -> ThermalModel:
        return self._thermal
