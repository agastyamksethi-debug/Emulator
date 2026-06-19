#!/usr/bin/env python3
"""
PCB Simulator CLI
=================

Usage:
  python3 sim.py <sketch.ino> --circuit <circuit.json>  [options]
  python3 sim.py <sketch.ino> --pin N=NET --led NET     [options]  ← quick mode

Circuit mode  (recommended — full schematic):
  sim firmware.ino --circuit board.json

  board.json defines every part, its value, and its wiring.
  Power rails, resistors, caps, LEDs, the MCU — all declared once.
  The simulator reads it, instantiates everything, and derives pin wiring
  automatically from the MCU's gpio_map.  No --pin or --led flags needed.

Quick mode  (no circuit file — for fast prototyping):
  sim blink.ino --pin 2=LED --led LED

Options:
  --circuit FILE   Path to circuit.json  (enables full schematic mode)
  --pin     N=NET  Map Arduino GPIO N to net NET  (repeatable, overrides circuit)
  --led     NET    Add an LED, anode=NET cathode=GND  (quick mode only)
  --led     NET:K  Same but cathode on net K
  --duration MS    Simulated time in ms  (default: 2000)
  --vf      V      LED forward voltage   (default: 2.0, quick mode only)
  --probe   NET    Waveform summary for NET after run  (repeatable)
  --output  PATH   Compiled binary destination  (default: auto next to .ino)
"""

import sys
import os
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.runner import SimRunner
from core.cpp_runtime import compile_sketch, CppFirmware
from parts.led.model import LEDNode


# ── helpers ───────────────────────────────────────────────────────────────────

def parse_pin(s: str) -> tuple[int, str]:
    if "=" not in s:
        sys.exit(f"--pin must be N=NET  (got: {s!r})")
    pin_s, net = s.split("=", 1)
    try:
        return int(pin_s), net
    except ValueError:
        sys.exit(f"--pin: pin number must be an integer  (got: {pin_s!r})")


def parse_led(s: str) -> tuple[str, str]:
    if ":" in s:
        a, k = s.split(":", 1)
        return a, k
    return s, "GND"


