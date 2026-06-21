#!/usr/bin/env python3
"""
Emulator — Developer Window

Usage:
    python run_gui.py
    python run_gui.py path/to/sketch.ino
    python run_gui.py path/to/sketch.ino --circuit path/to/circuit.json

If no --circuit flag is given the app looks for circuit.json in the same
directory as the sketch and auto-loads it.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Stabilise the embedded Chromium (Monaco editor) renderer on macOS — the GPU
# compositor can segfault (QtWebEngineCore EXC_BAD_ACCESS).  Must be set before
# QtWebEngine is imported.  Override by exporting QTWEBENGINE_CHROMIUM_FLAGS.
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS",
                      "--disable-gpu --disable-gpu-compositing")

from PyQt6.QtWidgets import QApplication
from gui.main_window import MainWindow


def _parse_args():
    args = sys.argv[1:]
    sketch  = None
    circuit = None
    i = 0
    while i < len(args):
        if args[i] == "--circuit" and i + 1 < len(args):
            circuit = os.path.abspath(args[i + 1])
            i += 2
        elif not args[i].startswith("--") and sketch is None:
            sketch = os.path.abspath(args[i])
            i += 1
        else:
            i += 1
    return sketch, circuit


def _install_excepthook():
    """Log uncaught exceptions (incl. those raised inside Qt slots) to a file.

    PyQt6 aborts the process when a slot raises; capturing the traceback here
    makes those crashes diagnosable instead of a silent quit.
    """
    import traceback, datetime
    log_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "crash.log")

    def hook(exc_type, exc, tb):
        msg = "".join(traceback.format_exception(exc_type, exc, tb))
        stamp = datetime.datetime.now().isoformat(timespec="seconds")
        try:
            with open(log_path, "a") as f:
                f.write(f"\n===== {stamp} =====\n{msg}\n")
        except OSError:
            pass
        sys.stderr.write(msg)

    sys.excepthook = hook


def main():
    _install_excepthook()
    app = QApplication(sys.argv)
    app.setApplicationName("Emulator")

    win = MainWindow()

    sketch_path, circuit_path = _parse_args()

    if sketch_path and os.path.isfile(sketch_path):
        win.load_sketch(sketch_path)

        # auto-detect circuit.json sitting next to the sketch
        if circuit_path is None:
            auto = os.path.join(os.path.dirname(sketch_path), "circuit.json")
            if os.path.isfile(auto):
                circuit_path = auto

    if circuit_path and os.path.isfile(circuit_path):
        win.load_circuit_file(circuit_path)

    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
