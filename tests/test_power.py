"""
Power-rail stability tests — rails have source impedance (stable, not ideal);
heavy loads sag them and can brown out a part.

Run:  python3 tests/test_power.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parts as _parts
for _e in os.scandir(os.path.join(os.path.dirname(__file__), "..", "parts")):
    if _e.is_dir() and os.path.exists(os.path.join(_e.path, "model.py")):
        _parts.load_part(_e.name)

from core.analyzer import analyze
from core.fidelity import CONFIG, Level
from core.runner import SimRunner

_MPU = {"type": "mpu6050", "pins": {"VCC": "3V3", "GND": "GND",
        "SDA": "SDA", "SCL": "SCL", "AD0": "GND"}}


def test_default_rail_is_stable():
    # default source impedance: a normal board barely sags and never browns out
    board = {"power": {"3V3": 3.3, "GND": 0.0}, "parts": {
        "IMU1": _MPU,
        "R1": {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SDA"}},
        "R2": {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SCL"}},
    }}
    plan = analyze(board, advanced=True)
    assert not any(d.code == "erc.brownout" for d in plan.diagnostics)
    rail = next(p for p in plan.phenomena if p.kind == "rail_load")
    assert rail.result["v_loaded"] > 3.28        # essentially full voltage


def test_brownout_on_weak_loaded_rail():
    board = {"power": {"3V3": {"v": 3.3, "r_src": 3.0}, "GND": 0.0}, "parts": {
        "IMU1": _MPU,
        "RL": {"type": "resistor", "value": "3", "pins": {"1": "3V3", "2": "GND"}},
    }}
    plan = analyze(board, advanced=True)
    assert any(d.code == "erc.brownout" and "3V3" in d.nets for d in plan.diagnostics)


def test_runtime_rail_sags_under_load():
    CONFIG.electrical = Level.ADVANCED
    try:
        r = SimRunner()
        r.load_circuit({"power": {"3V3": {"v": 3.3, "r_src": 3.0}, "GND": 0.0},
                        "parts": {"RL": {"type": "resistor", "value": "3",
                                         "pins": {"1": "3V3", "2": "GND"}}}})
        for _ in range(5):
            r.tick(1.0)
        assert r.bus.gpio.voltage("3V3") < 2.0      # sagged well below nominal
    finally:
        CONFIG.electrical = Level.BASIC


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn(); print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1; print(f"FAIL  {name}: {e}")
    sys.exit(1 if fails else 0)
