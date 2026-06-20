from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPlainTextEdit, QPushButton,
)
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor


class TerminalPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── header / tab bar ──────────────────────────────────────────────────
        self._header = QWidget()
        self._header.setFixedHeight(30)
        self._header.setStyleSheet(
            "background:#EEE8D5; border-top:1px solid #93A1A1;"
        )
        hbox = QHBoxLayout(self._header)
        hbox.setContentsMargins(0, 0, 6, 0)
        hbox.setSpacing(0)

        tab_lbl = QPushButton("TERMINAL")
        tab_lbl.setFixedHeight(30)
        tab_lbl.setStyleSheet(
            "QPushButton {"
            "  background:transparent; color:#586E75; border:none;"
            "  border-top:2px solid #CB4B16;"
            "  font-size:10px; padding:0 14px;"
            "  font-weight:600; letter-spacing:0.5px;"
            "}"
        )
        hbox.addWidget(tab_lbl)
        hbox.addStretch()

        self._collapse_btn = QPushButton("⌃")
        self._collapse_btn.setFixedSize(26, 26)
        self._collapse_btn.setToolTip("Collapse panel")
        self._collapse_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#93A1A1; border:none; font-size:13px; }"
            "QPushButton:hover { color:#657B83; }"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        hbox.addWidget(self._collapse_btn)
        layout.addWidget(self._header)

        # ── output area (plain — no dot grid) ────────────────────────────────
        self._out = QPlainTextEdit()
        self._out.setReadOnly(True)
        self._out.setFont(QFont("Menlo,Consolas,Courier New,monospace", 12))
        self._out.setStyleSheet(
            "QPlainTextEdit {"
            "  background:#FDF6E3;"        # Solarized base3 — lighter content vs base2 header
            "  color:#657B83;"
            "  border:none;"
            "  selection-background-color:#D4E5F7;"
            "}"
        )
        self._out.setMaximumBlockCount(4000)
        layout.addWidget(self._out)

    # ── collapse ──────────────────────────────────────────────────────────────

    _HEADER_H = 30

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._out.setVisible(not self._collapsed)
        self._collapse_btn.setText("⌄" if self._collapsed else "⌃")
        # constrain max-height so the QSplitter redistributes space correctly
        self.setMaximumHeight(self._HEADER_H if self._collapsed else 16_777_215)
        self.updateGeometry()

    def expand(self):
        if self._collapsed:
            self._toggle_collapse()   # restores max height inside

    # ── write helpers ─────────────────────────────────────────────────────────

    def write(self, text: str, color: str = "#657B83"):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor(color))
        cur = self._out.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(text, fmt)
        self._out.setTextCursor(cur)
        self._out.ensureCursorVisible()

    def writeln(self, text: str, color: str = "#657B83"):
        self.write(text + "\n", color)

    def error(self, text: str):
        self.writeln(text, "#B91C1C")

    def info(self, text: str):
        self.writeln(text, "#57534E")

    def warn(self, text: str):
        self.writeln(text, "#B45309")

    def clear(self):
        self._out.clear()

    def hide_header(self):
        self._header.hide()
