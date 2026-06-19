"""
C++ blink smoke test.

Compiles examples/blink.ino against the simulator shim, wires it to an LED
node on "GPIO_2", and runs 2 seconds of simulated time.

Expected output:
  Compiled: examples/blink_sim
  === C++ Blink (2000 ms) ===
  Blink starting!
  LED ON  t=0
  [LED D1] ON   (V=3.30V  anode=3.30V  t=1.0ms)
  LED OFF t=500
  [LED D1] OFF  (V=0.00V  anode=0.00V  t=501.0ms)
  LED ON  t=1000
  [LED D1] ON   (V=3.30V  anode=3.30V  t=1001.0ms)
  LED OFF t=1500
  [LED D1] OFF  (V=0.00V  anode=0.00V  t=1501.0ms)
  === Done: 2000 ms simulated ===
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.runner import SimRunner
from core.cpp_runtime import compile_sketch, CppFirmware
from parts.led.model import LEDNode

# ── 1. Compile the sketch ─────────────────────────────────────────────────────
sketch  = os.path.join(os.path.dirname(__file__), "blink.ino")
binary  = os.path.join(os.path.dirname(__file__), "blink_sim")
binary  = compile_sketch(sketch, output_path=binary)
print(f"Compiled: {os.path.relpath(binary)}")

# ── 2. Simulation setup ───────────────────────────────────────────────────────
runner = SimRunner(dt_ms=1.0)

# LED: Arduino pin 2 drives net "GPIO_2"; LED anode is on that net
led = LEDNode("D1", {"pins": {"A": "GPIO_2", "K": "GND"}, "vf": 2.0})
runner.bus.register(led)
led.attach_bus(runner.bus)
led.reset()
runner.bus.gpio.drive("GND", "_pwr", 0.0)
runner.probe("GPIO_2", label="GPIO2")

# ── 3. Firmware ───────────────────────────────────────────────────────────────
fw = CppFirmware(binary, pin_map={2: "GPIO_2"})
fw.attach(runner.bus, runner)
fw.start()   # compiles once, runs setup()

# ── 4. Run ────────────────────────────────────────────────────────────────────
print("=== C++ Blink (2000 ms) ===")
fw.run(duration_ms=2000)
print(f"=== Done: {runner.elapsed_ms:.0f} ms simulated ===")
fw.stop()

# ── 5. Waveform summary ───────────────────────────────────────────────────────
wf = runner.waveform("GPIO_2")
highs = sum(1 for _, v in wf if v > 1.65)
print(f"GPIO_2 HIGH for {highs} ms out of {len(wf)} ms total")
