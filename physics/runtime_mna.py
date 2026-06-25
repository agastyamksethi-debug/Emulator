"""
Runtime MNA electrical model (Advanced `electrical` tier).

Replaces PassiveModel's series-R voltage *propagation* with a real nodal solve
each tick, so the live simulation matches the static analyzer: dividers, loaded
nodes, and LED/diode currents are solved properly instead of approximated.

How it stays consistent with the behavioral models:
  - Every net that is *externally driven* — power rails, firmware GPIO outputs,
    behavioral sensor outputs (LDR/pot/…), capacitor junction voltages — is
    pinned as a Thévenin source at its current value.
  - The R/diode/LED/BJT/MOSFET interconnect is stamped as MNA devices.
  - The solver computes every *internal* (undriven) node; those are written back
    to the bus under the "_mna" driver id.

PassiveModel cooperates by releasing its R/diode propagation drivers in this
tier (it still computes power for the thermal model). Capacitors/inductors keep
driving their nodes — they're the dynamic sources the DC solve reads.
"""

from __future__ import annotations

# driver ids that are NOT real sources (our own / propagation artifacts)
_SKIP_PREFIXES = ("_res_", "_diode_", "_mna")
_GND_NETS = {"GND", "AGND", "DGND", "PGND", "VSS", "0"}


class RuntimeMNA:
    def __init__(self):
        self._warned = False

    def solve_writeback(self, circuit: dict, gpio, nodes=None) -> None:
        from physics.mna import build_devices, MNASolver

        # 1. drop last tick's solution so it isn't mistaken for a source
        for ns in gpio._nets.values():
            ns._drivers.pop("_mna", None)

        # 2. snapshot external sources (lowest-wins, like the bus), excl. ground
        driven: dict[str, float] = {}
        for net, ns in gpio._nets.items():
            if net in _GND_NETS:
                continue
            vals = [v for k, v in ns._drivers.items()
                    if not k.startswith(_SKIP_PREFIXES)]
            if vals:
                driven[net] = min(vals)
        if not driven:
            return

        # 3. build + solve the network (sources pinned, interconnect stamped)
        try:
            devices = build_devices(circuit, driven)
            solver = MNASolver()
            solver.load(devices)
            volts = solver.solve_dc()
        except Exception:
            return

        # 4. write back the solved internal nodes
        for net, v in volts.items():
            if net not in driven and net not in _GND_NETS:
                gpio.drive(net, "_mna", float(v))

        # 5. hand each LED its true current (= current through its series resistor)
        #    so the behavioural brightness model uses the solved value, not a heuristic
        if nodes:
            self._update_led_currents(circuit, gpio, nodes)

    def _update_led_currents(self, circuit: dict, gpio, nodes) -> None:
        from physics.mna.netlist_adapter import _parse_value

        resistors = [(p.get("pins") or {}, _parse_value(str(p.get("value", ""))))
                     for p in circuit.get("parts", {}).values()
                     if p.get("type", "").lower() in ("resistor", "r", "device:r")]

        for node in nodes:
            if not (hasattr(node, "anode_net") and hasattr(node, "brightness_pct")):
                continue
            anode = node.anode_net
            node._mna_current_ma = None
            for pins, r_ohm in resistors:
                vals = list(pins.values())
                if anode in vals and r_ohm and r_ohm > 0:
                    other = next((v for v in vals if v != anode), None)
                    if other:
                        i = abs(gpio.voltage(other) - gpio.voltage(anode)) / r_ohm
                        node._mna_current_ma = i * 1000.0
                    break
