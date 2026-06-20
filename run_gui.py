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


def main():
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
