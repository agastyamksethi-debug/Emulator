"""
C++ firmware runtime bridge.

Compiles an Arduino .ino sketch with the simulator shim and runs it as a
subprocess.  Every Arduino API call in the sketch sends a line to Python;
Python drives the bus and responds.  delay() causes Python to advance the
simulation for that many milliseconds before unblocking the C++.

Usage:
    from core.cpp_runtime import compile_sketch, CppFirmware

    binary = compile_sketch("examples/blink.ino")
    fw = CppFirmware(binary, pin_map={2: "GPIO_2"})
    fw.attach(runner.bus, runner)
    fw.start()          # runs setup()
    fw.run(2000)        # run 2 s of simulated time driven by delay() calls
    fw.stop()
"""

from __future__ import annotations
import os
import random
import subprocess
import threading
from collections import deque
from typing import TYPE_CHECKING

from core.fidelity import CONFIG


# ─────────────────────────────────────────────────── ADC conversion ───────────

def adc_convert(voltage: float, v_supply: float, bits: int = 12) -> int:
    """
    Convert a net voltage to an ADC code.

    BASIC     ideal linear:  code = v / v_supply · full_scale
    ADVANCED  ESP32-like:    usable input window (~0.1–3.1 V) with saturation at
              both ends, mild S-curve non-linearity, and a few LSB of noise.
    """
    full = (1 << bits) - 1
    if not CONFIG.is_advanced("adc"):
        return max(0, min(full, int(voltage / v_supply * full)))

    # ESP32: roughly dead below ~0.1 V, saturates above ~3.1 V
    lo, hi = 0.10, min(3.1, v_supply)
    x = (voltage - lo) / (hi - lo)
    x = max(0.0, min(1.0, x))
    # mild S non-linearity (the ESP32 ADC bows away from the ideal line)
    x = x + 0.06 * (x - 0.5) * (1.0 - abs(2.0 * x - 1.0))
    code = x * full + random.gauss(0.0, 8.0)   # ~8 LSB RMS noise
    return max(0, min(full, int(round(code))))

if TYPE_CHECKING:
    from core.bus import SimBus
    from core.runner import SimRunner

_FIRMWARE_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "firmware")
)


# ─────────────────────────────────────────────────── compilation ──────────────

def compile_sketch(sketch_path: str, output_path: str | None = None) -> str:
    """
    Compile a .ino file against sim_arduino.h and return the binary path.

    The sketch is force-included with sim_arduino.h so it can use all Arduino
    API calls without any #include at the top of the .ino file.
    """
    sketch_path = os.path.abspath(sketch_path)
    if output_path is None:
        output_path = os.path.splitext(sketch_path)[0] + "_sim"

    sim_header = os.path.join(_FIRMWARE_DIR, "sim_arduino.h")
    sim_main   = os.path.join(_FIRMWARE_DIR, "sim_main.cpp")

    cmd = [
        "g++", "-std=c++17",
        "-I", _FIRMWARE_DIR,
        "-include", sim_header,
        "-x", "c++", sketch_path,   # treat .ino as C++
        sim_main,
        "-o", output_path,
        "-Wno-unused-function",
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"Compilation failed for {os.path.basename(sketch_path)}:\n"
            f"{result.stderr}"
        )

    return output_path


# ─────────────────────────────────────────────────── runtime bridge ───────────

