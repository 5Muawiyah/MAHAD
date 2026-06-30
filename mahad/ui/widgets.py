from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (QAbstractButton, QButtonGroup, QFrame, QHBoxLayout,
                               QLabel, QPushButton, QTabBar, QWidget)

from mahad.ui import theme

_WHITE = QColor("#ffffff")


def _c(token: str) -> QColor:
    return theme._qcolor(token)


class ToggleSwitch(QAbstractButton):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(38, 22)

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(38, 22)

    def paintEvent(self, _event) -> None:  # noqa: N802
        on = self.isChecked()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(theme.ACCENT) if on else _c(theme.NESTED))
        p.drawRoundedRect(QRectF(0, 0, 38, 22), 11, 11)
        if not on:                                   # hairline ring when off
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(_c(theme.HAIRLINE))
            p.drawRoundedRect(QRectF(0.5, 0.5, 37, 21), 11, 11)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_WHITE if on else _c(theme.TEXT_3))
        knob_x = 20.0 if on else 2.0
        p.drawEllipse(QRectF(knob_x, 3.0, 16.0, 16.0))


class StatusDot(QWidget):
    # states: live, stale, warm, neutral

    def __init__(self, state: str = "warm", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._state = state
        self.setFixedSize(14, 14)

    def set_state(self, state: str) -> None:
        if state != self._state:
            self._state = state
            self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._state == "live":
            core, ring = theme.GREEN, theme.GREEN_SOFT
        elif self._state == "stale":
            core, ring = theme.AMBER, theme.AMBER_SOFT
        elif self._state == "neutral":
            core, ring = theme.NEUTRAL_DOT, None  # market closed
        else:
            core, ring = theme.TEXT_3, None
        cx, cy = 7.0, 7.0
        if ring is not None:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(_c(ring))
            p.drawEllipse(QRectF(cx - 6.5, cy - 6.5, 13.0, 13.0))
        p.setBrush(_c(core))
        p.drawEllipse(QRectF(cx - 4.0, cy - 4.0, 8.0, 8.0))


class LegendChip(QFrame):

    def __init__(self, text: str, color: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(6)
        self._swatch = QFrame()
        self._swatch.setFixedSize(14, 3)
        self._swatch.setStyleSheet(
            f"QFrame {{ background: {color}; border: none; border-radius: 1px; }}")
        self._label = QLabel(text)
        self._label.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 11.5px; border: none; background: transparent; }}")
        lay.addWidget(self._swatch)
        lay.addWidget(self._label)

    def set_text(self, text: str) -> None:
        self._label.setText(text)



class SegmentedControl(QFrame):

    changed = Signal(str)

    def __init__(self, options, active, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setStyleSheet(
            f"QFrame {{ background: {theme.NESTED}; border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_CTRL}px; }}")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(3, 3, 3, 3)
        lay.setSpacing(2)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}
        for opt in options:
            b = QPushButton(opt)
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setChecked(opt == active)
            b.setStyleSheet(
                f"QPushButton {{ background: transparent; border: none; outline: none;"
                f" border-radius: 7px; padding: 4px 12px; font-family: {theme.FONT_MONO};"
                f" font-size: 12px; color: {theme.TEXT_2}; }}"  # no focus rect
                f"QPushButton:checked {{ background: {theme.TONAL_FILL};"
                f" color: {theme.TONAL_LABEL}; font-weight: 600; }}")  # tonal selected
            b.clicked.connect(lambda _checked=False, o=opt: self.changed.emit(o))
            self._group.addButton(b)
            self._buttons[opt] = b
            lay.addWidget(b)

    def set_active(self, option: str) -> None:
        if option in self._buttons:
            self._buttons[option].setChecked(True)


# --------------------------------------------------------------------------- #
# custom window chrome (frameless title bar)
# --------------------------------------------------------------------------- #
class IconButton(QAbstractButton):

    def __init__(self, kind: str, tooltip: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._hover = False
        self.setToolTip(tooltip)
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def sizeHint(self) -> QSize:
        return QSize(30, 30)

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(255, 255, 255, 16))
            p.drawRoundedRect(QRectF(0, 0, 30, 30), 8, 8)
        col = _c(theme.TEXT_1) if self._hover else _c(theme.TEXT_2)
        pen = QPen(col)
        pen.setWidthF(1.4)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        cx, cy = 15.0, 15.0
        if self._kind == "gear":
            import math
            p.drawEllipse(QRectF(cx - 3.0, cy - 3.0, 6.0, 6.0))   # hub
            for i in range(8):                                    # 8 teeth
                a = i * math.pi / 4.0
                x0 = cx + 5.0 * math.cos(a); y0 = cy + 5.0 * math.sin(a)
                x1 = cx + 8.0 * math.cos(a); y1 = cy + 8.0 * math.sin(a)
                p.drawLine(QPointF(x0, y0), QPointF(x1, y1))
        else:                                                     # help: a ? glyph
            f = p.font()
            f.setFamily("Arial")
            f.setPixelSize(16)
            f.setBold(True)
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, "?")


