"""
Phase 1 analyzer / planner tests — ERC, characterization, tolerance, cache.

Run:  python3 tests/test_analyzer.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.analyzer import analyze, CharacterizationCache

_GOOD = {
    "power": {"3V3": 3.3, "GND": 0.0},
    "parts": {
        "U1":   {"type": "esp32-wroom-32",
                 "pins": {"VDD": "3V3", "GND_1": "GND", "CHIP_EN": "3V3",
                          "IO21": "SDA", "IO22": "SCL"}},
        "IMU1": {"type": "mpu6050",
                 "pins": {"VCC": "3V3", "GND": "GND", "SDA": "SDA",
                          "SCL": "SCL", "AD0": "GND"}},
        "R1":   {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SDA"}},
        "R2":   {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SCL"}},
        "C1":   {"type": "capacitor", "value": "100n", "pins": {"1": "3V3", "2": "GND"}},
        "C2":   {"type": "capacitor", "value": "10u",  "pins": {"1": "3V3", "2": "GND"}},
    },
}

_BAD = {
    "power": {"3V3": 3.3, "5V": 5.0, "GND": 0.0},
    "parts": {
        "U1":   {"type": "esp32-wroom-32",
                 "pins": {"VDD": "3V3", "GND_1": "GND", "CHIP_EN": "3V3",
                          "IO21": "SDA", "IO22": "SCL"}},
        "IMU1": {"type": "mpu6050",
                 "pins": {"VCC": "5V", "GND": "GND", "SDA": "SDA",
                          "SCL": "SCL", "AD0": "AD0_NET"}},
    },
}


def test_good_board_clean_and_characterized():
    plan = analyze(_GOOD)
    assert not plan.errors(), plan.errors()
    assert not plan.warnings(), plan.warnings()
    kinds = {p.kind for p in plan.phenomena}
    assert "bus_rc" in kinds and "power_sequence" in kinds
    bus = next(p for p in plan.phenomena if p.kind == "bus_rc")
    assert bus.result["modes"]["Standard (100 kHz)"] is True


def test_faulty_board_flags_miswiring():
    plan = analyze(_BAD)
    codes = {d.code for d in plan.diagnostics}
    assert "erc.power_window" in codes      # VCC on a 5 V rail
    assert "erc.floating" in codes          # AD0 dangling
    assert "erc.missing_pullup" in codes    # no SDA/SCL pull-ups
    assert plan.errors()                    # power window is an error


# AD0 driven by a 10k/10k divider → ~1.65 V, an ambiguous logic level
_DIVIDER = {
    "power": {"3V3": 3.3, "GND": 0.0},
    "parts": {
        "IMU1": {"type": "mpu6050",
                 "pins": {"VCC": "3V3", "GND": "GND", "SDA": "SDA",
                          "SCL": "SCL", "AD0": "ADDR"}},
        "R1": {"type": "resistor", "value": "10k", "pins": {"1": "3V3", "2": "ADDR"}},
        "R2": {"type": "resistor", "value": "10k", "pins": {"1": "ADDR", "2": "GND"}},
        "R3": {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SDA"}},
        "R4": {"type": "resistor", "value": "4.7k", "pins": {"1": "3V3", "2": "SCL"}},
    },
}


def test_island_mna_solves_divider():
    from core.islands import find_islands, solve_island
    div = next(i for i in find_islands(_DIVIDER, {"3V3", "GND"})
               if {"R1", "R2"} <= i["parts"])
    v = solve_island(_DIVIDER, div, {"3V3": 3.3, "GND": 0.0})
    assert abs(v["ADDR"] - 1.65) < 0.02, v


def test_advanced_tier_flags_indeterminate_level():
    plan = analyze(_DIVIDER, advanced=True)
    assert any(d.code == "erc.indeterminate_level" and "ADDR" in d.nets
               for d in plan.diagnostics), plan.diagnostics
    # and it produced an analog_island characterization
    assert any(p.kind == "analog_island" for p in plan.phenomena)


def test_basic_tier_skips_mna():
    plan = analyze(_DIVIDER, advanced=False)
    assert not any(p.kind == "analog_island" for p in plan.phenomena)


def test_cache_makes_reruns_free():
    cache = CharacterizationCache()
    analyze(_GOOD, cache)
    misses_after_first = cache.misses
    analyze(_GOOD, cache)
    assert cache.misses == misses_after_first      # nothing recomputed
    assert cache.hits >= misses_after_first        # all served from cache


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}: {e}")
    sys.exit(1 if fails else 0)
