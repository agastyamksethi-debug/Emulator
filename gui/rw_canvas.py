"""
Real-World Node Canvas.

Displays physical-domain components (LED, photoresistor, speaker …) as
draggable node cards.  Ports representing physical phenomena (light, heat,
sound …) can be wired together by dragging from one port to another.

Architecture
────────────
  _Port          — small circle on a node representing one RW signal
  _Wire          — dashed orthogonal line connecting two ports
  _RWScene       — QGraphicsScene subclass that handles port-drag wiring
  _BaseNode      — QGraphicsItem base: pill-shaped card, movable, updates wires
  _LEDNode       — glowing circle, on/off state, light output port
  _LDRNode       — photoresistor schematic symbol, light input port
  RWCanvas       — QWidget wrapper: view + toolbar + public API
"""

from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QGraphicsScene, QGraphicsView, QGraphicsItem,
    QGraphicsEllipseItem, QGraphicsPathItem, QLabel,
)
from PyQt6.QtGui import (
    QPainter, QColor, QPen, QBrush, QPainterPath,
    QRadialGradient, QFont, QTransform,
)
from PyQt6.QtCore import (
    Qt, QRectF, QPointF, pyqtSignal, QObject,
)

from core.rw_bus import RWBus

# ── Solarized Light palette ───────────────────────────────────────────────────

_BG         = QColor("#FDF6E3")   # base3  – canvas
_NODE_BG    = QColor("#EEE8D5")   # base2  – card fill
_NODE_EDGE  = QColor("#93A1A1")   # base1  – soft border (used with alpha)
_ACCENT     = QColor("#CB4B16")   # orange – primary accent
_YELLOW     = QColor("#B58900")   # yellow – secondary accent / active
_GREEN      = QColor("#859900")   # green  – ok / released
_TEXT_PRI   = QColor("#657B83")   # base00 – body text
_TEXT_SEC   = QColor("#93A1A1")   # base1  – muted text
_LED_OFF    = QColor("#C8C0AD")   # muted warm disc when off
_PORT_CLR   = {
    "light": QColor("#93A1A1"),
    "sound": QColor("#2AA198"),
    "heat":  QColor("#DC322F"),
    "ir":    QColor("#6C71C4"),
    "force": QColor("#859900"),
}
_WIRE_CLR   = {
    "light": QColor("#93A1A1"),
    "sound": QColor("#2AA198"),
    "heat":  QColor("#DC322F"),
    "ir":    QColor("#6C71C4"),
    "force": QColor("#859900"),
}
_PORT_R     = 6
_PORT_HOVER = QColor("#CB4B16")


# ── port ──────────────────────────────────────────────────────────────────────

class _Port(QGraphicsEllipseItem):
    """Small circle on a node.  Carries rw_type and direction."""

    def __init__(self, rw_type: str, direction: str,
                 label: str = "", parent: QGraphicsItem = None):
        r = _PORT_R
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self.rw_type   = rw_type
        self.direction = direction   # "input" | "output"
        self.label     = label

        clr = _PORT_CLR.get(rw_type, QColor("#888888"))
        self.setBrush(QBrush(clr))
        self.setPen(QPen(QColor("#555555"), 1))
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setZValue(10)

        self._wires: list[_Wire] = []

    def scene_center(self) -> QPointF:
        return self.mapToScene(QPointF(0, 0))

    def add_wire(self, w: "_Wire"):
        self._wires.append(w)

    def remove_wire(self, w: "_Wire"):
        self._wires = [x for x in self._wires if x is not w]

    def notify(self):
        for w in self._wires:
            w.refresh()

    def hoverEnterEvent(self, ev):
        self.setBrush(QBrush(_PORT_HOVER))
        super().hoverEnterEvent(ev)

    def hoverLeaveEvent(self, ev):
        self.setBrush(QBrush(_PORT_CLR.get(self.rw_type, QColor("#888888"))))
        super().hoverLeaveEvent(ev)


# ── wire ──────────────────────────────────────────────────────────────────────

