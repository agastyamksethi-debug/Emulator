"""
Firmware-bridge tests — compiled sketches over the IPC bridge.

Covers the Wire/I2C path, base Serial printing, and external interrupts
(attachInterrupt + the MPU-6050 INT pin).  Requires g++.

Run:  python3 tests/test_firmware.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import parts as _parts
for _e in os.scandir(os.path.join(os.path.dirname(__file__), "..", "parts")):
    if _e.is_dir() and os.path.exists(os.path.join(_e.path, "model.py")):
        _parts.load_part(_e.name)

from core.fidelity import CONFIG, Level
CONFIG.real_world = Level.BASIC          # deterministic (no sensor noise)

from core.cpp_runtime import compile_sketch, CppFirmware
from core.runner import SimRunner
from core.circuit import to_netlist, mcu_pinmap
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _run(example, steps=8, setup=None):
    circ = json.load(open(os.path.join(_ROOT, "examples", example, "circuit.json")))
    binary = compile_sketch(os.path.join(_ROOT, "examples", example, "sketch.ino"))
    nl = to_netlist(circ)
    r = SimRunner(); r._netlist = nl; r.bus.load_netlist(nl)
    for net, v in circ.get("power", {}).items():
        r.bus.gpio.drive(net, "_pwr", float(v))
    r._auto_instantiate()
    if setup:
        setup(r)
    out = []
    fw = CppFirmware(binary, pin_map=mcu_pinmap(circ, circ["mcu"]),
                     v_supply=3.3, serial_cb=out.append)
    fw.attach(r.bus, r)
    fw.start()
    for _ in range(steps):
        d = fw._read_until_delay()
        if d <= 0:
            break
        r.run(duration_ms=d)
        fw._send("OK")
    fw.stop()
    return "".join(out)


def test_i2c_wire_reads_whoami():
    out = _run("mpu6050", steps=3)
    assert "WHO_AM_I: 0x68" in out, out


def test_mpu_interrupt_fires():
    out = _run("mpu6050_interrupt", steps=8,
               setup=lambda r: r.node("IMU1").set_acceleration(0.1, 0.0, 0.95))
    assert out.count("INT #") >= 2, out      # interrupt-driven reads happened


if __name__ == "__main__":
    fails = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"PASS  {name}")
            except AssertionError as e:
                fails += 1
                print(f"FAIL  {name}: {str(e)[:200]}")
    sys.exit(1 if fails else 0)
