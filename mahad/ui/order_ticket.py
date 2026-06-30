from __future__ import annotations

from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QVBoxLayout, QWidget)

from mahad import config
from mahad.engine.portfolio import validate_qty
from mahad.ui import theme
from mahad.ui.glass_dialog import GlassDialog
from mahad.ui.widgets import SegmentedControl


def _fmt(d: Decimal) -> str:
    return f"{d:,.2f}"


class OrderTicket(GlassDialog):

    order_requested = Signal(object)            # side, qty, symbol, mark, ts

    def __init__(self, symbol: Optional[str], asset_class: str, mark: Optional[float],
                 mark_ts: Optional[float], stale: bool, warming: bool,
                 parent: Optional[QWidget] = None) -> None:
        super().__init__("Order ticket", width=460, parent=parent)
        self._symbol = symbol
        self._asset_class = asset_class or ("crypto" if symbol and "/" in symbol else "stock")
        self._mark = mark
        self._mark_ts = mark_ts
        self._stale = stale
        self._warming = warming
        self._pending = False
        self._done = False
        b = self.body()

        b.addWidget(self.field_label("SYMBOL"))
        sym_text = f"{symbol} · {self._asset_class}" if symbol else "no symbol"
        sym = QLabel(sym_text)
        sym.setTextFormat(Qt.TextFormat.PlainText)          # symbol is external-origin, no rich text
        sym.setObjectName("ReadoutBox")
        sym.setStyleSheet(
            f"QLabel#ReadoutBox {{ font-family: {theme.FONT_MONO}; font-size: 13.5px;"
            f" color: {theme.TEXT_1}; padding: 9px {theme.S3}px; }}")
        b.addWidget(sym)
        sim_note = QLabel("Simulated order - no real order is placed; the worker "
                          "fills it at the live mark.")
        sim_note.setWordWrap(True)
        sim_note.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-size: 11px; background: transparent; }}")
        b.addWidget(sim_note)

        # side and quantity, two-up
        row = QHBoxLayout()
        row.setSpacing(theme.S3)
        side_col = QVBoxLayout(); side_col.setSpacing(theme.S2)
        side_col.addWidget(self.field_label("SIDE"))
        self._side = SegmentedControl(["Buy", "Sell"], "Buy")
        self._side.changed.connect(self._on_side)
        side_col.addWidget(self._side)
        qty_col = QVBoxLayout(); qty_col.setSpacing(theme.S2)
        qty_col.addWidget(self.field_label("QUANTITY"))
        self._qty = QLineEdit(config.default_order_qty(symbol))   # default varies by asset class
        self._qty.setProperty("mono", "true")
        self._qty.textChanged.connect(lambda _t: self._refresh())
        qty_col.addWidget(self._qty)
        row.addLayout(side_col, 1)
        row.addLayout(qty_col, 1)
        b.addLayout(row)

        # live readout: mark plus estimated cost/proceeds
        box = QWidget(); box.setObjectName("ReadoutBox")
        bl = QVBoxLayout(box)
        bl.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        bl.setSpacing(theme.S2)
        mk = QHBoxLayout()
        mk.addWidget(self._dim("Mark"))
        mk.addStretch(1)
        self._mark_val = self._mono("-")
        mk.addWidget(self._mark_val)
        bl.addLayout(mk)
        est = QHBoxLayout()
        self._est_label = self._dim("Estimated cost")
        est.addWidget(self._est_label)
        est.addStretch(1)
        self._est_val = self._mono("-")
        est.addWidget(self._est_val)
        bl.addLayout(est)
        b.addWidget(box)

        self._warn = QLabel("")
        self._warn.setObjectName("InlineWarn")
        self._warn.setWordWrap(True)
        self._warn.hide()
        b.addWidget(self._warn)
        self._filled = QLabel("")
        self._filled.setObjectName("FillOk")
        self._filled.hide()
        b.addWidget(self._filled)

        foot = QHBoxLayout()
        foot.addStretch(1)
        self._cancel = QPushButton("Cancel")
        self._cancel.setProperty("variant", "ghost")
        self._cancel.clicked.connect(self.reject)
        self._confirm = QPushButton("Confirm buy")
        self._confirm.setProperty("variant", "primary")
        self._confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        self._confirm.clicked.connect(self._on_confirm)
        self._cancel.setAutoDefault(False)                 # Enter must not reject
        self._confirm.setDefault(True)
        self._confirm.setAutoDefault(True)
        foot.addWidget(self._cancel)
        foot.addWidget(self._confirm)
        self.add_footer(foot)

        self._refresh()

    def _dim(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(f"QLabel {{ color: {theme.TEXT_2}; background: transparent; }}")
        return lab

    def _mono(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; color: {theme.TEXT_1};"
            f" background: transparent; }}")
        return lab

    def _side_text(self) -> str:
        return "buy" if self._current_side() == "Buy" else "sell"

    def _current_side(self) -> str:
        return getattr(self, "_side_value", "Buy")

    def _on_side(self, opt: str) -> None:
        self._side_value = opt
        self._est_label.setText("Estimated cost" if opt == "Buy" else "Estimated proceeds")
        self._confirm.setText(f"Confirm {opt.lower()}")
        self._refresh()

    # called on every snapshot while the ticket is open
    def update_quote(self, mark: Optional[float], mark_ts: Optional[float],
                     stale: bool, warming: bool) -> None:
        if self._done:
            return
        self._mark, self._mark_ts, self._stale, self._warming = mark, mark_ts, stale, warming
        self._refresh()

    def _qty_decimal(self):
        ok, q, _reason = validate_qty(self._qty.text().strip())
        return (q if ok else None)

    def _refresh(self) -> None:
        if self._pending or self._done:
            return
        self._mark_val.setText(f"{self._mark:,.2f} USD" if self._mark is not None else "-")
        q = self._qty_decimal()
        bad_qty = bool(self._qty.text().strip()) and q is None
        if bool(self._qty.property("error")) != bad_qty:    # re-polish to repaint the error border
            self._qty.setProperty("error", bad_qty)
            self._qty.style().unpolish(self._qty)
            self._qty.style().polish(self._qty)
        if self._mark is not None and q is not None:
            self._est_val.setText(f"{(q * Decimal(str(self._mark))):,.2f} USD")
        else:
            self._est_val.setText("-")
        reason = ""
        if not self._symbol:
            reason = "add a symbol first"
        elif self._mark is None or self._warming:
            reason = "warming up - no quote yet"
        elif self._stale:
            reason = "stale price - waiting for a fresh quote"
        elif q is None:
            reason = "enter a valid quantity"
        if reason:
            self._warn.setText(reason)
            self._warn.show()
            self._confirm.setEnabled(False)
        else:
            self._warn.hide()
            self._confirm.setEnabled(True)

    def _on_confirm(self) -> None:
        if self._pending or self._done:                    # single-flight: ignore re-entry
            return
        q = self._qty_decimal()
        if self._mark is None or q is None or not self._symbol:
            return
        self._pending = True
        self._confirm.setEnabled(False)
        self._confirm.setText("filling...")
        self._warn.hide()
        self.order_requested.emit({
            "side": self._side_text(), "qty": self._qty.text().strip(),
            "symbol": self._symbol, "mark": self._mark, "ts": self._mark_ts})

    def reject(self) -> None:  # noqa: D401 # no close while a fill is in flight
        if self._pending and not self._done:
            return
        super().reject()

    # fed by the worker's order_result channel
    def show_result(self, result: object) -> None:
        if not isinstance(result, dict):
            return
        self._pending = False
        if result.get("ok"):
            self._done = True
            self._filled.setText(result.get("summary") or "filled")
            self._filled.show()
            self._confirm.hide()
            self._cancel.setText("Done")
            QTimer.singleShot(1200, self.accept)           # leave the banner up a beat before closing
        else:
            self._warn.setText(result.get("reason") or "order rejected")
            self._warn.show()
            self._confirm.setEnabled(True)
            self._confirm.setText(f"Confirm {self._side_text()}")
