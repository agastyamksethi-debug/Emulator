from __future__ import annotations
import os
import sys
import time

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
    QStatusBar, QLabel, QFileDialog, QMenuBar, QMenu, QPushButton, QFrame,
)
from PyQt6.QtGui import QColor, QPalette, QFont, QAction
from PyQt6.QtCore import Qt, QThread, pyqtSignal, pyqtSlot

from gui.panels.editor_panel   import EditorPanel
from gui.panels.terminal_panel import TerminalPanel
from gui.panels.serial_panel   import SerialPanel
from gui.panels.problems_panel import ProblemsPanel
from gui.rw_canvas             import RWCanvas


# ── Simulation worker ─────────────────────────────────────────────────────────

class SimWorker(QThread):
    log          = pyqtSignal(str)
    info         = pyqtSignal(str)
    warn         = pyqtSignal(str)
    error        = pyqtSignal(str)
    serial_out   = pyqtSignal(str)
    node_ready   = pyqtSignal(str, object)
    led_update   = pyqtSignal(str, bool, float)
    sensor_update = pyqtSignal(str, int, float)   # ref, adc value, light 0..1
    time_advance = pyqtSignal(float)
    finished     = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._sketch:  str | None  = None
        self._circuit: dict | None = None
        self._stop     = False
        self._fw       = None   # CppFirmware instance while running
        self._runner   = None   # SimRunner instance while running

    def configure(self, sketch_path: str, circuit: dict):
        self._sketch  = sketch_path
        self._circuit = circuit

    def push_serial_in(self, text: str):
        """Thread-safe: inject text into the running firmware's Serial.read() buffer."""
        if self._fw is not None:
            self._fw.inject_serial(text)

    def push_light(self, ref: str, level: float, wavelength: int = 0):
        """Thread-safe: feed rw_bus light into a sensor node so loss nodes apply."""
        runner = self._runner
        if runner is not None:
            node = runner.node(ref)
            if node is not None and hasattr(node, "set_light"):
                node.set_light(level, wavelength)

    def stop(self):
        self._stop   = True
        self._fw     = None
        self._runner = None

    def run(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if root not in sys.path:
            sys.path.insert(0, root)

        try:
            from core.cpp_runtime import compile_sketch, CppFirmware
            from core.runner      import SimRunner
            from core.circuit     import to_netlist, find_mcu, mcu_pinmap

            import parts as _parts, os as _os
            _parts_dir = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                       "..", "parts")
            for _entry in _os.scandir(_parts_dir):
                if (_entry.is_dir()
                        and _os.path.exists(_os.path.join(_entry.path, "model.py"))):
                    try:
                        _parts.load_part(_entry.name)
                    except Exception:
                        pass

            self.info.emit(f"Compiling  {os.path.basename(self._sketch)} …")
            binary = compile_sketch(self._sketch)
            self.info.emit("✓  Binary ready")

            circuit = self._circuit
            netlist = to_netlist(circuit)

            runner = SimRunner(
                v_supply  = max(circuit.get("power", {}).values(), default=3.3),
                ambient_c = 25.0,
            )
            runner._netlist = netlist
            self._runner = runner
            runner.bus.load_netlist(netlist)

            for net, v in circuit.get("power", {}).items():
                runner.bus.gpio.drive(net, "_pwr", float(v))

            runner._auto_instantiate()

            _nodes_list = list(runner.bus._nodes.values())
            runner.physics.load(_nodes_list, netlist)

            for _ref, _node in runner.bus._nodes.items():
                self.node_ready.emit(_ref, _node)

            mcu_ref = find_mcu(circuit)
            pin_map = mcu_pinmap(circuit, mcu_ref) if mcu_ref else {}
            v_sup   = circuit.get("power", {}).get("3V3",
                      circuit.get("power", {}).get("5V", 3.3))

            fw = CppFirmware(
                binary,
                pin_map   = pin_map,
                v_supply  = v_sup,
                serial_cb = lambda txt: self.serial_out.emit(txt),
            )
            fw.attach(runner.bus, runner)
            self._fw = fw

            self.info.emit("▶  Running …")
            fw.start()

            _led_prev: dict[str, tuple[bool, float]] = {}

            # Pace the sim to wall-clock so it can't out-run the GUI.  Without
            # this, runner.run() returns far faster than the simulated delay and
            # the loop floods the monitor/plotter with output until the event
            # queue overwhelms memory.
            _t0 = time.monotonic()
            _sim_s = 0.0

            while not self._stop:
                delay_ms = fw._read_until_delay()
                if delay_ms <= 0:
                    break
                runner.run(duration_ms=delay_ms)

                # real-time pacing: hold the firmware in its delay() until
                # wall-clock catches up to simulated time
                _sim_s += delay_ms / 1000.0
                _lag = (_t0 + _sim_s) - time.monotonic()
                if _lag > 0:
                    time.sleep(min(_lag, 0.25))

                fw._send("OK")
                self.time_advance.emit(delay_ms)

                for _ref, _node in runner.bus._nodes.items():
                    if hasattr(_node, "on") and hasattr(_node, "brightness_pct"):
                        _on = bool(_node.on)
                        _br = round(float(_node.brightness_pct) / 100.0, 3)
                        if _led_prev.get(_ref) != (_on, _br):
                            _led_prev[_ref] = (_on, _br)
                            self.led_update.emit(_ref, _on, _br)
                    elif hasattr(_node, "v_out") and hasattr(_node, "light"):
                        _adc = max(0, min(4095, int(_node.v_out / v_sup * 4095)))
                        self.sensor_update.emit(_ref, _adc, float(_node.light))

            fw.stop()
            self._fw = None
            if not self._stop:
                self.info.emit("■  Simulation complete")
            else:
                self.warn.emit("■  Stopped by user")

        except Exception as exc:
            self.error.emit(str(exc))
        finally:
            self._runner = None
            self.finished.emit()


