"""
Runtime-MNA electrical tier tests.

The behavioural series-R model can't solve a divider; the Advanced `electrical`
tier solves the real network each tick.

Run:  python3 tests/test_electrical.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parts as _parts
for _e in os.scandir(os.path.join(os.path.dirname(__file__), "..", "parts")):
    if _e.is_dir() and os.path.exists(os.path.join(_e.path, "model.py")):
        _parts.load_part(_e.name)

from core.fidelity import CONFIG, Level
from core.runner import SimRunner

_DIVIDER = {"power": {"3V3": 3.3, "GND": 0.0}, "parts": {
    "R1": {"type": "resistor", "value": "10k", "pins": {"1": "3V3", "2": "MID"}},
    "R2": {"type": "resistor", "value": "10k", "pins": {"1": "MID", "2": "GND"}},
}}


def _mid(advanced):
    CONFIG.electrical = Level.ADVANCED if advanced else Level.BASIC
    try:
        r = SimRunner()
        r.load_circuit(_DIVIDER)
        for _ in range(5):
            r.tick(1.0)
        return r.bus.gpio.voltage("MID")
    finally:
        CONFIG.electrical = Level.BASIC


def test_runtime_mna_solves_divider():
    v = _mid(advanced=True)
    assert abs(v - 1.65) < 0.02, f"MID={v}"


def test_basic_cannot_divide():
    # series-R propagation gives the rail, not the midpoint
    v = _mid(advanced=False)
    assert v > 3.0, f"MID={v}"


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL  {name}: {e}")
    sys.exit(1 if fails else 0)