class _Wire(QGraphicsPathItem):
    """Dashed orthogonal (H-V-H) connection between two ports."""

    def __init__(self, src: _Port, dst: _Port):
        super().__init__()
        self.src = src
        self.dst = dst
        clr = _WIRE_CLR.get(src.rw_type, QColor("#888888"))
        self.setPen(QPen(clr, 1.8, Qt.PenStyle.DashLine))
        self.setZValue(1)
        self.refresh()

    def refresh(self):
        p1 = self.src.scene_center()
        p2 = self.dst.scene_center()
        mid_x = (p1.x() + p2.x()) / 2
        path = QPainterPath(p1)
        path.lineTo(mid_x, p1.y())
        path.lineTo(mid_x, p2.y())
        path.lineTo(p2)
        self.setPath(path)


# ── base node ─────────────────────────────────────────────────────────────────

class _BaseNode(QGraphicsItem):
    _W  = 130
    _H  = 200
    _CR = 16    # corner radius

    def __init__(self, ref: str, type_label: str):
        super().__init__()
        self.ref        = ref
        self.type_label = type_label
        self._ports: list[_Port] = []

        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            for p in self._ports:
                p.notify()
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        return QRectF(0, 0, self._W, self._H)

    def paint(self, painter: QPainter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        # card background
        edge = QColor(_NODE_EDGE)
        edge.setAlpha(100)   # ~40% opacity — soft border
        painter.setPen(QPen(edge, 1))
        painter.setBrush(QBrush(_NODE_BG))
        painter.drawRoundedRect(0, 0, self._W, self._H, self._CR, self._CR)
        # orange top accent line
        painter.setPen(QPen(_ACCENT, 2))
        painter.drawLine(int(self._CR), 1, int(self._W - self._CR), 1)

    def _add_port(self, rw_type: str, direction: str, label: str,
                  lx: float, ly: float) -> _Port:
        p = _Port(rw_type, direction, label, parent=self)
        p.setPos(lx, ly)
        self._ports.append(p)
        return p

    def ports(self) -> list[_Port]:
        return self._ports


# ── LED node ──────────────────────────────────────────────────────────────────

class _LEDNode(_BaseNode):
    _LED_R = 34

    def __init__(self, ref: str, color: str = "#ff2020"):
        super().__init__(ref, "LED")
        self._on         = False
        self._brightness = 0.0
        self._led_color  = QColor(color)

        self._port_light = self._add_port(
            "light", "output", "Light",
            self._W / 2, self._H - 16
        )

    def update_state(self, on: bool, brightness: float = 1.0):
        self._on         = on
        self._brightness = max(0.0, min(1.0, brightness))
        self.update()

    def paint(self, painter: QPainter, option, widget):
        super().paint(painter, option, widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self._W, self._H

        # ── ref label  (PCB monospace, top-left, 14 px from top) ─────────────
        f_ref = QFont("Menlo,Consolas,Courier New,monospace", 8, QFont.Weight.Bold)
        painter.setFont(f_ref)
        painter.setPen(_TEXT_PRI)
        painter.drawText(QRectF(12, 14, W - 52, 14), Qt.AlignmentFlag.AlignLeft, self.ref)

        # ── type badge pill (top-right, 14 px from top) ───────────────────────
        badge_rect = QRectF(W - 38, 13, 26, 14)
        painter.setBrush(QBrush(QColor("#FDF6E3")))
        bdr = QColor(_ACCENT); bdr.setAlpha(160)
        painter.setPen(QPen(bdr, 0.5))
        painter.drawRoundedRect(badge_rect, 6, 6)
        f_badge = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 7, QFont.Weight.Bold)
        painter.setFont(f_badge)
        painter.setPen(_ACCENT)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "LED")

        # ── LED disc (centred with room for pill + port below) ────────────────
        r  = self._LED_R
        cx = W / 2
        cy = 14 + 14 + 12 + r      # top_padding + row_h + gap + radius = 74

        if self._on:
            glow_r = r * (1.6 + 0.4 * self._brightness)
            c = self._led_color
            grad = QRadialGradient(cx, cy, glow_r)
            grad.setColorAt(0.0, QColor(c.red(), c.green(), c.blue(), 200))
            grad.setColorAt(0.45, QColor(c.red(), c.green(), c.blue(), 70))
            grad.setColorAt(1.0, QColor(c.red(), c.green(), c.blue(), 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        disc = self._led_color if self._on else _LED_OFF
        border_clr = self._led_color.darker(130) if self._on else QColor(_NODE_EDGE)
        painter.setPen(QPen(border_clr, 1.5))
        painter.setBrush(QBrush(disc))
        painter.drawEllipse(QPointF(cx, cy), r, r)

        if self._on:
            hi = QRadialGradient(cx - r * 0.28, cy - r * 0.32, r * 0.55)
            hi.setColorAt(0.0, QColor(255, 255, 255, 130))
            hi.setColorAt(1.0, QColor(255, 255, 255, 0))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(hi))
            painter.drawEllipse(QPointF(cx, cy), r, r)

        # ── state pill (below disc, 14 px gap, 12 px above port label) ────────
        if self._on:
            state_txt = f"ON  {int(self._brightness * 100)}%"
            pill_bg   = QColor("#FDF6E3")
            pill_fg   = _ACCENT
            pill_bdr  = QColor(_ACCENT); pill_bdr.setAlpha(80)
        else:
            state_txt = "OFF"
            pill_bg   = QColor("#FDF6E3")
            pill_fg   = _TEXT_SEC
            pill_bdr  = QColor(_NODE_EDGE); pill_bdr.setAlpha(80)

        pill_top  = cy + r + 12
        pill_rect = QRectF(W / 2 - 30, pill_top, 60, 17)
        painter.setBrush(QBrush(pill_bg))
        painter.setPen(QPen(pill_bdr, 0.5))
        painter.drawRoundedRect(pill_rect, 8, 8)
        f_st = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 8, QFont.Weight.Medium)
        painter.setFont(f_st)
        painter.setPen(pill_fg)
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, state_txt)

        # ── port connector trace (12 px above port) ───────────────────────────
        port_y    = H - 16
        label_y   = port_y - 14
        trc = QColor(_TEXT_SEC); trc.setAlpha(80)
        painter.setPen(QPen(trc, 1, Qt.PenStyle.DotLine))
        painter.drawLine(QPointF(W / 2 - 20, port_y), QPointF(W / 2 - 9, port_y))
        painter.drawLine(QPointF(W / 2 + 9,  port_y), QPointF(W / 2 + 20, port_y))

        f3 = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 7)
        painter.setFont(f3)
        painter.setPen(_TEXT_SEC)
        painter.drawText(QRectF(0, label_y, W, 12), Qt.AlignmentFlag.AlignHCenter, "LIGHT OUT")


