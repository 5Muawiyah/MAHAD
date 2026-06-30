from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QDialog, QDoubleSpinBox,
                               QFrame, QHBoxLayout, QLabel, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

from mahad.config import EMA_PERIOD, RSI_PERIOD, SMA_PERIOD
from mahad.engine.indicators import MAX_PERIOD, MIN_PERIOD
from mahad.engine.signals import (CROSSOVER_TYPES, DOWN, PRICE_SMA_CROSS,
                                  PRICE_THRESHOLD, RSI_THRESHOLD, SMA_EMA_CROSS,
                                  UP, AlertSpec, bars_needed_for, summary,
                                  validate_params)
from mahad.ui import theme

# (label, condition_type), in dialog order
_CONDITIONS = [
    ("Price crosses SMA", PRICE_SMA_CROSS),
    ("SMA crosses EMA", SMA_EMA_CROSS),
    ("RSI threshold", RSI_THRESHOLD),
    ("Price threshold", PRICE_THRESHOLD),
]
_TIP_NOTE = ("Tip: arm a price threshold just inside the live mark "
             "(use mark - 0.1%) - it fires within about one poll.")


class AlertDialog(QDialog):
    arm_requested = Signal(object)            # dict: condition_type, params, direction

    def __init__(self, active_symbol: Optional[str], mark: Optional[float],
                 stale: bool = False, warming: bool = False, closed_count: int = 0,
                 fired_summaries: Optional[set] = None,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Dialog)  # no native title bar
        self.setWindowTitle(f"{theme.APP_NAME} - New Alert")
        # translucent so the inner frame can round its corners
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._symbol = active_symbol
        self._drag = None
        self._mark = mark
        self._stale = stale
        self._warming = warming
        self._closed = int(closed_count)
        self._fired = fired_summaries or set()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        card = QFrame()
        card.setObjectName("AlertDialog")
        card.setMinimumWidth(420)
        outer.addWidget(card)
        root = QVBoxLayout(card)
        root.setContentsMargins(theme.S6, theme.S5, theme.S6, theme.S5)
        root.setSpacing(theme.S3)

        head = QHBoxLayout()
        head.setSpacing(theme.S2)
        title = QLabel("New Alert")
        title.setObjectName("PanelTitle")
        close = QPushButton("✕")
        close.setObjectName("DialogClose")
        close.setFocusPolicy(Qt.FocusPolicy.NoFocus)  # no dotted focus ring on open
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.reject)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(close)
        root.addLayout(head)

        root.addWidget(self._label("SYMBOL", obj="FieldLabel"))
        sym_text = active_symbol or "no symbol"
        mark_text = f"  ·  mark {mark:,.2f}" if mark is not None else "  ·  no quote yet"
        self._symbol_line = QLabel(f"{sym_text}{mark_text}")
        self._symbol_line.setObjectName("ReadoutBox")
        self._symbol_line.setStyleSheet(
            f"QLabel#ReadoutBox {{ font-family: {theme.FONT_MONO}; font-size: 13.5px;"
            f" color: {theme.TEXT_1}; background: {theme.ROW_SOLID};"
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_INPUT}px;"
            f" padding: 9px {theme.S3}px; }}")
        root.addWidget(self._symbol_line)

        root.addWidget(self._label("CONDITION", obj="FieldLabel"))
        self._cond = QComboBox()
        self._cond.setMinimumHeight(32)
        for label, _ in _CONDITIONS:
            self._cond.addItem(label)
        self._cond.currentIndexChanged.connect(self._on_condition_changed)
        root.addWidget(self._cond)

        # parameter rows are swapped in and out by condition
        self._params_box = QWidget()
        self._params_box.setObjectName("ParamsBox")
        self._params_box.setStyleSheet("QWidget#ParamsBox { background: transparent; }")
        self._pb = QVBoxLayout(self._params_box)
        self._pb.setContentsMargins(0, 0, 0, 0)
        self._pb.setSpacing(theme.S2)
        self._build_param_widgets()
        root.addWidget(self._params_box)

        root.addWidget(self._label("DIRECTION", obj="FieldLabel"))
        self._dir = QComboBox()
        self._dir.setMinimumHeight(32)
        self._dir.currentIndexChanged.connect(self._revalidate)
        root.addWidget(self._dir)

        self._note = QLabel("")
        self._note.setWordWrap(True)
        self._note.setStyleSheet(
            f"QLabel {{ color: {theme.AMBER}; font-family: {theme.FONT_MONO}; font-size: 11px; }}")
        self._note.hide()
        root.addWidget(self._note)

        self._error = QLabel("")
        self._error.setWordWrap(True)
        self._error.setStyleSheet(
            f"QLabel {{ color: {theme.RED}; font-size: 12px; }}")
        self._error.hide()
        root.addWidget(self._error)

        tip = QFrame()
        tip.setObjectName("TipBox")
        tipl = QVBoxLayout(tip)
        tipl.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        tip_note = QLabel(_TIP_NOTE)
        tip_note.setWordWrap(True)
        tip_note.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_2}; font-size: 11.5px; background: transparent; }}")
        tipl.addWidget(tip_note)
        root.addWidget(tip)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton("Cancel")
        cancel.setProperty("variant", "ghost")
        cancel.clicked.connect(self.reject)
        self._arm = QPushButton("Arm alert")
        self._arm.setProperty("variant", "primary")
        self._arm.clicked.connect(self._on_arm)
        btns.addWidget(cancel)
        btns.addWidget(self._arm)
        root.addLayout(btns)

        self._on_condition_changed(0)         # seed direction, params and validation

    def _label(self, text: str, obj: str = "") -> QLabel:
        lab = QLabel(text)
        if obj:
            lab.setObjectName(obj)
        return lab

    def _spin(self, default: int) -> QSpinBox:
        s = QSpinBox()
        s.setRange(MIN_PERIOD, MAX_PERIOD)
        s.setValue(default)
        s.setKeyboardTracking(False)                                   # validate once per edit, not per digit
        s.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        s.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        s.setMinimumHeight(32)
        s.valueChanged.connect(self._revalidate)
        return s

    def _build_param_widgets(self) -> None:
        self._sma = self._row("SMA period", self._spin(SMA_PERIOD))
        self._ema = self._row("EMA period", self._spin(EMA_PERIOD))
        self._rsi = self._row("RSI period", self._spin(RSI_PERIOD))
        self._level = QDoubleSpinBox()
        self._level.setDecimals(2)
        self._level.setRange(0.0, 1_000_000_000.0)
        self._level.setValue(0.0)
        self._level.setKeyboardTracking(False)
        self._level.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._level.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._level.setMinimumHeight(32)
        self._level.valueChanged.connect(self._revalidate)
        use_mark = QPushButton("use mark - 0.1%")
        use_mark.setProperty("variant", "ghost")
        use_mark.clicked.connect(self._use_mark)
        self._level_row = self._row("Level", self._level, use_mark)
        for w in (self._sma, self._ema, self._rsi, self._level_row):
            self._pb.addWidget(w)

    def _row(self, label: str, *widgets: QWidget) -> QWidget:
        w = QWidget()
        w.setObjectName("DlgRow")
        w.setStyleSheet("QWidget#DlgRow { background: transparent; }")   # let the glass card show through
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(theme.S2)
        lab = QLabel(label)
        lab.setStyleSheet(f"QLabel {{ color: {theme.TEXT_2}; font-size: 12.5px; }}")
        lab.setFixedWidth(96)
        h.addWidget(lab)
        for wd in widgets:
            h.addWidget(wd)
        h.addStretch(1)
        return w

    def _condition_type(self) -> str:
        return _CONDITIONS[self._cond.currentIndex()][1]

    def _on_condition_changed(self, _idx: int) -> None:
        ct = self._condition_type()
        self._sma.setVisible(ct in (PRICE_SMA_CROSS, SMA_EMA_CROSS))
        self._ema.setVisible(ct == SMA_EMA_CROSS)
        self._rsi.setVisible(ct == RSI_THRESHOLD)
        self._level_row.setVisible(ct in (RSI_THRESHOLD, PRICE_THRESHOLD))
        # crossovers read "up/down", thresholds read "at or above/below"
        self._dir.blockSignals(True)
        self._dir.clear()
        if ct in CROSSOVER_TYPES:
            self._dir.addItem("up (crosses above)", UP)
            self._dir.addItem("down (crosses below)", DOWN)
        else:
            self._dir.addItem("at or above", UP)
            self._dir.addItem("at or below", DOWN)
        self._dir.blockSignals(False)
        if ct == RSI_THRESHOLD:
            self._level.setRange(0.0, 100.0)
            if not 0.0 < self._level.value() <= 100.0:
                self._level.setValue(70.0)
        elif ct == PRICE_THRESHOLD:
            self._level.setRange(0.0, 1_000_000_000.0)
            if self._level.value() <= 0.0 and self._mark is not None:
                self._level.setValue(round(self._mark * 0.999, 2))     # prefill just under the mark
        self._revalidate()

    # drag the frameless window by its top band
    def mousePressEvent(self, e) -> None:  # noqa: N802
        if e.button() == Qt.MouseButton.LeftButton and e.position().y() < 56:
            self._drag = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()
        else:
            super().mousePressEvent(e)

    def mouseMoveEvent(self, e) -> None:  # noqa: N802
        if self._drag is not None and (e.buttons() & Qt.MouseButton.LeftButton):
            self.move(e.globalPosition().toPoint() - self._drag)
            e.accept()
        else:
            super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e) -> None:  # noqa: N802
        self._drag = None
        super().mouseReleaseEvent(e)

    def _use_mark(self) -> None:
        if self._mark is not None:
            self._level.setValue(round(self._mark * 0.999, 2))

    def _raw_params(self) -> dict:
        ct = self._condition_type()
        sma = self._sma.findChild(QSpinBox).value()
        ema = self._ema.findChild(QSpinBox).value()
        rsi = self._rsi.findChild(QSpinBox).value()
        if ct == PRICE_SMA_CROSS:
            return {"sma_period": sma}
        if ct == SMA_EMA_CROSS:
            return {"sma_period": sma, "ema_period": ema}
        if ct == RSI_THRESHOLD:
            return {"rsi_period": rsi, "level": self._level.value()}
        return {"level": self._level.value()}

    def _payload(self) -> dict:
        return {"condition_type": self._condition_type(),
                "params": self._raw_params(),
                "direction": self._dir.currentData()}

    def _revalidate(self, *_a) -> None:
        self._error.hide()
        ct = self._condition_type()
        if not self._symbol:
            self._note.setText("add a symbol to the watchlist first")
            self._note.show()
            self._arm.setEnabled(False)
            return
        ok, params, reason = validate_params(ct, self._raw_params())
        if not ok:
            self._error.setText(reason)
            self._error.show()
            self._arm.setEnabled(False)
            return
        # warn if an identical spec has already fired this session
        spec = AlertSpec(symbol=self._symbol, condition_type=ct, params=params,
                         direction=self._dir.currentData())
        if (self._symbol, summary(spec)) in self._fired:
            self._error.hide()
            self._note.setText("this condition already fired - re-arm it from the Alerts tab")
            self._note.show()
            self._arm.setEnabled(True)
            return
        need = bars_needed_for(ct, params, self._closed)
        msgs = []
        if need > 0:
            msgs.append(f"needs {need} more bars - will start once warmed")
        if self._warming:
            msgs.append("symbol is warming up - the alert arms but will not evaluate until live")
        elif self._stale:
            msgs.append("symbol is stale - alerts are paused until a fresh quote")
        if msgs:
            self._note.setText(" · ".join(msgs))
            self._note.show()
        else:
            self._note.hide()
        self._arm.setEnabled(True)

    def _on_arm(self) -> None:
        # stay open until the worker confirms the arm
        if getattr(self, "_arming", False):               # ignore double-clicks while in flight
            return
        self._arming = True
        self._error.hide()
        self._arm.setEnabled(False)
        self._arm.setText("arming...")
        self.arm_requested.emit(self._payload())

    def show_reject(self, reason: str) -> None:
        self._arming = False                              # let the user fix the input and retry
        self._note.hide()
        self._error.setText(reason)
        self._error.show()
        self._arm.setEnabled(True)
        self._arm.setText("Arm alert")