class WinControlButton(QAbstractButton):

    def __init__(self, kind: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._hover = False
        self.setFixedSize(30, 30)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip({"min": "Minimise", "max": "Maximise",
                         "restore": "Restore", "close": "Close"}.get(kind, ""))

    def set_kind(self, kind: str) -> None:
        if kind != self._kind:
            self._kind = kind
            self.setToolTip({"min": "Minimise", "max": "Maximise",
                             "restore": "Restore", "close": "Close"}.get(kind, ""))
            self.update()

    def sizeHint(self) -> QSize:
        return QSize(30, 30)

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        close = self._kind == "close"
        if self.isDown():
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(248, 81, 73, 64) if close else QColor(255, 255, 255, 30))
            p.drawRoundedRect(QRectF(0, 0, 30, 30), 8, 8)
        elif self._hover:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(248, 81, 73, 40) if close else QColor(255, 255, 255, 16))
            p.drawRoundedRect(QRectF(0, 0, 30, 30), 8, 8)
        if close and (self._hover or self.isDown()):
            col = _c(theme.RED)
        else:
            col = _c(theme.TEXT_1) if (self._hover or self.isDown()) else _c(theme.TEXT_2)
        pen = QPen(col)
        pen.setWidthF(1.3)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        # 12x12 glyph box centred in the 30x30 button, so 9..21
        if self._kind == "min":
            p.drawLine(QPointF(9, 15), QPointF(21, 15))
        elif self._kind == "max":
            p.drawRoundedRect(QRectF(9.5, 9.5, 11, 11), 1.5, 1.5)
        elif self._kind == "restore":
            p.drawRoundedRect(QRectF(11, 9, 9, 9), 1.5, 1.5)     # back rect
            p.drawRoundedRect(QRectF(9, 11, 9, 9), 1.5, 1.5)     # front rect
        else:                                                    # close: an X
            p.drawLine(QPointF(10, 10), QPointF(20, 20))
            p.drawLine(QPointF(20, 10), QPointF(10, 20))


class AssetGlyph(QWidget):

    def __init__(self, asset_class: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._crypto = (asset_class == "crypto")
        self.setFixedSize(14, 14)
        self.setToolTip("Crypto pair" if self._crypto else "US equity")

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = _c(theme.TEXT_3)
        if self._crypto:                              # coin: circle + bar
            pen = p.pen(); pen.setColor(col); pen.setWidthF(1.3)
            p.setPen(pen); p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(2, 2, 10, 10))
            p.drawLine(QPointF(5, 7), QPointF(9, 7))
        else:                                          # stock: ascending bars
            p.setPen(Qt.PenStyle.NoPen); p.setBrush(col)
            p.drawRect(QRectF(2, 9, 2.6, 4))
            p.drawRect(QRectF(5.8, 6, 2.6, 7))
            p.drawRect(QRectF(9.6, 3, 2.6, 10))


class Chevron(QAbstractButton):

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._expanded = True
        self._hover = False
        self.setFixedSize(16, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_expanded(self, expanded: bool) -> None:
        if expanded != self._expanded:
            self._expanded = expanded
            self.update()

    def is_expanded(self) -> bool:
        return self._expanded

    def enterEvent(self, _e) -> None:  # noqa: N802
        self._hover = True
        self.update()

    def leaveEvent(self, _e) -> None:  # noqa: N802
        self._hover = False
        self.update()

    def paintEvent(self, _e) -> None:  # noqa: N802
        from PySide6.QtGui import QPolygonF
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = _c(theme.TEXT_1) if self._hover else _c(theme.TEXT_2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        if self._expanded:                                  # pointing down
            tri = QPolygonF([QPointF(4, 6), QPointF(12, 6), QPointF(8, 11)])
        else:                                               # pointing right
            tri = QPolygonF([QPointF(6, 4), QPointF(6, 12), QPointF(11, 8)])
        p.drawPolygon(tri)


# --------------------------------------------------------------------------- #
# Frameless window helpers (Qt6 system move/resize with a degrade path)
# --------------------------------------------------------------------------- #
def start_system_move(window: QWidget) -> bool:
    # True only if the native move path actually ran
    try:
        h = window.windowHandle()
        if h is not None and hasattr(h, "startSystemMove"):
            return bool(h.startSystemMove())
    except Exception:  # nosec B110 - degrade boundary (headless / no WM)
        pass
    return False


def start_system_resize(window: QWidget, edges) -> bool:
    try:
        h = window.windowHandle()
        if h is not None and hasattr(h, "startSystemResize"):
            return bool(h.startSystemResize(edges))
    except Exception:  # nosec B110 - degrade boundary
        pass
    return False


def edge_at(window: QWidget, pos, margin: int = 6):
    # Qt.Edges for a point in the border zone, else None
    r = window.rect()
    x, y, w, h = pos.x(), pos.y(), r.width(), r.height()
    left, right = x <= margin, x >= w - margin
    top, bottom = y <= margin, y >= h - margin
    if not (left or right or top or bottom):
        return None
    edges = Qt.Edge(0)
    if left:
        edges |= Qt.Edge.LeftEdge
    if right:
        edges |= Qt.Edge.RightEdge
    if top:
        edges |= Qt.Edge.TopEdge
    if bottom:
        edges |= Qt.Edge.BottomEdge
    return edges


class _DockTabBar(QTabBar):
    # draws its own fixed-width centred accent indicator under the active tab

    IND_W = 28

    def paintEvent(self, e) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(e)
        idx = self.currentIndex()
        if idx < 0:
            return
        r = self.tabRect(idx)
        x = r.center().x() - self.IND_W // 2
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(_c(theme.ACCENT))
        p.drawRoundedRect(QRectF(float(x), float(r.top()), float(self.IND_W), 2.0), 1.0, 1.0)