# ── Photoresistor (LDR) node ──────────────────────────────────────────────────

class _LDRNode(_BaseNode):
    _W = 150

    def __init__(self, ref: str):
        super().__init__(ref, "PHOTORESISTOR")

        # light input on left-centre
        self._port_light = self._add_port(
            "light", "input", "Light",
            0, self._H / 2
        )

    def paint(self, painter: QPainter, option, widget):
        super().paint(painter, option, widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self._W, self._H

        # ── ref + type labels ─────────────────────────────────────────────────
        f_ref = QFont("Menlo,Consolas,Courier New,monospace", 8, QFont.Weight.Bold)
        painter.setFont(f_ref)
        painter.setPen(_TEXT_PRI)
        painter.drawText(QRectF(10, 8, W - 50, 14), Qt.AlignmentFlag.AlignLeft, self.ref)

        badge_rect = QRectF(W - 44, 7, 34, 15)
        painter.setBrush(QBrush(QColor("#EDE9E3")))
        painter.setPen(QPen(_NODE_EDGE, 0.5))
        painter.drawRoundedRect(badge_rect, 7, 7)
        f_b = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 7, QFont.Weight.Bold)
        painter.setFont(f_b)
        painter.setPen(_TEXT_SEC)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "LDR")

        # ── schematic symbol: rectangle + horizontal lines ────────────────────
        sx = W / 2 - 28
        sy = H / 2 - 36
        sw = 56
        sh = 72

        painter.setPen(QPen(_TEXT_PRI, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRoundedRect(QRectF(sx, sy, sw, sh), 6, 6)

        n_lines = 4
        gap = sh / (n_lines + 1)
        for i in range(n_lines):
            ly = sy + gap * (i + 1)
            painter.drawLine(QPointF(sx + 8, ly), QPointF(sx + sw - 8, ly))

        painter.setPen(QPen(_TEXT_SEC, 1.5))
        painter.drawLine(QPointF(0, H / 2), QPointF(sx, H / 2))
        painter.drawLine(QPointF(sx + sw, H / 2), QPointF(W, H / 2))

        # ── port label ────────────────────────────────────────────────────────
        f2 = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 7)
        painter.setFont(f2)
        painter.setPen(_TEXT_SEC)
        painter.drawText(QRectF(8, H / 2 - 18, 50, 14),
                         Qt.AlignmentFlag.AlignLeft, "LIGHT IN")


# ── button cap (child item, handles its own mouse events) ────────────────────

class _ButtonCap(QGraphicsEllipseItem):
    """
    Tactile button cap drawn as a 3-D disc.
    Handles its own press/release so the parent node stays draggable elsewhere.
    """
    _R = 32

    def __init__(self, parent: QGraphicsItem, on_change):
        r = self._R
        super().__init__(-r, -r, r * 2, r * 2, parent)
        self._on_change = on_change
        self._pressed   = False
        self.setAcceptHoverEvents(True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setPen(QPen(Qt.PenStyle.NoPen))  # paint() handles own outline
        self.setZValue(5)

    def paint(self, painter: QPainter, option, widget):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = self._R

        if not self._pressed:
            # shadow
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#586E75")))
            painter.drawEllipse(QPointF(2, 4), r, r)
            # cap — Solarized gray gradient
            grad = QRadialGradient(-r * 0.3, -r * 0.35, r * 1.3)
            grad.setColorAt(0.0, QColor("#C8C0AD"))
            grad.setColorAt(0.5, QColor("#93A1A1"))
            grad.setColorAt(1.0, QColor("#657B83"))
            painter.setBrush(QBrush(grad))
            painter.setPen(QPen(QColor("#57534E"), 1.5))
            painter.drawEllipse(QPointF(0, 0), r, r)
        else:
            # pressed: flat Solarized-orange tinted
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(QColor("#586E75")))
            painter.drawEllipse(QPointF(1, 2), r, r)
            painter.setPen(QPen(_ACCENT, 1.5))
            painter.setBrush(QBrush(_ACCENT.darker(150)))
            painter.drawEllipse(QPointF(0, 2), r, r)

    def mousePressEvent(self, ev):
        self._pressed = True
        self.update()
        self._on_change(True)
        ev.accept()          # stop event reaching parent node (prevents drag)

    def mouseReleaseEvent(self, ev):
        self._pressed = False
        self.update()
        self._on_change(False)
        ev.accept()


# ── button node ───────────────────────────────────────────────────────────────

class _ButtonNode(_BaseNode):
    _H = 180

    def __init__(self, ref: str):
        super().__init__(ref, "BUTTON")
        self._pressed = False
        self._model   = None          # ButtonModel set after sim starts

        # button cap child — lives at vertical centre of card
        self._cap = _ButtonCap(self, self._on_cap_change)
        self._cap.setPos(self._W / 2, self._H / 2 + 12)

    # ── model binding (called from main thread after sim node_ready signal) ───

    def bind_model(self, model):
        self._model = model

    # ── cap interaction ───────────────────────────────────────────────────────

    def _on_cap_change(self, pressed: bool):
        self._pressed = pressed
        if self._model is not None:
            self._model.set_pressed(pressed)
        self.update()

    # ── paint ─────────────────────────────────────────────────────────────────

    def paint(self, painter: QPainter, option, widget):
        super().paint(painter, option, widget)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self._W, self._H

        # ── ref label (PCB monospace, top-left, 14 px from top) ──────────────
        f_ref = QFont("Menlo,Consolas,Courier New,monospace", 8, QFont.Weight.Bold)
        painter.setFont(f_ref)
        painter.setPen(_TEXT_PRI)
        painter.drawText(QRectF(12, 14, W - 52, 14), Qt.AlignmentFlag.AlignLeft, self.ref)

        # ── type badge pill (top-right, 14 px from top) ───────────────────────
        badge_rect = QRectF(W - 42, 13, 30, 14)
        painter.setBrush(QBrush(QColor("#FDF6E3")))
        bdr = QColor(_TEXT_SEC); bdr.setAlpha(100)
        painter.setPen(QPen(bdr, 0.5))
        painter.drawRoundedRect(badge_rect, 6, 6)
        f_badge = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 7, QFont.Weight.Bold)
        painter.setFont(f_badge)
        painter.setPen(_TEXT_SEC)
        painter.drawText(badge_rect, Qt.AlignmentFlag.AlignCenter, "TACT")

        # ── state pill (12 px from bottom) ────────────────────────────────────
        if self._pressed:
            state_txt = "PRESSED"
            pill_bg   = QColor("#FDF6E3")
            pill_fg   = _ACCENT
            dot_clr   = _ACCENT
            pill_bdr  = QColor(_ACCENT); pill_bdr.setAlpha(80)
        else:
            state_txt = "RELEASED"
            pill_bg   = QColor("#FDF6E3")
            pill_fg   = _GREEN
            dot_clr   = _GREEN
            pill_bdr  = QColor(_GREEN); pill_bdr.setAlpha(80)

        pill_rect = QRectF(W / 2 - 40, H - 28, 80, 16)
        painter.setBrush(QBrush(pill_bg))
        painter.setPen(QPen(pill_bdr, 0.5))
        painter.drawRoundedRect(pill_rect, 8, 8)

        # indicator dot
        dot_x = pill_rect.left() + 11
        dot_y = pill_rect.center().y()
        painter.setBrush(QBrush(dot_clr))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(QPointF(dot_x, dot_y), 3.5, 3.5)

        f_st = QFont("SF Pro Text,Helvetica,Arial,sans-serif", 8, QFont.Weight.Medium)
        painter.setFont(f_st)
        painter.setPen(pill_fg)
        text_rect = QRectF(pill_rect.left() + 18, pill_rect.top(),
                           pill_rect.width() - 22, pill_rect.height())
        painter.drawText(text_rect,
                         Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                         state_txt)


