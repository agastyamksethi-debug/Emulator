"""
Voltage sources — drives a net to a controlled voltage each tick.

VoltageSourceNode   base class (ideal source)
BatteryNode         finite charge, terminal voltage drops with SoC
RegulatorNode       fixed output; drops below setpoint when input sags

Usage:
    batt = BatteryNode("BT1", output_net="VBAT",
                        v_full=4.2, v_empty=3.0, capacity_mah=2000)
    runner.add_node(batt)

    ldo = RegulatorNode("U3", input_net="VBAT", output_net="3V3",
                         v_out=3.3, v_dropout=0.3)
    runner.add_node(ldo)
"""

from __future__ import annotations
from core.node import Node
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.bus import SimBus


class VoltageSourceNode(Node):
    """
    Ideal voltage source. Drives output_net to self.voltage every tick.
    Subclass and override tick() to implement non-ideal behaviour.
    """

    def __init__(self, instance_id: str, descriptor: dict,
                 output_net: str, voltage: float,
                 internal_resistance: float = 0.0):
        super().__init__(instance_id, descriptor)
        self.output_net         = output_net
        self.voltage            = voltage
        self.internal_resistance = internal_resistance
        self._bus: SimBus | None = None

    def attach_bus(self, bus: SimBus) -> None:
        """Called by runner.add_node() so the source can drive its net."""
        self._bus = bus
        self._drive()

    def _drive(self) -> None:
        if self._bus and self.output_net:
            self._bus.drive(self.output_net, self.id, self.voltage)

    def reset(self) -> None:
        self._drive()

    def tick(self, dt_ms: float) -> None:
        self._drive()

    def __repr__(self):
        return f"<{type(self).__name__} {self.id}  {self.voltage:.3f}V → {self.output_net}>"


class BatteryNode(VoltageSourceNode):
    """
    Primary or rechargeable cell.

    Terminal voltage follows a linear approximation between v_full (SoC=1)
    and v_empty (SoC=0). Current draw is estimated from power_dissipation
    set by downstream nodes; if nothing sets it, the battery doesn't drain.
    """

    def __init__(self, instance_id: str,
                 output_net:  str,
                 v_full:      float = 4.2,
                 v_empty:     float = 3.0,
                 capacity_mah: float = 2000.0,
                 internal_resistance: float = 0.1,
                 initial_soc: float = 1.0):
        descriptor = {
            "part": "Battery",
            "classification": "Battery",
            "thermal_resistance_c_per_w": 200.0,
            "thermal_capacitance_j_per_c": 2.0,
        }
        v_init = v_empty + initial_soc * (v_full - v_empty)
        super().__init__(instance_id, descriptor, output_net,
                         v_init, internal_resistance)
        self.v_full       = v_full
        self.v_empty      = v_empty
        self.capacity_mah = capacity_mah
        self.soc:         float = initial_soc
        self._charge_mah: float = capacity_mah * initial_soc

    def tick(self, dt_ms: float) -> None:
        v_oc = self.v_empty + self.soc * (self.v_full - self.v_empty)
        if v_oc > 0 and self.power_dissipation > 0:
            current_a   = self.power_dissipation / v_oc
            dt_h        = dt_ms / 3_600_000.0          # ms → hours
            drain_mah   = current_a * 1000.0 * dt_h
            self._charge_mah = max(0.0, self._charge_mah - drain_mah)
            self.soc         = self._charge_mah / self.capacity_mah

        self.voltage = v_oc
        self._drive()

    @property
    def remaining_mah(self) -> float:
        return self._charge_mah

    @property
    def depleted(self) -> bool:
        return self.soc <= 0.0

    def __repr__(self):
        return (f"<Battery {self.id}  SoC={self.soc*100:.1f}%  "
                f"V={self.voltage:.3f}V  rem={self._charge_mah:.0f}mAh>")


class RegulatorNode(VoltageSourceNode):
    """
    Fixed-output voltage regulator (LDO or switching).

    While v_input >= v_out + v_dropout → output is held at v_out.
    Below that threshold the output tracks v_input − v_dropout (dropout).
    """

    def __init__(self, instance_id: str,
                 input_net:   str,
                 output_net:  str,
                 v_out:       float = 3.3,
                 v_dropout:   float = 0.3,
                 i_limit_a:   float = 1.0):
        descriptor = {
            "part": "Regulator",
            "classification": "Power",
            "vdd_nom": v_out,
            "thermal_resistance_c_per_w": 50.0,
            "thermal_capacitance_j_per_c": 0.5,
        }
        super().__init__(instance_id, descriptor, output_net, v_out)
        self.input_net     = input_net
        self.v_out_nom     = v_out
        self.v_dropout     = v_dropout
        self.i_limit_a     = i_limit_a
        self.in_regulation = True

    def tick(self, dt_ms: float) -> None:
        if self._bus is None:
            return
        v_in = self._bus.read_voltage(self.input_net)
        if v_in >= self.v_out_nom + self.v_dropout:
            self.voltage       = self.v_out_nom
            self.in_regulation = True
        else:
            self.voltage       = max(0.0, v_in - self.v_dropout)
            self.in_regulation = False
        self._drive()

    def __repr__(self):
        status = "OK" if self.in_regulation else "DROPOUT"
        return f"<Regulator {self.id}  {self.voltage:.3f}V  {status}>"