# ── VS Code-style status bar ──────────────────────────────────────────────────

_SB_BASE = (
    "QPushButton {"
    "  background:transparent; color:#657B83; border:none;"
    "  font-size:11px; padding:0 8px; min-height:24px;"
    "}"
    "QPushButton:hover { background:#FDF6E3; }"
)
_SB_ACTIVE = (
    "QPushButton {"
    "  background:transparent; color:#CB4B16; border:none;"
    "  border-bottom:2px solid #CB4B16;"
    "  font-size:11px; padding:0 8px; min-height:24px;"
    "}"
    "QPushButton:hover { background:#FDF6E3; }"
)


class _VsStatusBar(QStatusBar):
    sketch_open_req = pyqtSignal()
    monitor_toggled = pyqtSignal()
    plotter_toggled = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSizeGripEnabled(False)
        self.setFixedHeight(24)
        self.setStyleSheet(
            "QStatusBar { background:#EEE8D5; border-top:1px solid #93A1A1; padding:0; }"
            "QStatusBar::item { border:none; }"
        )
        self._errors   = 0
        self._warnings = 0
        self._build()

    def _build(self):
        container = QWidget()
        hbox = QHBoxLayout(container)
        hbox.setContentsMargins(4, 0, 4, 0)
        hbox.setSpacing(0)

        # sketch indicator (left-most)
        self._sketch_btn = QPushButton("◈  No sketch")
        self._sketch_btn.setStyleSheet(_SB_BASE)
        self._sketch_btn.clicked.connect(self.sketch_open_req)
        hbox.addWidget(self._sketch_btn)

        hbox.addWidget(self._sep())

        # run status dot
        self._run_btn = QPushButton("●  Ready")
        self._run_btn.setEnabled(False)
        self._run_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#859900; border:none;"
            "  font-size:11px; padding:0 8px; min-height:24px; }"
        )
        hbox.addWidget(self._run_btn)

        hbox.addStretch()

        # error / warning counts
        self._err_btn = QPushButton("⊗  0")
        self._err_btn.setStyleSheet(_SB_BASE)
        self._err_btn.setEnabled(False)
        hbox.addWidget(self._err_btn)

        self._warn_btn = QPushButton("⚠  0")
        self._warn_btn.setStyleSheet(_SB_BASE)
        self._warn_btn.setEnabled(False)
        hbox.addWidget(self._warn_btn)

        hbox.addWidget(self._sep())

        # serial monitor / plotter toggles (right side)
        self._mon_btn  = QPushButton("▤  Monitor")
        self._plot_btn = QPushButton("∿  Plotter")
        self._mon_btn.setStyleSheet(_SB_BASE)
        self._plot_btn.setStyleSheet(_SB_BASE)
        self._mon_btn.clicked.connect(self.monitor_toggled)
        self._plot_btn.clicked.connect(self.plotter_toggled)
        hbox.addWidget(self._mon_btn)
        hbox.addWidget(self._plot_btn)

        self.addWidget(container, 1)

    def _sep(self) -> QFrame:
        f = QFrame()
        f.setFrameShape(QFrame.Shape.VLine)
        f.setFixedSize(1, 14)
        f.setStyleSheet("QFrame { background:#93A1A1; margin:5px 4px; }")
        return f

    # ── public update API ─────────────────────────────────────────────────────

    def set_sketch(self, name: str):
        self._sketch_btn.setText(f"◈  {name}")

    def set_state(self, state: str):
        if state == "running":
            txt, clr = "●  Running", "#CB4B16"
        elif state == "error":
            txt, clr = "✕  Error",   "#DC322F"
        elif state == "stopping":
            txt, clr = "●  Stopping…", "#B58900"
        else:
            txt, clr = "●  Ready",   "#859900"
        self._run_btn.setText(txt)
        self._run_btn.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{clr}; border:none;"
            f"  font-size:11px; padding:0 8px; min-height:24px; }}"
        )

    def add_error(self):
        self._errors += 1
        self._err_btn.setText(f"⊗  {self._errors}")
        self._err_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#DC322F; border:none;"
            "  font-size:11px; padding:0 8px; min-height:24px; }"
        )

    def add_warning(self):
        self._warnings += 1
        self._warn_btn.setText(f"⚠  {self._warnings}")
        self._warn_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#B58900; border:none;"
            "  font-size:11px; padding:0 8px; min-height:24px; }"
        )

    def reset_counts(self):
        self._errors   = 0
        self._warnings = 0
        self._err_btn.setText("⊗  0")
        self._warn_btn.setText("⚠  0")
        self._err_btn.setStyleSheet(_SB_BASE)
        self._warn_btn.setStyleSheet(_SB_BASE)

    def set_monitor_active(self, active: bool):
        self._mon_btn.setStyleSheet(_SB_ACTIVE if active else _SB_BASE)

    def set_plotter_active(self, active: bool):
        self._plot_btn.setStyleSheet(_SB_ACTIVE if active else _SB_BASE)