# ── scene (handles port-drag wiring) ─────────────────────────────────────────

class _RWScene(QGraphicsScene):
    connection_made = pyqtSignal(str, str, str)   # src_id, dst_id, rw_type

    def __init__(self):
        super().__init__()
        self._drag_src:  _Port | None            = None
        self._temp_wire: QGraphicsPathItem | None = None

    def _port_at(self, pos: QPointF) -> _Port | None:
        for item in self.items(pos):
            if isinstance(item, _Port):
                return item
        return None

    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            port = self._port_at(ev.scenePos())
            if port:
                self._drag_src = port
                self._temp_wire = QGraphicsPathItem()
                clr = _WIRE_CLR.get(port.rw_type, QColor("#888888"))
                self._temp_wire.setPen(QPen(clr, 1.5, Qt.PenStyle.DashLine))
                self._temp_wire.setZValue(100)
                self.addItem(self._temp_wire)
                ev.accept()
                return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev):
        if self._drag_src and self._temp_wire:
            p1 = self._drag_src.scene_center()
            p2 = ev.scenePos()
            mid_x = (p1.x() + p2.x()) / 2
            path = QPainterPath(p1)
            path.lineTo(mid_x, p1.y())
            path.lineTo(mid_x, p2.y())
            path.lineTo(p2)
            self._temp_wire.setPath(path)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev):
        if self._drag_src and self._temp_wire:
            self.removeItem(self._temp_wire)
            self._temp_wire = None

            dst = self._port_at(ev.scenePos())
            src = self._drag_src
            self._drag_src = None

            if (dst and dst is not src
                    and dst.rw_type == src.rw_type
                    and dst.direction != src.direction):
                # normalise so src is always the output
                out_p = src if src.direction == "output" else dst
                in_p  = dst if src.direction == "output" else src
                wire = _Wire(out_p, in_p)
                self.addItem(wire)
                out_p.add_wire(wire)
                in_p.add_wire(wire)
                # emit bus-level ids
                out_id = f"{out_p.parentItem().ref}:{out_p.rw_type}"
                in_id  = f"{in_p.parentItem().ref}:{in_p.rw_type}"
                self.connection_made.emit(out_id, in_id, src.rw_type)

            ev.accept()
            return
        super().mouseReleaseEvent(ev)

    def remove_wire(self, wire: _Wire):
        wire.src.remove_wire(wire)
        wire.dst.remove_wire(wire)
        self.removeItem(wire)