def _probe_summary(runner: SimRunner, nets: list[str]):
    for net in nets:
        wf = runner.waveform(net)
        if not wf:
            continue
        highs = sum(1 for _, v in wf if v > 1.65)
        lows  = len(wf) - highs
        v_min = min(v for _, v in wf)
        v_max = max(v for _, v in wf)
        transitions = sum(
            1 for i in range(1, len(wf))
            if (wf[i][1] > 1.65) != (wf[i-1][1] > 1.65)
        )
        print(f"\nProbe [{net}]:")
        print(f"  HIGH {highs} ms  /  LOW {lows} ms")
        print(f"  Voltage range: {v_min:.2f} V – {v_max:.2f} V")
        print(f"  Transitions: {transitions}")


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sim",
        description="Compile and simulate an Arduino sketch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("sketch",
        help="Path to the .ino firmware file")
    parser.add_argument("--circuit", metavar="FILE",
        help="Circuit definition JSON (full schematic mode)")
    parser.add_argument("--pin", metavar="N=NET", action="append", default=[],
        help="Map Arduino GPIO N to bus net NET (repeatable)")
    parser.add_argument("--led", metavar="NET[:K]", action="append", default=[],
        help="Add an LED in quick mode (repeatable)")
    parser.add_argument("--duration", metavar="MS", type=float, default=2000,
        help="Simulated run time in milliseconds (default: 2000)")
    parser.add_argument("--vf", metavar="V", type=float, default=2.0,
        help="LED forward voltage in volts, quick mode (default: 2.0)")
    parser.add_argument("--probe", metavar="NET", action="append", default=[],
        help="Print waveform summary for this net after run (repeatable)")
    parser.add_argument("--output", metavar="PATH", default=None,
        help="Compiled binary path (default: <sketch>_sim)")
    args = parser.parse_args()

    sketch = os.path.abspath(args.sketch)
    if not os.path.exists(sketch):
        sys.exit(f"Sketch not found: {sketch}")

    # ── compile ───────────────────────────────────────────────────────────────
    print(f"Compiling  {os.path.relpath(sketch)} ...")
    try:
        binary = compile_sketch(sketch, output_path=args.output)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"  → {os.path.relpath(binary)}\n")

    runner = SimRunner(dt_ms=1.0)
    for net in args.probe:
        runner.probe(net, label=net)

    # ══════════════════════════════════════════════════════════════════════════
    # CIRCUIT MODE  — full schematic from circuit.json
    # ══════════════════════════════════════════════════════════════════════════
    if args.circuit:
        from core import circuit as _circ

        circuit_path = os.path.abspath(args.circuit)
        if not os.path.exists(circuit_path):
            sys.exit(f"Circuit file not found: {circuit_path}")

        circ = _circ.load(circuit_path)

        # Find the MCU in the circuit (auto or from circ["mcu"])
        mcu_ref = _circ.find_mcu(circ)
        if not mcu_ref:
            sys.exit(
                "No MCU found in circuit file.  "
                "Add '\"mcu\": \"U1\"' or make sure your MCU type has a "
                "descriptor with a gpio_map."
            )

        print(f"Circuit:   {os.path.relpath(circuit_path)}")
        print(f"MCU:       {mcu_ref}  ({circ['parts'][mcu_ref]['type']})")

        # Load circuit — skip MCU instantiation, C++ firmware replaces it
        runner.load_circuit(circ, skip_refs={mcu_ref})

        # Derive pin_map from MCU wiring; --pin flags override/extend it
        pin_map = _circ.mcu_pinmap(circ, mcu_ref)
        pin_map.update(dict(parse_pin(p) for p in args.pin))

        # Print wiring summary
        mcu_pins = circ["parts"][mcu_ref].get("pins", {})
        other_parts = {r: p for r, p in circ["parts"].items() if r != mcu_ref}
        print(f"\nParts ({len(other_parts)}):")
        for ref, part in other_parts.items():
            ptype = part.get("type", "?")
            val   = part.get("value", "")
            pins  = part.get("pins", {})
            pin_str = "  ".join(f"{k}→{v}" for k, v in pins.items())
            print(f"  {ref:4s}  {ptype:16s}  {val:6s}  {pin_str}")

        if circ.get("power"):
            print(f"\nPower rails:")
            for net, v in circ["power"].items():
                print(f"  {net} = {v} V")

    # ══════════════════════════════════════════════════════════════════════════
    # QUICK MODE  — --pin / --led flags only
    # ══════════════════════════════════════════════════════════════════════════
    else:
        pin_map  = dict(parse_pin(p) for p in args.pin)
        led_nets = [parse_led(s) for s in args.led]

        runner.bus.gpio.drive("GND", "_pwr", 0.0)

        for i, (anode, cathode) in enumerate(led_nets, start=1):
            led = LEDNode(
                f"D{i}",
                {"pins": {"A": anode, "K": cathode}, "vf": args.vf},
            )
            runner.bus.register(led)
            led.attach_bus(runner.bus)
            led.reset()
            print(f"  LED D{i}:  {anode} → [{args.vf}V drop] → {cathode}")

        if not pin_map and not led_nets:
            print("  (no --pin or --led specified — firmware output only)\n")

    # ── shared: print pin map, start firmware ─────────────────────────────────
    if pin_map:
        print(f"\nPin map:")
        for gpio, net in sorted(pin_map.items()):
            print(f"  GPIO{gpio:2d} → {net}")

    fw = CppFirmware(binary, pin_map=pin_map)
    fw.attach(runner.bus, runner)
    print(f"\nRunning setup() ...")
    fw.start()

    # ── run ───────────────────────────────────────────────────────────────────
    print(f"\n{'─'*52}")
    fw.run(duration_ms=args.duration)
    print(f"{'─'*52}")
    print(f"\nSimulated: {runner.elapsed_ms:.0f} ms")

    _probe_summary(runner, args.probe)
    fw.stop()


if __name__ == "__main__":
    main()
