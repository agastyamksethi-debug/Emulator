"""
Blink smoke test
================
Verifies the full node → bus → peripheral pipeline without a KiCad schematic.

What it tests:
  - SimRunner tick loop and elapsed_ms
  - GPIOBus net voltage propagation
  - LEDNode reading net voltages and emitting state-change messages
  - WaveformRecorder capturing a net

Expected output (LED toggles every 500 ms):
  [LED D1] ON   (V=3.30V  anode=3.30V  t=1.0ms)
  [LED D1] OFF  (V=0.00V  anode=0.00V  t=501.0ms)
  [LED D1] ON   (V=3.30V  anode=3.30V  t=1001.0ms)
  [LED D1] OFF  (V=0.00V  anode=0.00V  t=1501.0ms)
  === Complete: 2000.0 ms simulated ===
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.runner import SimRunner
from parts.led.model import LEDNode

# ── 1. Runner ─────────────────────────────────────────────────────────────────
runner = SimRunner(dt_ms=1.0)

# ── 2. LED node: anode on "LED_ANODE", cathode on "GND" ──────────────────────
led = LEDNode(
    instance_id="D1",
    descriptor={"pins": {"A": "LED_ANODE", "K": "GND"}, "vf": 2.0, "color": "red"},
)
runner.bus.register(led)
led.attach_bus(runner.bus)
led.reset()

# ── 3. Static power rails ─────────────────────────────────────────────────────
runner.bus.gpio.drive("GND", "_pwr", 0.0)

# ── 4. Probe the anode net so we can inspect the waveform afterwards ──────────
runner.probe("LED_ANODE", label="Anode")

# ── 5. Run 2 seconds: drive LED_ANODE high for 500 ms, low for 500 ms, repeat ─
print("=== Blink simulation (2000 ms) ===")
PERIOD_MS  = 500
TOTAL_MS   = 2000
V_HIGH     = 3.3
V_LOW      = 0.0

for t in range(TOTAL_MS):
    high = (t // PERIOD_MS) % 2 == 0
    runner.bus.gpio.drive("LED_ANODE", "_blink", V_HIGH if high else V_LOW)
    runner.tick(dt_ms=1.0)

# ── 6. Results ────────────────────────────────────────────────────────────────
print(f"=== Complete: {runner.elapsed_ms:.1f} ms simulated ===")
print(f"Final LED state : {'ON' if led.on else 'OFF'}")

wf = runner.waveform("LED_ANODE")
transitions = sum(1 for i in range(1, len(wf)) if wf[i][1] != wf[i-1][1])
print(f"Waveform samples: {len(wf)}  voltage transitions: {transitions}")

# ── 7. Assertions ─────────────────────────────────────────────────────────────
assert runner.elapsed_ms == TOTAL_MS,          "elapsed_ms mismatch"
assert led.on is False,                        "LED should be OFF at t=2000ms"
assert len(wf) == TOTAL_MS,                   "should have one sample per tick"
assert transitions == 3,                       "expected 3 transitions (ON→OFF→ON→OFF)"
print("All assertions passed.")