# ── view ──────────────────────────────────────────────────────────────────────

class _RWView(QGraphicsView):
    def __init__(self, scene: _RWScene):
        super().__init__(scene)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setStyleSheet("QGraphicsView { border:none; background:#FDF6E3; }")
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

    def drawBackground(self, painter: QPainter, rect):
        painter.fillRect(rect, _BG)
        # faint dotted grid
        pen = QPen(QColor("#C5BDA8"), 1.2)
        painter.setPen(pen)
        grid = 28
        l = int(rect.left())  - (int(rect.left())  % grid)
        t = int(rect.top())   - (int(rect.top())   % grid)
        x = float(l)
        while x < rect.right():
            y = float(t)
            while y < rect.bottom():
                painter.drawPoint(QPointF(x, y))
                y += grid
            x += grid

    def wheelEvent(self, ev):
        factor = 1.15 if ev.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)

    def mousePressEvent(self, ev):
        # don't start pan-drag when clicking on a port or node
        item = self.itemAt(ev.pos())
        if isinstance(item, (_Port, _BaseNode)):
            self.setDragMode(QGraphicsView.DragMode.NoDrag)
        else:
            self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        super().mouseReleaseEvent(ev)


# ── toolbar button helper ─────────────────────────────────────────────────────

def _tbtn(label: str) -> QPushButton:
    b = QPushButton(label)
    b.setFixedHeight(22)
    b.setStyleSheet(
        "QPushButton { background:#FDF6E3; color:#657B83; border:1px solid #93A1A1; "
        "border-radius:3px; padding:0 10px; font-size:10px; }"
        "QPushButton:hover { background:#EEE8D5; color:#586E75; }"
    )
    return b


