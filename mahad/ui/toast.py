from __future__ import annotations

import time as _time
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QVBoxLayout, QWidget)

from mahad.ui import theme


class Toast(QFrame):
    dismissed = Signal()
    rearm_requested = Signal(int)

    def __init__(self, event, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(360)
        self._alert_id = event.alert_id if event.alert_id is not None else -1
        try:
            self.setGraphicsEffect(theme.drop_shadow(self, 34, 14, 150))   # outer glow
        except Exception:  # nosec B110 - degrade boundary
            pass

        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.S4, theme.S3, theme.S3, theme.S3)
        lay.setSpacing(theme.S1)

        top = QHBoxLayout()
        kicker = QLabel("ALERT FIRED")
        kicker.setStyleSheet(  # green reads as fired
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 10.5px;"
            f" letter-spacing: 1px; color: {theme.GREEN}; }}")
        dismiss = QPushButton("\u2715")
        dismiss.setObjectName("ToastClose")
        dismiss.setFixedSize(28, 28)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setToolTip("Dismiss")
        dismiss.setStyleSheet(
            f"QPushButton#ToastClose {{ color: rgba(255,255,255,0.92);"
            f" background: transparent; border: 1px solid rgba(255,255,255,0.18);"
            f" border-radius: 8px; font-size: 15px; padding: 0; }}"
            f" QPushButton#ToastClose:hover {{ background: {theme.RED_SOFT};"
            f" border-color: rgba(229,86,77,0.45); color: #FFFFFF; }}")
        dismiss.clicked.connect(self._dismiss)
        top.addWidget(kicker)
        top.addStretch(1)
        top.addWidget(dismiss)
        lay.addLayout(top)

        ident = QHBoxLayout()
        ident.setSpacing(theme.S2)
        chip = QLabel(event.symbol)
        chip.setTextFormat(Qt.TextFormat.PlainText)          # symbol-bearing text
        chip.setFixedHeight(22)
        chip.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 12px; font-weight: 600;"
            f" color: {theme.TEXT_2}; background: rgba(255,255,255,0.06);"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
            f" padding: 0 8px; }}")
        pill = QLabel("fired")
        pill.setObjectName("PillFired")
        pill.setFixedHeight(22)
        when = QLabel(_time.strftime("%H:%M:%S", _time.localtime(event.fired_at)))
        when.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 11px;"
            f" color: {theme.TEXT_3}; }}")
        ident.addWidget(chip)
        ident.addWidget(pill)
        ident.addStretch(1)
        ident.addWidget(when)
        lay.addLayout(ident)

        # drop the symbol/fired echoes here; full message lives in the tooltip
        display = event.message
        if display.startswith(f"{event.symbol} · "):
            display = display[len(event.symbol) + 3:]
        if display.endswith(" - fired"):
            display = display[: -len(" - fired")]
        msg = QLabel(display)
        msg.setTextFormat(Qt.TextFormat.PlainText)           # symbol-bearing text
        msg.setWordWrap(True)
        msg.setToolTip(event.message)
        msg.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 13px; color: {theme.TEXT_1}; }}")
        lay.addWidget(msg)

        actions = QHBoxLayout()
        actions.addStretch(1)
        rearm = QPushButton("re-arm")
        rearm.setFixedHeight(24)
        rearm.setCursor(Qt.CursorShape.PointingHandCursor)   # no accent fill per toast
        rearm.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_2}; background: transparent;"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
            f" font-size: 12px; padding: 0 12px; }}"
            f" QPushButton:hover {{ background: {theme.NESTED}; color: {theme.TEXT_1};"
            f" border-color: {theme.DIVIDER}; }}")
        rearm.clicked.connect(self._rearm)
        actions.addWidget(rearm)
        lay.addLayout(actions)

    def paintEvent(self, e) -> None:  # noqa: N802 (Qt override)
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0.5, 0.5, self.width() - 1.0, self.height() - 1.0,
                            float(theme.R_CARD), float(theme.R_CARD))
        p.setClipPath(path)
        c = theme._qcolor(theme.GREEN)
        c.setAlphaF(0.9)
        p.fillRect(0, 0, 3, self.height(), c)
        p.end()

    def _dismiss(self) -> None:
        self.dismissed.emit()

    def _rearm(self) -> None:
        if self._alert_id >= 0:
            self.rearm_requested.emit(self._alert_id)
        self.dismissed.emit()                                # re-arming clears the toast


class ToastHost(QWidget):
    rearm_requested = Signal(int)
    MAX_VISIBLE = 4
    MARGIN = 20
    STATUS_BAR_GAP = 30

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(0, 0, 0, 0)
        self._lay.setSpacing(theme.S2)
        self._lay.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self._toasts: list[Toast] = []
        self._overflow = 0
        self._more = QLabel("")
        self._more.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 11px; }}")
        self._more.hide()
        self._lay.addWidget(self._more, 0, Qt.AlignmentFlag.AlignRight)
        self.hide()

    def add_event(self, event) -> None:
        # one toast per fire; over the cap they fall back to the Alerts tab, never dropped
        toast = Toast(event, self)
        toast.dismissed.connect(lambda w=toast: self._remove(w))
        toast.rearm_requested.connect(self.rearm_requested)
        self._toasts.append(toast)
        self._lay.insertWidget(self._lay.count() - 1, toast)   # above the "+N more" label
        self._enforce_cap()
        self.show()
        self.raise_()
        self.reposition()

    def _enforce_cap(self) -> None:
        while len(self._toasts) > self.MAX_VISIBLE:
            old = self._toasts.pop(0)
            old.setParent(None)
            old.deleteLater()
            self._overflow += 1
        self._refresh_more()

    def _refresh_more(self) -> None:
        if self._overflow > 0:
            self._more.setText(f"+{self._overflow} more in the Alerts tab")
            self._more.show()
        else:
            self._more.hide()

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.setParent(None)
        toast.deleteLater()
        if not self._toasts:
            self._overflow = 0
            self._more.hide()
            self.hide()
        else:
            self._refresh_more()
            self.reposition()

    def reposition(self) -> None:
        # bottom-right, clearing the status bar
        parent = self.parentWidget()
        if parent is None:
            return
        self.adjustSize()
        x = parent.width() - self.width() - self.MARGIN
        y = parent.height() - self.height() - self.MARGIN - self.STATUS_BAR_GAP
        self.move(max(0, x), max(0, y))
