"""
GPIO / analog net state model.

Each net carries both a digital state (0/1) and a float voltage.
Digital drivers quantize to 0 V or V_supply; analog drivers (passives,
ADC outputs) write a float voltage directly. Readers get whichever
representation they need.
"""

from __future__ import annotations
from dataclasses import dataclass, field

V_SUPPLY = 3.3    # default logic-high voltage (V)


@dataclass
class NetState:
    """Voltage and drive state of one named net."""
    name: str
    _voltage: float = 0.0
    _pull: float | None = None      # pull-up/down voltage, None = floating
    _drivers: dict[str, float] = field(default_factory=dict)  # node_id -> V

    # --- driving ------------------------------------------------------------

    def drive_digital(self, node_id: str, high: bool, v_supply: float = V_SUPPLY):
        """Drive from a digital output: HIGH → v_supply, LOW → 0."""
        self._drivers[node_id] = v_supply if high else 0.0

    def drive_voltage(self, node_id: str, voltage: float):
        """Drive an explicit analog voltage onto the net."""
        self._drivers[node_id] = voltage

    def release(self, node_id: str):
        """Stop driving (tri-state / input mode)."""
        self._drivers.pop(node_id, None)

    # --- reading ------------------------------------------------------------

    @property
    def voltage(self) -> float:
        """
        Resolved net voltage.
        Multiple drivers: lowest voltage wins (wired-AND / open-drain safe).
        No drivers: pull value or 0 V (floating).
        """
        if not self._drivers:
            return self._pull if self._pull is not None else 0.0
        return min(self._drivers.values())

    @property
    def high(self) -> bool:
        """True when net voltage is above logic threshold (V_supply / 2)."""
        return self.voltage > V_SUPPLY / 2

    @property
    def digital(self) -> int:
        return 1 if self.high else 0


class GPIOBus:
    """Holds the voltage state of every net in the simulation."""

    def __init__(self, v_supply: float = V_SUPPLY):
        self.v_supply = v_supply
        self._nets: dict[str, NetState] = {}

    # --- net management -----------------------------------------------------

    def add_net(self, name: str, pull: float | None = None) -> NetState:
        net = NetState(name=name, _pull=pull)
        self._nets[name] = net
        return net

    def net(self, name: str) -> NetState:
        """Get-or-create a net by name."""
        if name not in self._nets:
            self._nets[name] = NetState(name=name)
        return self._nets[name]

    def load_from_netlist(self, netlist):
        """Create a NetState entry for every net in the netlist."""
        for net_name in netlist.nets:
            self.net(net_name)

    # --- convenience writes -------------------------------------------------

    def drive(self, net_name: str, node_id: str, voltage: float):
        self.net(net_name).drive_voltage(node_id, voltage)

    def drive_digital(self, net_name: str, node_id: str, high: bool):
        self.net(net_name).drive_digital(node_id, high, self.v_supply)

    def release(self, net_name: str, node_id: str):
        self.net(net_name).release(node_id)

    # --- convenience reads --------------------------------------------------

    def voltage(self, net_name: str) -> float:
        return self.net(net_name).voltage

    def digital(self, net_name: str) -> int:
        return self.net(net_name).digital

    def voltages(self) -> dict[str, float]:
        """Snapshot of all net voltages — passed to PassiveModel.tick()."""
        return {name: n.voltage for name, n in self._nets.items()}
