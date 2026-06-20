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
import subprocess
from typing import TYPE_CHECKING

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
      C++ → Python:  PM DW DR AR AW DELAY MILLIS SER SERLN READY
      Python → C++:  OK  or  <integer>
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
                val = max(0, min(4095, int((v / self.v_supply) * 4095)))
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