# ── Main window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Emulator")
        self.resize(1520, 900)

        self._circuit:    dict | None = None
        self._worker      = SimWorker()
        self._had_error   = False
        self._analyzer_cache = None      # persistent characterization cache

        self._apply_palette()
        self._build_menu()
        self._build_ui()
        self._wire()

    # ── styling ───────────────────────────────────────────────────────────────

    def _apply_palette(self):
        p = QPalette()
        p.setColor(QPalette.ColorRole.Window,          QColor("#FDF6E3"))
        p.setColor(QPalette.ColorRole.WindowText,      QColor("#657B83"))
        p.setColor(QPalette.ColorRole.Base,            QColor("#EEE8D5"))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor("#FDF6E3"))
        p.setColor(QPalette.ColorRole.Text,            QColor("#657B83"))
        p.setColor(QPalette.ColorRole.Button,          QColor("#EEE8D5"))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor("#657B83"))
        p.setColor(QPalette.ColorRole.Highlight,       QColor("#268BD2"))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor("#FDF6E3"))
        self.setPalette(p)
        self.setFont(QFont("SF Pro Text,Segoe UI,system-ui", 11))

    # ── menu bar ──────────────────────────────────────────────────────────────

    def _build_menu(self):
        mb = QMenuBar(self)
        mb.setStyleSheet(
            "QMenuBar { background:#EEE8D5; color:#657B83; }"
            "QMenuBar::item:selected { background:#FDF6E3; }"
            "QMenu { background:#FDF6E3; color:#657B83; border:1px solid #93A1A1; }"
            "QMenu::item:selected { background:#EAE4CE; }"
        )
        file_menu = QMenu("File", mb)
        act_open_ino     = QAction("Open Sketch…",  self)
        act_open_circuit = QAction("Load Circuit…", self)
        act_open_ino.triggered.connect(self._open_sketch)
        act_open_circuit.triggered.connect(self._open_circuit)
        file_menu.addAction(act_open_ino)
        file_menu.addAction(act_open_circuit)
        mb.addMenu(file_menu)

        self._build_sim_menu(mb)
        self.setMenuBar(mb)

    def _build_sim_menu(self, mb: QMenuBar):
        """Simulation-fidelity config menu — choose Basic vs Advanced per domain."""
        from core.fidelity import CONFIG, Level

        sim_menu = QMenu("Simulation", mb)

        self._act_rw = QAction("Real-World Physics — Advanced", self, checkable=True)
        self._act_rw.setChecked(CONFIG.real_world == Level.ADVANCED)
        self._act_rw.toggled.connect(
            lambda on: self._set_fidelity("real_world", on))

        self._act_adc = QAction("ADC — Advanced", self, checkable=True)
        self._act_adc.setChecked(CONFIG.adc == Level.ADVANCED)
        self._act_adc.toggled.connect(
            lambda on: self._set_fidelity("adc", on))

        self._act_digital = QAction("Digital — Advanced", self, checkable=True)
        self._act_digital.setChecked(CONFIG.digital == Level.ADVANCED)
        self._act_digital.setEnabled(False)   # digital advanced not implemented
        self._act_digital.setToolTip("Digital logic always runs the basic model")

        self._act_auto = QAction("Auto (by circuit complexity)", self, checkable=True)
        self._act_auto.setChecked(CONFIG.auto)
        self._act_auto.toggled.connect(self._on_auto_toggle)

        sim_menu.addAction(self._act_rw)
        sim_menu.addAction(self._act_adc)
        sim_menu.addAction(self._act_digital)
        sim_menu.addSeparator()
        sim_menu.addAction(self._act_auto)
        mb.addMenu(sim_menu)

    def _set_fidelity(self, domain: str, advanced: bool):
        from core.fidelity import CONFIG, Level
        setattr(CONFIG, domain, Level.ADVANCED if advanced else Level.BASIC)
        self.rw_canvas.refresh_fidelity()
        tier = "Advanced" if advanced else "Basic"
        self.terminal.info(f"Fidelity · {domain} → {tier}")

    def _on_auto_toggle(self, on: bool):
        from core.fidelity import CONFIG, auto_select, Level
        CONFIG.auto = on
        # manual toggles are disabled while auto drives the tiers
        self._act_rw.setEnabled(not on)
        self._act_adc.setEnabled(not on)
        if on:
            auto_select(self._circuit)
            self._act_rw.setChecked(CONFIG.real_world == Level.ADVANCED)
            self._act_adc.setChecked(CONFIG.adc == Level.ADVANCED)
            self.rw_canvas.refresh_fidelity()
            self.terminal.info(f"Fidelity · auto → {CONFIG}")

    # ── layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.editor    = EditorPanel()
        self.rw_canvas = RWCanvas()
        self.terminal  = TerminalPanel()
        self.serial    = SerialPanel()
        self.problems  = ProblemsPanel()
        self.problems.locate.connect(self.rw_canvas.focus_ref)

        h_ss = "QSplitter::handle { background:#BEC5C5; height:1px; }"
        v_ss = "QSplitter::handle { background:#BEC5C5; width:1px; }"

        left_split = QSplitter(Qt.Orientation.Vertical)
        left_split.setStyleSheet(h_ss)
        left_split.addWidget(self.editor)
        left_split.addWidget(self.terminal)
        left_split.addWidget(self.problems)
        left_split.setSizes([520, 150, 150])

        right_split = QSplitter(Qt.Orientation.Vertical)
        right_split.setStyleSheet(h_ss)
        right_split.addWidget(self.rw_canvas)
        right_split.addWidget(self.serial)
        right_split.setSizes([560, 240])

        h_split = QSplitter(Qt.Orientation.Horizontal)
        h_split.setStyleSheet(v_ss)
        h_split.addWidget(left_split)
        h_split.addWidget(right_split)
        h_split.setSizes([720, 800])

        root.addWidget(h_split)

        # VS Code-style status bar
        self._sb = _VsStatusBar(self)
        self.setStatusBar(self._sb)

    # ── signal wiring ─────────────────────────────────────────────────────────

    def _wire(self):
        self.editor.run_requested.connect(self._on_run)
        self.editor.stop_requested.connect(self._on_stop)

        self._worker.info.connect(self.terminal.info)
        self._worker.warn.connect(self._on_worker_warn)
        self._worker.error.connect(self._on_worker_error)
        self._worker.log.connect(self.terminal.writeln)
        self._worker.serial_out.connect(self.serial.append)
        self._worker.node_ready.connect(self.rw_canvas.on_node_ready)
        self._worker.led_update.connect(self.rw_canvas.update_led)
        self._worker.sensor_update.connect(self.rw_canvas.update_sensor)
        self._worker.time_advance.connect(self.serial.advance_time)
        self._worker.finished.connect(self._on_worker_finished)

        self._worker.serial_out.connect(lambda _: self.serial.expand())
        self.serial.send_requested.connect(self._worker.push_serial_in)
        self.rw_canvas.ldr_light_changed.connect(self._worker.push_light)

        self._sb.sketch_open_req.connect(self._open_sketch)
        self._sb.monitor_toggled.connect(self._on_monitor_toggle)
        self._sb.plotter_toggled.connect(self._on_plotter_toggle)

    # ── slots ─────────────────────────────────────────────────────────────────

    @pyqtSlot(str)
    def _on_run(self, sketch_path: str):
        if self._circuit is None:
            self.terminal.warn("No circuit loaded — File → Load Circuit…")
            self.editor.set_running(False)
            return
        if self._worker.isRunning():
            return

        self._had_error = False
        self.terminal.clear()
        self.serial.reset_plot()
        self._sb.reset_counts()
        self._run_analyzer()          # ERC pass before the firmware runs
        self._sb.set_state("running")

        self._worker = SimWorker()
        self._worker.info.connect(self.terminal.info)
        self._worker.warn.connect(self._on_worker_warn)
        self._worker.error.connect(self._on_worker_error)
        self._worker.log.connect(self.terminal.writeln)
        self._worker.serial_out.connect(self.serial.append)
        self._worker.node_ready.connect(self.rw_canvas.on_node_ready)
        self._worker.led_update.connect(self.rw_canvas.update_led)
        self._worker.sensor_update.connect(self.rw_canvas.update_sensor)
        self._worker.time_advance.connect(self.serial.advance_time)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.serial_out.connect(lambda _: self.serial.expand())
        self.serial.send_requested.connect(self._worker.push_serial_in)
        self.rw_canvas.ldr_light_changed.connect(self._worker.push_light)

        self._worker.configure(sketch_path, self._circuit)
        self._worker.start()

    @pyqtSlot()
    def _on_stop(self):
        if self._worker.isRunning():
            self._worker.stop()
        self._sb.set_state("stopping")

    def _on_worker_error(self, msg: str):
        self.terminal.error(msg)
        self._had_error = True
        self._sb.add_error()

    def _on_worker_warn(self, msg: str):
        self.terminal.warn(msg)
        self._sb.add_warning()

    def _on_worker_finished(self):
        self.editor.set_running(False)
        self._sb.set_state("error" if self._had_error else "ready")

    def _on_monitor_toggle(self):
        is_on = (not self.serial._collapsed
                 and self.serial._stack.currentIndex() == 0)
        if is_on:
            self.serial._toggle_collapse()
            self._sb.set_monitor_active(False)
        else:
            self.serial.show_monitor()
            self._sb.set_monitor_active(True)
            self._sb.set_plotter_active(False)

    def _on_plotter_toggle(self):
        is_on = (not self.serial._collapsed
                 and self.serial._stack.currentIndex() == 1)
        if is_on:
            self.serial._toggle_collapse()
            self._sb.set_plotter_active(False)
        else:
            self.serial.show_plotter()
            self._sb.set_plotter_active(True)
            self._sb.set_monitor_active(False)

    def _open_sketch(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Sketch", "",
            "Arduino Sketches (*.ino *.cpp);;All Files (*)")
        if path:
            self.editor.load_file(path)
            name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
            self._sb.set_sketch(name)

    def _open_circuit(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Load Circuit", "",
            "Circuit JSON (*.json);;All Files (*)")
        if path:
            self.load_circuit_file(path)

    # ── public API ────────────────────────────────────────────────────────────

    def load_circuit(self, circuit: dict):
        self._circuit = circuit
        self.rw_canvas.load_circuit(circuit)
        self._apply_auto_fidelity()
        self._run_analyzer()
        self.terminal.info("Circuit received from KiCad")

    def _run_analyzer(self):
        """Run the ERC / planner pass and surface results in Problems + overlays."""
        if self._circuit is None:
            return
        from core.analyzer import analyze, CharacterizationCache
        from core.fidelity import CONFIG
        if self._analyzer_cache is None:
            path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                ".sim_cache", "characterization.json")
            self._analyzer_cache = CharacterizationCache(path=path)
        try:
            plan = analyze(self._circuit, cache=self._analyzer_cache,
                           advanced=CONFIG.is_advanced("real_world"))
        except Exception as exc:
            self.terminal.error(f"Analyzer failed: {exc}")
            return
        self._analyzer_cache.flush()
        self.problems.set_diagnostics(plan.diagnostics)
        self.rw_canvas.set_diagnostics(plan.diagnostics)
        n_e, n_w = len(plan.errors()), len(plan.warnings())
        if n_e or n_w:
            self.terminal.warn(f"ERC: {n_e} error(s), {n_w} warning(s) — see Problems")
        else:
            self.terminal.info("ERC: no problems detected")

    def _apply_auto_fidelity(self):
        """If auto mode is on, re-pick fidelity tiers from the loaded circuit."""
        from core.fidelity import CONFIG, auto_select, Level
        if CONFIG.auto:
            auto_select(self._circuit)
            self._act_rw.setChecked(CONFIG.real_world == Level.ADVANCED)
            self._act_adc.setChecked(CONFIG.adc == Level.ADVANCED)
            self.rw_canvas.refresh_fidelity()

    def load_sketch(self, path: str):
        self.editor.load_file(path)
        name = os.path.basename(os.path.dirname(path)) + "/" + os.path.basename(path)
        self._sb.set_sketch(name)

    def load_circuit_file(self, path: str):
        import json
        try:
            with open(path) as f:
                self._circuit = json.load(f)
            self.rw_canvas.load_circuit(self._circuit)
            self._apply_auto_fidelity()
            self._run_analyzer()
            self.terminal.info(f"Circuit loaded: {os.path.basename(path)}")
        except Exception as e:
            self.terminal.error(f"Circuit load failed: {e}")
