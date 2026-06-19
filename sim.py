#!/usr/bin/env python3
"""
PCB Simulator CLI
=================

Usage:
  python3 sim.py <sketch.ino> [options]

Examples:
  python3 sim.py examples/blink.ino --pin 2=LED --led LED
  python3 sim.py firmware/sensor.ino --pin 2=LED --pin 36=ADC_IN --led LED --duration 5000
  python3 sim.py firmware/read.ino   --pin 36=VOUT --probe VOUT --duration 1000

Options:
  --pin  N=NET     Map Arduino GPIO N to bus net NET  (repeatable)
  --led  NET       Add an LED with anode on NET, cathode on GND  (repeatable)
  --led  NET:GND   Same but specify the cathode net explicitly
  --duration MS    Simulated time in milliseconds  (default: 2000)
  --vf   V         LED forward voltage in volts    (default: 2.0)
  --probe NET      Print waveform summary for NET after run  (repeatable)
  --output PATH    Where to write the compiled binary (default: auto)
"""

import sys
import os
import argparse

# Make sure project root is on the path
sys.path.insert(0, os.path.dirname(__file__))

from core.runner import SimRunner
from core.cpp_runtime import compile_sketch, CppFirmware
from parts.led.model import LEDNode


# ── argument parsing ─────────────────────────────────────────────────────────

def parse_pin(s: str) -> tuple[int, str]:
    """Parse '2=LED_NET' → (2, 'LED_NET')"""
    if "=" not in s:
        sys.exit(f"--pin must be N=NET  (got: {s!r})")
    pin_s, net = s.split("=", 1)
    try:
        return int(pin_s), net
    except ValueError:
        sys.exit(f"--pin: pin number must be an integer  (got: {pin_s!r})")


def parse_led(s: str) -> tuple[str, str]:
    """Parse 'NET' or 'NET:GND_NET' → (anode_net, cathode_net)"""
    if ":" in s:
        a, k = s.split(":", 1)
        return a, k
    return s, "GND"


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        prog="sim.py",
        description="Compile and simulate an Arduino sketch.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
        add_help=True,
    )
    parser.add_argument("sketch",
        help="Path to the .ino file to simulate")
    parser.add_argument("--pin", metavar="N=NET", action="append", default=[],
        help="Map Arduino GPIO N to bus net NET (repeatable)")
    parser.add_argument("--led", metavar="NET[:GND]", action="append", default=[],
        help="Add an LED with anode on NET (repeatable)")
    parser.add_argument("--duration", metavar="MS", type=float, default=2000,
        help="Simulated run time in milliseconds (default: 2000)")
    parser.add_argument("--vf", metavar="V", type=float, default=2.0,
        help="LED forward voltage in volts (default: 2.0)")
    parser.add_argument("--probe", metavar="NET", action="append", default=[],
        help="Print waveform summary for a net after run (repeatable)")
    parser.add_argument("--output", metavar="PATH", default=None,
        help="Output binary path (default: <sketch>_sim)")
    args = parser.parse_args()

    sketch = os.path.abspath(args.sketch)
    if not os.path.exists(sketch):
        sys.exit(f"Sketch not found: {sketch}")

    pin_map  = dict(parse_pin(p) for p in args.pin)
    led_nets = [parse_led(s) for s in args.led]

    # ── compile ───────────────────────────────────────────────────────────────
    print(f"Compiling {os.path.relpath(sketch)} ...")
    try:
        binary = compile_sketch(sketch, output_path=args.output)
    except RuntimeError as e:
        sys.exit(str(e))
    print(f"  → {os.path.relpath(binary)}\n")

    # ── simulation setup ──────────────────────────────────────────────────────
    runner = SimRunner(dt_ms=1.0)
    runner.bus.gpio.drive("GND", "_pwr", 0.0)

    # Add LED parts
    for i, (anode, cathode) in enumerate(led_nets, start=1):
        led = LEDNode(
            f"D{i}",
            {"pins": {"A": anode, "K": cathode}, "vf": args.vf},
        )
        runner.bus.register(led)
        led.attach_bus(runner.bus)
        led.reset()
        print(f"  LED D{i}: anode={anode}  cathode={cathode}  Vf={args.vf}V")

    # Probe nets
    for net in args.probe:
        runner.probe(net, label=net)

    if pin_map:
        print(f"\n  Pin map:")
        for gpio, net in sorted(pin_map.items()):
            print(f"    GPIO{gpio} → {net}")

    # ── firmware ──────────────────────────────────────────────────────────────
    fw = CppFirmware(binary, pin_map=pin_map)
    fw.attach(runner.bus, runner)
    print(f"\nRunning setup() ...")
    fw.start()

    # ── run ───────────────────────────────────────────────────────────────────
    print(f"\n{'─'*50}")
    fw.run(duration_ms=args.duration)
    print(f"{'─'*50}")
    print(f"\nSimulated: {runner.elapsed_ms:.0f} ms")

    # ── probe summary ─────────────────────────────────────────────────────────
    for net in args.probe:
        wf = runner.waveform(net)
        if not wf:
            continue
        highs  = sum(1 for _, v in wf if v > 1.65)
        lows   = len(wf) - highs
        v_min  = min(v for _, v in wf)
        v_max  = max(v for _, v in wf)
        transitions = sum(
            1 for i in range(1, len(wf))
            if (wf[i][1] > 1.65) != (wf[i-1][1] > 1.65)
        )
        print(f"\nProbe [{net}]:")
        print(f"  HIGH: {highs} ms   LOW: {lows} ms")
        print(f"  V range: {v_min:.2f} V – {v_max:.2f} V")
        print(f"  Transitions: {transitions}")

    fw.stop()


if __name__ == "__main__":
    main()
