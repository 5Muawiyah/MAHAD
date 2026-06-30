from __future__ import annotations

import time as _time
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal, Slot
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from mahad.data.symbols import AlertsView
from mahad.ui import theme

_EMPTY = "No alerts yet - arm one from New Alert"

# one column model so cells line up across rows
COL_SYM = 96
COL_STATUS = 72
_ACT_X = 22
_ACT_REARM = 64
ROW_H = 52
CTRL_H = 22


def _transparent(w: QWidget) -> QWidget:
    # keep the wrapper see-through over the entry's tint
    w.setObjectName("AlertCell")
    w.setStyleSheet("QWidget#AlertCell { background: transparent; }")
    return w


class _ElideLabel(QLabel):

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._full = text
        super().setText(text)
        self.setToolTip(text)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(0, super().minimumSizeHint().height())

    def resizeEvent(self, e) -> None:  # noqa: N802
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight, self.width()))
        super().resizeEvent(e)


class AlertsTab(QWidget):

    rearm_requested = Signal(int)
    disarm_requested = Signal(int)
    remove_requested = Signal(int)
    delete_requested = Signal(int, bool)  # (alert_id, was_fired)
    armed_count_changed = Signal(int)  # tab count chip
    paused_changed = Signal(bool)  # window corner pill

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DockPanel")
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.S4, theme.S3, theme.S4, theme.S4)
        root.setSpacing(theme.S2)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setObjectName("AlertsViewport")
        scroll.viewport().setStyleSheet(
            "QWidget#AlertsViewport { background: transparent; }")
        self._list_host = QWidget()
        self._list_host.setObjectName("AlertListHost")
        self._list_host.setStyleSheet(
            "QWidget#AlertListHost { background: transparent; }")
        self._list = QVBoxLayout(self._list_host)
        self._list.setContentsMargins(0, 0, 0, 0)
        self._list.setSpacing(theme.S2)
        self._empty = QLabel(_EMPTY)
        self._empty.setProperty("tier", "3")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        self._empty.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 12.5px; padding: {theme.S8}px {theme.S4}px;"
            f" background: transparent; }}")
        self._list.addWidget(self._empty)
        self._list.addStretch(1)
        scroll.setWidget(self._list_host)
        root.addWidget(scroll, 1)

    @Slot(object)
    def set_state(self, view: object) -> None:
        if not isinstance(view, AlertsView):
            return
        self.paused_changed.emit(bool(view.paused))
        armed_n = sum(1 for r in view.rows if r.armed)
        self.armed_count_changed.emit(armed_n)
        # drop rows but keep the empty label and trailing stretch
        while self._list.count() > 2:
            item = self._list.takeAt(0)
            w = item.widget()
            if w is not None and w is not self._empty:
                w.deleteLater()
        self._empty.setVisible(view.is_empty)
        for i, row in enumerate(view.rows):
            self._list.insertWidget(i, self._make_row(row, zebra=(i % 2 == 1)))

    def _make_row(self, row, zebra: bool = False) -> QWidget:
        frame = QFrame()
        frame.setObjectName("AlertEntry")
        frame.setProperty("zebra", "on" if zebra else "off")
        frame.setFixedHeight(ROW_H)
        line = QHBoxLayout(frame)
        line.setContentsMargins(theme.S3, 0, theme.S3, 0)
        line.setSpacing(theme.S3)

        sym = QLabel(row.symbol)
        sym.setTextFormat(Qt.TextFormat.PlainText)          # symbol comes from outside, no rich text
        sym.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sym.setMinimumWidth(56)
        sym.setFixedHeight(CTRL_H)
        sym.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 12px; font-weight: 600;"
            f" color: {theme.TEXT_2}; background: rgba(255,255,255,0.06);"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
            f" padding: 0 8px; }}")
        # condition elides and shares its column with the inline cues
        desc = _ElideLabel(row.summary)
        desc.setTextFormat(Qt.TextFormat.PlainText)
        desc.setStyleSheet(f"QLabel {{ color: {theme.TEXT_1}; font-size: 13px;"
                           f" background: transparent; }}")
        cond_wrap = _transparent(QWidget())
        _cwl = QHBoxLayout(cond_wrap)
        _cwl.setContentsMargins(0, 0, 0, 0); _cwl.setSpacing(theme.S2)
        _cwl.addWidget(desc, 1)
        if row.not_active:                                  # symbol isn't the one being polled
            tag = QLabel("not active")
            tag.setFixedHeight(18)
            tag.setStyleSheet(
                # TEXT_2 ink reaches AA on the alternate row backing
                f"QLabel {{ color: {theme.TEXT_2}; font-family: {theme.FONT_MONO};"
                f" font-size: 10px; background: transparent;"
                f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
                f" padding: 1px 6px; }}")
            tag.setToolTip("not the active symbol - resumes when reselected")
            _cwl.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
        if not row.armed and row.fired_at:
            when = QLabel(_time.strftime("%H:%M:%S", _time.localtime(row.fired_at)))
            when.setStyleSheet(
                f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
                f" font-size: 11px; background: transparent; }}")
            when.setToolTip("fired at")
            _cwl.addWidget(when, 0)
        pill = QLabel("armed" if row.armed else "fired")
        pill.setObjectName("PillArmed" if row.armed else "PillFired")
        pill.setFixedHeight(CTRL_H)
        # chip pinned left in a fixed cell so conditions line up
        sym_cell = _transparent(QWidget())
        sym_cell.setFixedWidth(COL_SYM)
        _scl = QHBoxLayout(sym_cell)
        _scl.setContentsMargins(0, 0, 0, 0); _scl.setSpacing(0)
        _scl.addWidget(sym); _scl.addStretch(1)
        status_cell = _transparent(QWidget())
        status_cell.setFixedWidth(COL_STATUS)
        _stl = QHBoxLayout(status_cell)
        _stl.setContentsMargins(0, 0, 0, 0); _stl.setSpacing(0)
        _stl.addWidget(pill); _stl.addStretch(1)
        line.addWidget(sym_cell)
        line.addWidget(cond_wrap, 1)
        line.addWidget(status_cell)

        # armed rows reserve the same slot so widths stay put
        if not row.armed:
            rearm = QPushButton("re-arm")
            rearm.setFixedSize(_ACT_REARM, CTRL_H)
            rearm.setCursor(Qt.CursorShape.PointingHandCursor)
            rearm.setStyleSheet(
                f"QPushButton {{ color: {theme.TEXT_2}; background: transparent;"
                f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
                f" font-size: 11.5px; padding: 0; }}"
                f" QPushButton:hover {{ background: {theme.NESTED}; color: {theme.TEXT_1};"
                f" border-color: {theme.DIVIDER}; }}")
            rearm.clicked.connect(lambda _=False, i=row.id: self.rearm_requested.emit(i))
            line.addWidget(rearm)
        else:
            slot = _transparent(QWidget())
            slot.setFixedSize(_ACT_REARM, CTRL_H)
            line.addWidget(slot)

        # X deletes; it also carries the fired flag through to the signal
        remove = QPushButton("\u2715")
        remove.setFixedSize(_ACT_X, CTRL_H)
        remove.setCursor(Qt.CursorShape.PointingHandCursor)
        remove.setToolTip("Delete alert")
        remove.setStyleSheet(
            f"QPushButton {{ color: {theme.TEXT_2}; background: transparent;"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_ATOM}px;"
            f" font-size: 13px; padding: 0; }}"
            f" QPushButton:hover {{ color: {theme.TEXT_1}; background: {theme.NESTED};"
            f" border-color: {theme.DIVIDER}; }}")
        remove.clicked.connect(
            lambda _=False, i=row.id, f=(not row.armed): self.delete_requested.emit(i, f))
        line.addWidget(remove)

        # menu carries only the state paths; Delete lives on the X
        frame.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        frame.customContextMenuRequested.connect(
            lambda _pos, i=row.id, armed=bool(row.armed): self._row_menu(i, armed))
        return frame

    def _row_menu(self, alert_id: int, armed: bool) -> None:
        menu = QMenu(self)
        if armed:
            act_disarm = menu.addAction("Disarm")
            act_disarm.triggered.connect(lambda: self.disarm_requested.emit(alert_id))
        else:
            act_rearm = menu.addAction("Re-arm")
            act_rearm.triggered.connect(lambda: self.rearm_requested.emit(alert_id))
        menu.exec(self.cursor().pos())
