from __future__ import annotations

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem,
    QPushButton, QLabel,
)
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtCore import Qt, pyqtSignal


_SEV = {
    "error":   ("✕", "#DC322F"),
    "warning": ("⚠", "#B58900"),
    "info":    ("ⓘ", "#657B83"),
}


class ProblemsPanel(QWidget):
    """Lists ERC / analyzer diagnostics (Layer 4).  Double-click → locate."""

    locate = pyqtSignal(str)          # emits the first part ref of a diagnostic

    def __init__(self, parent=None):
        super().__init__(parent)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QWidget()
        header.setFixedHeight(30)
        header.setStyleSheet("background:#EEE8D5; border-top:1px solid #93A1A1;")
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(12, 0, 8, 0)
        hbox.setSpacing(8)

        tab = QLabel("PROBLEMS")
        tab.setStyleSheet(
            "color:#586E75; font-size:10px; font-weight:600; letter-spacing:0.5px;"
            "border-top:2px solid #CB4B16; padding-top:6px;")
        hbox.addWidget(tab)

        self._count = QLabel("")
        self._count.setStyleSheet("color:#93A1A1; font-size:11px;")
        hbox.addWidget(self._count)
        hbox.addStretch()
        layout.addWidget(header)

        self._list = QListWidget()
        self._list.setFont(QFont("Menlo,Consolas,Courier New,monospace", 11))
        self._list.setStyleSheet(
            "QListWidget { background:#FDF6E3; border:none; color:#657B83; }"
            "QListWidget::item { padding:3px 10px; }"
            "QListWidget::item:selected { background:#EEE8D5; }")
        self._list.itemDoubleClicked.connect(self._on_activate)
        layout.addWidget(self._list)

    # ── public API ──────────────────────────────────────────────────────────────

    def set_diagnostics(self, diags):
        self._list.clear()
        n_err = n_warn = 0
        # errors first, then warnings, then info
        order = {"error": 0, "warning": 1, "info": 2}
        for d in sorted(diags, key=lambda x: order.get(x.severity.value, 3)):
            sev = d.severity.value
            icon, color = _SEV.get(sev, ("·", "#657B83"))
            n_err  += sev == "error"
            n_warn += sev == "warning"
            loc = " ".join(filter(None, [",".join(d.parts), ",".join(d.pins),
                                         ",".join(d.nets)]))
            text = f"{icon}  {d.message}" + (f"   [{loc}]" if loc else "")
            item = QListWidgetItem(text)
            item.setForeground(QColor(color))
            item.setData(Qt.ItemDataRole.UserRole, d.parts[0] if d.parts else "")
            self._list.addItem(item)

        if not diags:
            item = QListWidgetItem("✓  No problems detected")
            item.setForeground(QColor("#859900"))
            self._list.addItem(item)
            self._count.setText("")
        else:
            self._count.setText(f"{n_err} error(s), {n_warn} warning(s)")

    def clear(self):
        self._list.clear()
        self._count.setText("")

    # ── slots ─────────────────────────────────────────────────────────────────

    def _on_activate(self, item: QListWidgetItem):
        ref = item.data(Qt.ItemDataRole.UserRole)
        if ref:
            self.locate.emit(ref)
