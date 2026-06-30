from __future__ import annotations

from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, Signal, Slot
from PySide6.QtWidgets import (QAbstractItemView, QFileDialog, QHBoxLayout,
                               QHeaderView, QLabel, QPushButton, QSizePolicy,
                               QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from mahad.data.portfolio_view import PortfolioView
from mahad.engine.portfolio import build_trade_csv, fmt_ts, money
from mahad.ui import theme

_COLS = ["Time", "Symbol", "Side", "Qty", "Fill price", "Avg cost at fill", "Realised P&L"]
_CLEAR_REASON = "Export the log before clearing"


def _money(d) -> str:
    return f"{money(d):,.2f}"          # ledger HALF_UP


def _qty(d) -> str:
    # integral shown bare, fractional padded to at least 2 places
    q = Decimal(d).normalize()
    if q == q.to_integral_value():
        return format(q.to_integral_value(), "f")
    if -q.as_tuple().exponent < 2:
        return format(q.quantize(Decimal("0.01")), "f")
    return format(q, "f")


class TradeLogPanel(QWidget):

    clear_requested = Signal(int)        # exported trade count
    exported = Signal(bool)                       # export-success state

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DockPanel")          # transparent on the dock
        self._view: Optional[PortfolioView] = None
        self._export_ok = False
        self._exported_count = -1
        self._trade_sig = None               # skip redundant rebuilds
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.S4, theme.S3, theme.S4, theme.S4)
        root.setSpacing(theme.S3)

        # action row: Clear, reason chip, Export CSV
        bar = QHBoxLayout()
        bar.setSpacing(theme.S2)
        self._clear = QPushButton("Clear trade log")
        self._clear.clicked.connect(self._on_clear)
        bar.addWidget(self._clear)
        self._reason = QLabel(_CLEAR_REASON)
        # quiet grey at rest
        self._reason.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 11.5px; background: transparent; }}")
        bar.addWidget(self._reason)
        bar.addStretch(1)
        self._err = QLabel("")
        self._err.setStyleSheet(f"QLabel {{ color: {theme.RED}; font-size: 12px; }}")
        self._err.hide()
        bar.addWidget(self._err)
        self._export = QPushButton("Export CSV")
        self._export.setProperty("variant", "primary")
        self._export.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export.clicked.connect(self._on_export)
        bar.addWidget(self._export)
        root.addLayout(bar)

        # trades table
        self._table = QTableWidget(0, len(_COLS))
        self._table.setObjectName("DataTable")
        self._table.setHorizontalHeaderLabels([c.upper() for c in _COLS])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        # numeric headers right-aligned, text headers left
        for i, name in enumerate(_COLS):
            item = self._table.horizontalHeaderItem(i)
            if item is not None:
                numeric = name not in ("Time", "Symbol", "Side")
                item.setTextAlignment(
                    (Qt.AlignmentFlag.AlignRight if numeric else Qt.AlignmentFlag.AlignLeft)
                    | Qt.AlignmentFlag.AlignVCenter)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table, 1)

        self._empty = QLabel("No trades yet.")
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 13px; padding: {theme.S8}px 0; }}")
        root.addWidget(self._empty, 1)
        self._table.hide()
        self._sync_clear()

    # -- state in ------------------------------------------------------------ #
    @Slot(object)
    def set_view(self, view: object) -> None:
        if not isinstance(view, PortfolioView):
            return
        self._view = view
        count = len(view.trades)
        if count != self._exported_count:          # changed trades invalidate the export
            self._export_ok = False
        sig = (count, view.trades[-1].ts if count else None)   # change signature
        changed = sig != self._trade_sig
        self._trade_sig = sig
        if count == 0:
            self._empty.show(); self._table.hide()
        else:
            self._empty.hide(); self._table.show()
            if changed:                            # rebuild only on change
                self._fill_table(view)
        self._sync_clear()

    def _fill_table(self, view: PortfolioView) -> None:
        self._table.setRowCount(len(view.trades))
        from PySide6.QtGui import QColor
        for r, t in enumerate(view.trades):
            side_colour = theme.GREEN if t.side == "buy" else theme.RED
            _r = Decimal(t.realised_pnl)
            if t.side == "buy":
                realised = "-"
            else:
                realised = "0.00" if _r == 0 else f"{_r:+,.2f}"   # zero unsigned and neutral
            cells = [
                (fmt_ts(t.ts), Qt.AlignmentFlag.AlignLeft, theme.TEXT_2),
                (t.symbol, Qt.AlignmentFlag.AlignLeft, None),
                (t.side, Qt.AlignmentFlag.AlignLeft, side_colour),
                (_qty(t.quantity), Qt.AlignmentFlag.AlignRight, None),
                (_money(t.fill_price), Qt.AlignmentFlag.AlignRight, None),
                (_money(t.avg_cost_at_fill), Qt.AlignmentFlag.AlignRight, None),
                (realised, Qt.AlignmentFlag.AlignRight,
                 (theme.TEXT_3 if t.side == "buy"
                  else (None if _r == 0 else (theme.GREEN if _r > 0 else theme.RED)))),
            ]
            for c, (text, align, colour) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
                if colour is not None:
                    item.setForeground(QColor(theme._qcolor(colour)))
                self._table.setItem(r, c, item)

    # -- export / clear ------------------------------------------------------ #
    def request_export(self) -> None:
        # entry point wired to the keyboard shortcut
        self._on_export()

    def _on_export(self) -> None:
        if self._view is None or not self._view.trades:
            self._err.setText("No trades to export."); self._err.show()
            return
        trades = self._view.trades                  # snapshot before the dialog
        starting_cash = self._view.starting_cash    # snapshot before the dialog
        exported_count = len(trades)
        self._export.setEnabled(False)              # single-flight
        try:
            path, _ = QFileDialog.getSaveFileName(self, "Export trade log CSV",
                                                  "mahad-trades.csv", "CSV files (*.csv)")
            if not path:                            # cancelled, retain log
                return
            try:
                csv_text = build_trade_csv(trades, starting_cash)
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_text)
            except Exception as exc:                # keep failures out of the event loop
                self._err.setText(f"Could not write CSV ({exc}). Try another path.")
                self._err.show()
                return
            self._err.hide()
            self._export_ok = True
            self._exported_count = exported_count
            self.exported.emit(True)
            self._sync_clear()
        finally:
            self._export.setEnabled(True)

    def _on_clear(self) -> None:
        if not self._export_ok or self._view is None:
            return
        self._clear.setEnabled(False)               # single-flight
        self.clear_requested.emit(self._exported_count)   # clear only the exported set

    def export_succeeded(self) -> bool:
        return self._export_ok

    def _sync_clear(self) -> None:
        has_trades = bool(self._view and self._view.trades)
        enabled = self._export_ok and has_trades
        self._clear.setEnabled(enabled)
        self._reason.setVisible(has_trades and not enabled)   # always-visible chip
