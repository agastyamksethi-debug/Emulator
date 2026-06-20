from __future__ import annotations
import re

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget,
    QPlainTextEdit, QPushButton, QLineEdit,
)
from PyQt6.QtGui import QFont, QColor, QTextCharFormat, QTextCursor
from PyQt6.QtCore import pyqtSignal
import pyqtgraph as pg


_PLOT_COLORS = ["#CB4B16", "#0369A1", "#059669", "#9333EA", "#DC2626", "#0891B2"]
_MAX_PTS = 10_000


class SerialPanel(QWidget):
    send_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._series:     dict[str, list]            = {}
        self._plot_items: dict[str, pg.PlotDataItem] = {}
        self._color_idx   = 0
        self._elapsed_ms: float = 0.0
        self._line_buf:   str   = ""
        self._collapsed   = False
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── internal tab bar ──────────────────────────────────────────────────
        bar = QWidget()
        bar.setFixedHeight(30)
        bar.setStyleSheet("background:#EEE8D5; border-top:1px solid #93A1A1;")
        hbox = QHBoxLayout(bar)
        hbox.setContentsMargins(0, 0, 6, 0)
        hbox.setSpacing(0)

        self._tabs: list[QPushButton] = []
        for idx, label in enumerate(["MONITOR", "PLOTTER"]):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setStyleSheet(
                "QPushButton {"
                "  background:transparent; color:#93A1A1; border:none;"
                "  border-top:2px solid transparent;"
                "  font-size:10px; padding:0 14px;"
                "  font-weight:600; letter-spacing:0.5px;"
                "}"
                "QPushButton:checked {"
                "  color:#586E75; border-top:2px solid #CB4B16;"
                "}"
                "QPushButton:hover:!checked { color:#657B83; }"
            )
            btn.clicked.connect(lambda _, i=idx: self._switch(i))
            hbox.addWidget(btn)
            self._tabs.append(btn)

        hbox.addStretch()

        self._collapse_btn = QPushButton("⌃")
        self._collapse_btn.setFixedSize(26, 26)
        self._collapse_btn.setToolTip("Collapse panel")
        self._collapse_btn.setStyleSheet(
            "QPushButton { background:transparent; color:#93A1A1; border:none; font-size:13px; }"
            "QPushButton:hover { color:#586E75; }"
        )
        self._collapse_btn.clicked.connect(self._toggle_collapse)
        hbox.addWidget(self._collapse_btn)
        layout.addWidget(bar)

        # ── stacked content ───────────────────────────────────────────────────
        self._stack = QStackedWidget()

        # ─ page 0: monitor ────────────────────────────────────────────────────
        mon_widget = QWidget()
        mon_layout = QVBoxLayout(mon_widget)
        mon_layout.setContentsMargins(0, 0, 0, 0)
        mon_layout.setSpacing(0)

        self._monitor = QPlainTextEdit()
        self._monitor.setReadOnly(True)
        self._monitor.setFont(QFont("Menlo,Consolas,Courier New,monospace", 12))
        self._monitor.setStyleSheet(
            "QPlainTextEdit {"
            "  background:#FDF6E3;"        # base3 content — lighter than base2 tab bar
            "  color:#657B83;"
            "  border:none;"
            "  selection-background-color:#D4E5F7;"
            "}"
        )
        self._monitor.setMaximumBlockCount(3000)
        mon_layout.addWidget(self._monitor)

        # send bar
        send_row = QHBoxLayout()
        send_row.setContentsMargins(6, 3, 6, 3)
        send_row.setSpacing(4)

        self._send_input = QLineEdit()
        self._send_input.setPlaceholderText("Send to serial…")
        self._send_input.setStyleSheet(
            "QLineEdit {"
            "  background:#F7F1E1; color:#657B83;"
            "  border:1px solid #93A1A1; border-radius:3px;"
            "  padding:3px 6px; font-size:11px;"
            "}"
            "QLineEdit:focus { border-color:#CB4B16; }"
        )
        self._send_input.returnPressed.connect(self._on_send)

        send_btn = QPushButton("Send")
        send_btn.setFixedWidth(52)
        send_btn.setStyleSheet(
            "QPushButton { background:#CB4B16; color:#fff; border:none;"
            " border-radius:3px; padding:4px; font-size:11px; }"
            "QPushButton:hover { background:#B45309; }"
        )
        send_btn.clicked.connect(self._on_send)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(48)
        clear_btn.setStyleSheet(
            "QPushButton { background:#EEE8D5; color:#93A1A1; border:none;"
            " border-radius:3px; padding:4px; font-size:11px; }"
            "QPushButton:hover { background:#93A1A1; color:#586E75; }"
        )
        clear_btn.clicked.connect(self._clear_monitor)

        send_row.addWidget(self._send_input)
        send_row.addWidget(send_btn)
        send_row.addWidget(clear_btn)
        mon_layout.addLayout(send_row)
        self._stack.addWidget(mon_widget)

        # ─ page 1: plotter ────────────────────────────────────────────────────
        plot_widget = QWidget()
        plot_layout = QVBoxLayout(plot_widget)
        plot_layout.setContentsMargins(0, 0, 0, 0)
        plot_layout.setSpacing(0)

        ptb = QHBoxLayout()
        ptb.setContentsMargins(6, 3, 6, 3)
        ptb.setSpacing(6)
        ptb.addStretch()

        self._btn_autoscroll = QPushButton("⟳ Live")
        self._btn_autoscroll.setCheckable(True)
        self._btn_autoscroll.setChecked(True)
        self._btn_autoscroll.setFixedHeight(22)
        self._btn_autoscroll.setStyleSheet(
            "QPushButton { background:#EEE8D5; color:#93A1A1; border:none;"
            " border-radius:3px; padding:0 8px; font-size:10px; }"
            "QPushButton:checked { background:#CB4B16; color:#fff; }"
            "QPushButton:hover { background:#93A1A1; color:#586E75; }"
        )
        ptb.addWidget(self._btn_autoscroll)

        ptb_widget = QWidget()
        ptb_widget.setFixedHeight(28)
        ptb_widget.setStyleSheet("background:#EEE8D5; border-bottom:1px solid #93A1A1;")
        ptb_widget.setLayout(ptb)
        plot_layout.addWidget(ptb_widget)

        pg.setConfigOption("background", "#FDF6E3")
        pg.setConfigOption("foreground", "#657B83")
        self._plot = pg.PlotWidget()
        self._plot.showGrid(x=True, y=True, alpha=0.2)
        self._plot.getAxis("bottom").setLabel("time (ms)")
        self._plot.addLegend(offset=(10, 10))
        self._plot.setStyleSheet("border:none;")
        self._plot.enableAutoRange(axis="y", enable=True)
        self._plot.setMouseEnabled(x=True, y=True)
        plot_layout.addWidget(self._plot)

        self._stack.addWidget(plot_widget)
        layout.addWidget(self._stack)

        self._plot.scene().sigMouseClicked.connect(self._on_plot_click)
        self._switch(0)

    # ── tab / collapse ────────────────────────────────────────────────────────

    def _switch(self, idx: int):
        if self._collapsed:
            self._collapsed = False
            self._stack.setVisible(True)
            self._collapse_btn.setText("⌃")
            self.setMaximumHeight(16_777_215)
            self.updateGeometry()
        self._stack.setCurrentIndex(idx)
        for i, btn in enumerate(self._tabs):
            btn.setChecked(i == idx)

    _BAR_H = 30

    def _toggle_collapse(self):
        self._collapsed = not self._collapsed
        self._stack.setVisible(not self._collapsed)
        self._collapse_btn.setText("⌄" if self._collapsed else "⌃")
        self.setMaximumHeight(self._BAR_H if self._collapsed else 16_777_215)
        self.updateGeometry()

    def show_monitor(self):
        self._switch(0)

    def show_plotter(self):
        self._switch(1)

    def hide_header(self):
        pass   # tabs are internal — nothing to hide externally

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_send(self):
        text = self._send_input.text().strip()
        if text:
            self.send_requested.emit(text)
            self._send_input.clear()

    def _clear_monitor(self):
        self._monitor.clear()

    def _on_plot_click(self, _ev):
        self._btn_autoscroll.setChecked(False)

    # ── public API ────────────────────────────────────────────────────────────

    def append(self, text: str):
        self._line_buf += text
        while "\n" in self._line_buf:
            line, _, self._line_buf = self._line_buf.partition("\n")
            line = line.rstrip("\r")
            if line:
                self._display_line(line)
                self._try_plot(line)

    def reset_plot(self):
        self._plot.clear()
        self._series.clear()
        self._plot_items.clear()
        self._color_idx  = 0
        self._elapsed_ms = 0.0
        self._line_buf   = ""
        self._plot.addLegend(offset=(10, 10))

    def advance_time(self, dt_ms: float):
        self._elapsed_ms += dt_ms

    # ── helpers ───────────────────────────────────────────────────────────────

    def _display_line(self, line: str):
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("#657B83"))
        cur = self._monitor.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        cur.insertText(line + "\n", fmt)
        self._monitor.setTextCursor(cur)
        self._monitor.ensureCursorVisible()

    def _try_plot(self, line: str):
        t = self._elapsed_ms
        pairs = re.findall(
            r'(\w+)\s*:\s*(-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)', line
        )
        if pairs:
            for label, val in pairs:
                self._push(label, t, float(val))
            return
        nums = re.findall(r'-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?', line)
        if len(nums) == 1:
            self._push("value", t, float(nums[0]))
        elif len(nums) > 1:
            for i, n in enumerate(nums):
                self._push(f"ch{i}", t, float(n))

    def _push(self, label: str, t: float, v: float):
        if label not in self._series:
            color = _PLOT_COLORS[self._color_idx % len(_PLOT_COLORS)]
            self._color_idx += 1
            self._series[label] = []
            pen = pg.mkPen(color=color, width=1.5)
            self._plot_items[label] = self._plot.plot(pen=pen, name=label)

        pts = self._series[label]
        pts.append((t, v))
        if len(pts) > _MAX_PTS:
            del pts[:len(pts) - _MAX_PTS]

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]
        self._plot_items[label].setData(xs, ys)

        if self._btn_autoscroll.isChecked() and xs:
            window = 10_000
            x_max = xs[-1]
            x_min = max(xs[0], x_max - window)
            self._plot.setXRange(x_min, x_max, padding=0.02)
