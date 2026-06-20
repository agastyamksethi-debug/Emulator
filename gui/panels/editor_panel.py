from __future__ import annotations
import os

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QFileDialog, QFrame,
)
from PyQt6.QtCore import pyqtSignal

from .monaco_widget import MonacoWidget


# ── button helpers ─────────────────────────────────────────────────────────────

def _icon_btn(symbol: str, tooltip: str = "") -> QPushButton:
    """Small transparent icon button — VS Code style."""
    b = QPushButton(symbol)
    b.setFixedSize(28, 28)
    b.setToolTip(tooltip)
    b.setStyleSheet(
        "QPushButton { background:transparent; color:#93A1A1; border:none;"
        " border-radius:4px; font-size:15px; }"
        "QPushButton:hover { background:#EEE8D5; color:#657B83; }"
        "QPushButton:disabled { color:#BDC5C5; }"
    )
    return b


def _action_btn(label: str, bg: str, hover: str, fg: str = "#fff") -> QPushButton:
    """Filled coloured action button — for Run / Stop."""
    b = QPushButton(label)
    b.setFixedHeight(24)
    b.setStyleSheet(
        f"QPushButton {{ background:{bg}; color:{fg}; border:none;"
        f" border-radius:3px; padding:0 12px; font-size:11px; font-weight:500; }}"
        f"QPushButton:hover {{ background:{hover}; }}"
        f"QPushButton:disabled {{ background:#EEE8D5; color:#BDC5C5; }}"
    )
    return b


def _sep() -> QFrame:
    """Thin vertical separator between button groups."""
    f = QFrame()
    f.setFrameShape(QFrame.Shape.VLine)
    f.setFixedWidth(1)
    f.setFixedHeight(16)
    f.setStyleSheet("background:#BEC5C5; border:none;")
    return f


# ── editor panel ───────────────────────────────────────────────────────────────

class EditorPanel(QWidget):
    run_requested  = pyqtSignal(str)
    stop_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path: str | None = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── toolbar ────────────────────────────────────────────────────────────
        toolbar = QWidget()
        toolbar.setFixedHeight(38)
        toolbar.setStyleSheet(
            "background:#EEE8D5; border-bottom:1px solid #93A1A1;"
        )
        hbox = QHBoxLayout(toolbar)
        hbox.setContentsMargins(8, 0, 8, 0)
        hbox.setSpacing(4)

        # filename tab label
        self._file_label = QLabel("No file open")
        self._file_label.setStyleSheet("color:#93A1A1; font-size:11px; padding:0 6px;")
        hbox.addWidget(self._file_label)
        hbox.addStretch()

        # file actions (transparent icon-style)
        self._btn_open = _icon_btn("⊞", "Open sketch")
        self._btn_save = _icon_btn("↓",  "Save  (Ctrl+S)")
        hbox.addWidget(self._btn_open)
        hbox.addWidget(self._btn_save)

        hbox.addWidget(_sep())

        # run actions (filled coloured buttons)
        self._btn_run  = _action_btn("▶  Run",  "#CB4B16", "#A83B0F")
        self._btn_stop = _action_btn("■  Stop", "#586E75", "#4A5F6B")
        self._btn_stop.setEnabled(False)
        hbox.addWidget(self._btn_run)
        hbox.addWidget(self._btn_stop)

        root.addWidget(toolbar)

        # ── Monaco editor ──────────────────────────────────────────────────────
        self._editor = MonacoWidget()
        root.addWidget(self._editor)

        self._btn_open.clicked.connect(self._open)
        self._btn_save.clicked.connect(self._save)
        self._btn_run.clicked.connect(self._run)
        self._btn_stop.clicked.connect(self._stop)

    # ── public API ────────────────────────────────────────────────────────────

    def load_file(self, path: str):
        try:
            with open(path) as f:
                text = f.read()
            self._path = path
            self._editor.set_text(text)
            self._file_label.setText(os.path.basename(path))
            self._file_label.setStyleSheet("color:#586E75; font-size:11px; padding:0 6px;")
        except OSError as e:
            self._file_label.setText(f"Error: {e}")

    def set_running(self, running: bool):
        self._btn_run.setEnabled(not running)
        self._btn_stop.setEnabled(running)
        self._editor.set_read_only(running)

    # ── slots ─────────────────────────────────────────────────────────────────

    def _open(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Sketch", "",
            "Arduino Sketches (*.ino *.cpp);;All Files (*)")
        if path:
            self.load_file(path)

    def _save(self):
        if not self._path:
            path, _ = QFileDialog.getSaveFileName(
                self, "Save Sketch", "",
                "Arduino Sketch (*.ino);;C++ (*.cpp);;All Files (*)")
            if not path:
                return
            self._path = path
        self._editor.get_text(self._write_file)

    def _write_file(self, text: str):
        try:
            with open(self._path, "w") as f:
                f.write(text or "")
            self._file_label.setText(os.path.basename(self._path))
        except OSError as e:
            self._file_label.setText(f"Save error: {e}")

    def _run(self):
        if not self._path:
            self._open()
            if not self._path:
                return
        self._editor.get_text(self._save_then_run)

    def _save_then_run(self, text: str):
        self._write_file(text)
        self.set_running(True)
        self.run_requested.emit(self._path)

    def _stop(self):
        self.set_running(False)
        self.stop_requested.emit()