class CppFirmware:
    """
    IPC bridge between a compiled Arduino sketch and the Python simulation bus.

    Protocol summary (each message is one line):
      C++ → Python:  PM DW DR AR AW DELAY MILLIS SER SERLN SER_AVAIL SER_READ
                     I2CW I2CR READY
      Python → C++:  OK  or  <integer>  or  <hexbytes>
    """

    def __init__(self, binary: str, pin_map: dict[int, str],
                 v_supply: float = 3.3,
                 serial_cb=None):
        """
        binary    — path to compiled sketch binary
        pin_map   — {arduino_pin_number: bus_net_name}
        serial_cb — callable(text: str) invoked for every Serial.print/println;
                    if None, output goes to stdout
        """
        self.binary    = binary
        self.pin_map   = pin_map
        self.v_supply  = v_supply
        self._serial_cb = serial_cb
        self._proc: subprocess.Popen | None = None
        self._bus:    SimBus    | None = None
        self._runner: SimRunner | None = None
        # LEDC channel state (populated at runtime by LEDC_SETUP / LEDC_ATTACH)
        self._ledc_resolution: dict[int, int] = {}  # channel → resolution bits
        self._ledc_pin:        dict[int, int] = {}  # channel → pin number
        # Serial receive buffer — bytes pushed from GUI, consumed by SER_AVAIL/SER_READ
        self._serial_in_buf:  deque[int]     = deque()
        self._serial_in_lock: threading.Lock = threading.Lock()

    def inject_serial(self, text: str):
        """Thread-safe — push text (+ newline) into the firmware's Serial receive buffer."""
        data = (text + "\n").encode("utf-8")
        with self._serial_in_lock:
            self._serial_in_buf.extend(data)

    def attach(self, bus, runner):
        self._bus    = bus
        self._runner = runner

    # ─────────────────────────────────────────── low-level IPC ───────────────

    def _send(self, msg: str):
        self._proc.stdin.write(msg + "\n")
        self._proc.stdin.flush()

    def _recv(self) -> str:
        line = self._proc.stdout.readline()
        return line.rstrip("\n")

    # ─────────────────────────────────────────── op dispatch ─────────────────

    def _dispatch(self, line: str):
        """
        Handle one op line (everything except DELAY and READY).
        Sends the appropriate response back to the C++ process.
        """
        op, _, rest = line.partition(" ")

        if op == "PM":
            pin_s, _, mode_s = rest.partition(" ")
            pin  = int(pin_s)
            mode = int(mode_s) if mode_s.strip() else 1   # default OUTPUT
            net  = self.pin_map.get(pin)
            if net and self._bus:
                ns = self._bus.gpio.net(net)
                if mode == 2:    # INPUT_PULLUP
                    ns._pull = self.v_supply
                elif mode == 3:  # INPUT_PULLDOWN
                    ns._pull = 0.0
                else:            # INPUT (0) or OUTPUT (1)
                    ns._pull = None
            self._send("OK")

        elif op == "DW":
            pin_s, _, val_s = rest.partition(" ")
            pin, val = int(pin_s), int(val_s)
            net = self.pin_map.get(pin)
            if net and self._bus:
                self._bus.gpio.drive(net, "cpp_fw", self.v_supply if val else 0.0)
            self._send("OK")

        elif op == "DR":
            pin = int(rest)
            net = self.pin_map.get(pin)
            val = 0
            if net and self._bus:
                val = self._bus.gpio.digital(net)
            self._send(str(val))

        elif op == "AR":
            pin = int(rest)
            net = self.pin_map.get(pin)
            val = 0
            if net and self._bus:
                v = self._bus.gpio.voltage(net)
                val = adc_convert(v, self.v_supply, bits=12)
            self._send(str(val))

        elif op == "AW":
            pin_s, _, val_s = rest.partition(" ")
            pin, val = int(pin_s), int(val_s)
            net = self.pin_map.get(pin)
            if net and self._bus:
                self._bus.gpio.drive(net, "cpp_fw", (val / 255.0) * self.v_supply)
            self._send("OK")

        elif op == "LEDC_SETUP":
            parts = rest.split()
            channel    = int(parts[0])
            # parts[1] is freq — not relevant for voltage-domain simulation
            resolution = int(parts[2])
            self._ledc_resolution[channel] = resolution
            self._send("OK")

        elif op == "LEDC_ATTACH":
            pin_s, _, ch_s = rest.partition(" ")
            self._ledc_pin[int(ch_s)] = int(pin_s)
            self._send("OK")

        elif op == "LEDC_WRITE":
            ch_s, _, duty_s = rest.partition(" ")
            channel, duty = int(ch_s), int(duty_s)
            pin = self._ledc_pin.get(channel)
            net = self.pin_map.get(pin) if pin is not None else None
            if net and self._bus:
                resolution = self._ledc_resolution.get(channel, 8)
                max_duty   = (1 << resolution) - 1
                voltage    = (duty / max_duty) * self.v_supply
                self._bus.gpio.drive(net, "cpp_fw", voltage)
            self._send("OK")

        elif op == "LEDC_DETACH":
            pin = int(rest)
            for ch, p in list(self._ledc_pin.items()):
                if p == pin:
                    del self._ledc_pin[ch]
            net = self.pin_map.get(pin)
            if net and self._bus:
                self._bus.gpio.release(net, "cpp_fw")
            self._send("OK")

        elif op == "SER_AVAIL":
            with self._serial_in_lock:
                self._send(str(len(self._serial_in_buf)))

        elif op == "SER_READ":
            with self._serial_in_lock:
                byte = self._serial_in_buf.popleft() if self._serial_in_buf else -1
            self._send(str(byte))

        elif op == "I2CW":
            # I2CW <addr> <hexbytes> — Wire write transaction.
            # First byte is the register pointer; the rest is the payload.
            addr_s, _, hex_s = rest.partition(" ")
            addr = int(addr_s)
            payload = bytes.fromhex(hex_s.strip()) if hex_s.strip() else b""
            status = 2   # NAK (no such device)
            if self._bus is not None:
                reg  = payload[0] if payload else 0
                data = payload[1:] if len(payload) > 1 else b""
                status = 0 if self._bus.i2c_write(addr, reg, data) else 2
            self._send(str(status))

        elif op == "I2CR":
            # I2CR <addr> <len> — Wire requestFrom; reads from the device's
            # current register pointer (set by the preceding I2CW).
            addr_s, _, len_s = rest.partition(" ")
            addr, length = int(addr_s), int(len_s)
            data = b""
            if self._bus is not None and addr in self._bus.i2c._devices:
                data = self._bus.i2c_read(addr, 0, length)
            self._send(data.hex().upper())

        elif op == "MILLIS":
            t = int(self._runner.elapsed_ms) if self._runner else 0
            self._send(str(t))

        elif op == "SER":
            if self._serial_cb:
                self._serial_cb(rest)
            else:
                print(rest, end="", flush=True)
            self._send("OK")

        elif op == "SERLN":
            text = rest + "\n"
            if self._serial_cb:
                self._serial_cb(text)
            else:
                print(rest, flush=True)
            self._send("OK")

    def _read_until_delay(self) -> float:
        """
        Read and dispatch ops until the next DELAY message.
        Returns the delay amount in ms WITHOUT yet sending OK — the caller
        must call _send("OK") after advancing the simulation.
        """
        while True:
            line = self._recv()
            if not line:
                return 0.0
            op, _, rest = line.partition(" ")
            if op == "DELAY":
                return float(rest) if rest else 0.0
            self._dispatch(line)

    # ─────────────────────────────────────────── lifecycle ───────────────────

    def start(self):
        """
        Spawn the binary and run setup() to completion.
        Handles any API calls (including delay()) made during setup().
        """
        self._proc = subprocess.Popen(
            [self.binary],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # Read until "READY" (emitted by sim_main.cpp after setup() returns)
        while True:
            line = self._recv()
            if line == "READY":
                break
            op, _, rest = line.partition(" ")
            if op == "DELAY":
                # setup() called delay() — advance simulation accordingly
                ms = float(rest) if rest else 0.0
                if self._runner:
                    self._runner.run(duration_ms=ms)
                self._send("OK")
            else:
                self._dispatch(line)

    def run(self, duration_ms: float):
        """
        Run the sketch for approximately duration_ms of simulated time.

        Time advances naturally through the sketch's delay() calls.  Each
        delay() triggers a simulation advancement; other nodes (LEDs, sensors,
        physics) tick during that time.  The loop exits once at least
        duration_ms has been consumed.
        """
        remaining = duration_ms
        while remaining > 0:
            delay_ms = self._read_until_delay()
            if delay_ms <= 0:
                break
            # Advance the rest of the simulation (physics, LED nodes, etc.)
            if self._runner:
                self._runner.run(duration_ms=delay_ms)
            # Unblock the C++ so it continues from after delay()
            self._send("OK")
            remaining -= delay_ms

    def stop(self):
        """Terminate the firmware subprocess."""
        if self._proc:
            self._proc.terminate()
            self._proc.wait()
            self._proc = None