# ── public canvas widget ──────────────────────────────────────────────────────

class RWCanvas(QWidget):
    """
    The real-world node canvas.

    Public API
    ──────────
    add_led(ref, color)     → place an LED node and return it
    add_ldr(ref)            → place a photoresistor node and return it
    get_led(ref)            → look up an existing LED node
    update_led(ref, on, brightness)  → update LED visual state during sim
    rw_bus                  → the RWBus instance (read by sim for LDR values etc.)
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rw_bus = RWBus()
        self._nodes: dict[str, _BaseNode] = {}
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # header
        header = QWidget()
        header.setFixedHeight(32)
        header.setStyleSheet("background:#EEE8D5; border-bottom:1px solid #93A1A1;")
        hbox = QHBoxLayout(header)
        hbox.setContentsMargins(8, 4, 8, 4)
        hbox.setSpacing(6)
        title = QLabel("Real World")
        title.setStyleSheet("color:#657B83; font-size:11px;")
        hbox.addWidget(title)
        hbox.addStretch()

        btn_led = _tbtn("+ LED")
        btn_ldr = _tbtn("+ LDR")
        btn_btn = _tbtn("+ Button")
        btn_led.clicked.connect(self._add_led_interactive)
        btn_ldr.clicked.connect(self._add_ldr_interactive)
        btn_btn.clicked.connect(self._add_button_interactive)
        hbox.addWidget(btn_led)
        hbox.addWidget(btn_ldr)
        hbox.addWidget(btn_btn)
        layout.addWidget(header)

        self._scene = _RWScene()
        self._scene.setSceneRect(-2000, -2000, 4000, 4000)
        self._scene.connection_made.connect(self._on_connection)
        self._view = _RWView(self._scene)
        layout.addWidget(self._view)

        self._next_led = 1
        self._next_ldr = 1
        self._next_btn = 1

    # ── node addition ─────────────────────────────────────────────────────────

    def add_led(self, ref: str, color: str = "#ff2020",
                pos: tuple[float, float] = (0, 0)) -> _LEDNode:
        node = _LEDNode(ref, color)
        node.setPos(*pos)
        self._scene.addItem(node)
        self._nodes[ref] = node
        return node

    def add_ldr(self, ref: str,
                pos: tuple[float, float] = (220, 0)) -> _LDRNode:
        node = _LDRNode(ref)
        node.setPos(*pos)
        self._scene.addItem(node)
        self._nodes[ref] = node
        return node

    def add_button(self, ref: str,
                   pos: tuple[float, float] = (0, 0)) -> _ButtonNode:
        node = _ButtonNode(ref)
        node.setPos(*pos)
        self._scene.addItem(node)
        self._nodes[ref] = node
        return node

    def get_led(self, ref: str) -> _LEDNode | None:
        n = self._nodes.get(ref)
        return n if isinstance(n, _LEDNode) else None

    def get_button(self, ref: str) -> _ButtonNode | None:
        n = self._nodes.get(ref)
        return n if isinstance(n, _ButtonNode) else None

    # ── sim update ────────────────────────────────────────────────────────────

    def update_led(self, ref: str, on: bool, brightness: float = 1.0):
        """Called by SimWorker after each tick to update LED visual."""
        node = self.get_led(ref)
        if node:
            node.update_state(on, brightness)
            # propagate to RW bus
            self.rw_bus.set(f"{ref}:light", brightness if on else 0.0)
            self.rw_bus.tick()

    # ── circuit auto-population ───────────────────────────────────────────────

    def load_circuit(self, circuit: dict):
        """
        Auto-populate RW canvas from a circuit dict.
        Creates visual nodes for every LED and button part found.
        Existing nodes are cleared first.
        """
        # clear existing visual nodes
        for ref in list(self._nodes.keys()):
            item = self._nodes.pop(ref)
            if self._scene:
                self._scene.removeItem(item)

        _LED_TYPES = {"led", "Device:LED", "Device:LED_ALT"}
        _BTN_TYPES = {"button", "Device:SW_Push", "Device:SW_Push_Virtual"}
        _LDR_TYPES = {"ldr", "photoresistor", "Device:R_Photo"}

        led_col = 0
        btn_col = 0
        ldr_col = 0

        for ref, part_def in circuit.get("parts", {}).items():
            ptype = part_def.get("type", "")
            color = part_def.get("color", "red")
            # map color name to hex
            _CLR = {"red": "#ff2020", "green": "#20dd20", "blue": "#2060ff",
                    "yellow": "#ffdd00", "white": "#ffffff", "orange": "#ff8800"}
            hex_color = _CLR.get(color, "#ff2020")

            if ptype in _LED_TYPES:
                x = led_col * 160 - 200
                self.add_led(ref, color=hex_color, pos=(x, -80))
                led_col += 1
                self._next_led = led_col + 1

            elif ptype in _BTN_TYPES:
                x = btn_col * 160 - 200
                self.add_button(ref, pos=(x, 140))
                btn_col += 1
                self._next_btn = btn_col + 1

            elif ptype in _LDR_TYPES:
                x = ldr_col * 200 + 80
                self.add_ldr(ref, pos=(x, -80))
                ldr_col += 1
                self._next_ldr = ldr_col + 1

        self._view.fitInView(
            self._scene.itemsBoundingRect().adjusted(-40, -40, 40, 40),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    # ── sim node binding (called when sim starts and nodes are instantiated) ───

    def on_node_ready(self, ref: str, node):
        """
        Called by SimWorker for each sim node after the runner is set up.
        Links button visual nodes to their ButtonModel counterparts so
        clicking the cap directly calls model.set_pressed().
        """
        btn_node = self.get_button(ref)
        if btn_node is not None:
            btn_node.bind_model(node)

    # ── connection handler ────────────────────────────────────────────────────

    def _on_connection(self, src_id: str, dst_id: str, rw_type: str):
        self.rw_bus.connect(src_id, dst_id)

    # ── interactive add (toolbar buttons) ─────────────────────────────────────

    def _add_led_interactive(self):
        ref = f"D{self._next_led}"
        self._next_led += 1
        # place near centre of current view
        centre = self._view.mapToScene(
            self._view.viewport().rect().center()
        )
        x = centre.x() - 65 + (self._next_led - 2) * 20
        y = centre.y() - 100
        self.add_led(ref, pos=(x, y))

    def _add_ldr_interactive(self):
        ref = f"R{self._next_ldr}"
        self._next_ldr += 1
        centre = self._view.mapToScene(
            self._view.viewport().rect().center()
        )
        x = centre.x() + 80 + (self._next_ldr - 2) * 20
        y = centre.y() - 100
        self.add_ldr(ref, pos=(x, y))

    def _add_button_interactive(self):
        ref = f"SW{self._next_btn}"
        self._next_btn += 1
        centre = self._view.mapToScene(
            self._view.viewport().rect().center()
        )
        x = centre.x() - 65 + (self._next_btn - 2) * 20
        y = centre.y() - 87
        self.add_button(ref, pos=(x, y))
