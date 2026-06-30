from __future__ import annotations

from decimal import Decimal
from typing import Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QSizePolicy, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from mahad.data.portfolio_view import PortfolioView
from mahad.engine.portfolio import money
from mahad.ui import theme

_COLS = ["Symbol", "Qty", "Avg cost", "Mark", "Unrealised P&L", "Value"]


def _money(d) -> str:
    return f"{money(d):,.2f}"          # ledger rounds HALF_UP


def _signed(d) -> str:
    d = money(d)
    if d == 0:
        return "0.00"                       # zero stays unsigned
    return f"+{d:,.2f}" if d > 0 else f"{d:,.2f}"


def _qty(d) -> str:
    # whole shares show bare, fractional keep 2 decimals
    q = Decimal(d).normalize()
    if q == q.to_integral_value():
        return format(q.to_integral_value(), "f")
    if -q.as_tuple().exponent < 2:
        return format(q.quantize(Decimal("0.01")), "f")
    return format(q, "f")


class PortfolioPanel(QWidget):

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("DockPanel")          # transparent against the dock
        self._starting_cash = Decimal("100000")
        root = QVBoxLayout(self)
        root.setContentsMargins(theme.S4, theme.S4, theme.S4, theme.S4)
        root.setSpacing(theme.S4)

        stats = QHBoxLayout()
        stats.setSpacing(theme.S8)
        self._v_cash = self._stat(
            stats, "Cash",
            "Cash = the simulated USD ledger balance (exact). Updates on each "
            "fill; not marked to market.")
        self._v_value = self._stat(
            stats, "Total value",
            "Total value = cash + sum(position value at the latest mark), "
            "marked to market live; shows - until the first marks arrive.")
        div = QFrame(); div.setFixedWidth(1)
        div.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        stats.addWidget(div)
        self._v_realised = self._stat(
            stats, "Realised P&L",
            "Realised P&L = profit/loss booked on closed quantity (exact "
            "ledger, since inception).")
        self._v_unreal = self._stat(
            stats, "Unrealised P&L",
            "Unrealised P&L = sum(qty x (mark - avg cost)) at the latest "
            "mark; live, moves with the marks.")
        self._v_total = self._stat(
            stats, "Total P&L",
            "Total P&L = realised + unrealised; signed (green up, red down). "
            "Simulated USD portfolio.")
        stats.addStretch(1)
        from PySide6.QtWidgets import QPushButton
        self._gbp_btn = QPushButton("GBP")
        self._gbp_btn.setObjectName("CsvChip")
        self._gbp_btn.setFixedSize(44, 22)
        self._gbp_btn.setCheckable(True)
        self._gbp_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._gbp_btn.setToolTip(
            "GBP view (display only): values the book at the ECB USD->GBP "
            "reference rate. The ledger, fills, and every figure above "
            "remain USD - no FX conversion touches the accounts.")
        self._gbp_btn.toggled.connect(self._on_gbp_toggled)
        self._gbp_btn.setEnabled(False)                    # stays off until a rate arrives
        stats.addWidget(self._gbp_btn)
        root.addLayout(stats)
        self._gbp_line = QLabel("")
        self._gbp_line.setObjectName("CtxValMuted")
        self._gbp_line.setTextFormat(Qt.TextFormat.PlainText)
        self._gbp_line.hide()
        root.addWidget(self._gbp_line)

        self._table = QTableWidget(0, len(_COLS))
        self._table.setObjectName("DataTable")
        self._table.setHorizontalHeaderLabels([c.upper() for c in _COLS])
        for _c in range(len(_COLS)):                       # Symbol left, numerics right
            _it = self._table.horizontalHeaderItem(_c)
            _al = (Qt.AlignmentFlag.AlignLeft if _c == 0 else Qt.AlignmentFlag.AlignRight)
            _it.setTextAlignment(int(_al | Qt.AlignmentFlag.AlignVCenter))
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(False)
        self._table.setAlternatingRowColors(True)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for i in range(1, len(_COLS)):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        root.addWidget(self._table, 1)

        self._empty = QLabel(self._empty_text())
        self._empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-family: {theme.FONT_MONO};"
            f" font-size: 13px; padding: {theme.S8}px 0;"
            f" background: {theme.PLOT}; border: 1px solid {theme.HAIRLINE};"
            f" border-radius: {theme.R_CTRL}px; }}")
        root.addWidget(self._empty, 1)
        self._table.hide()

    def _stat(self, row: QHBoxLayout, label: str, tip: str = "") -> QLabel:
        col = QVBoxLayout(); col.setSpacing(2)
        lab = QLabel(label); lab.setObjectName("StatLabel")
        val = QLabel("-"); val.setObjectName("StatValue")
        if tip:
            lab.setToolTip(tip)
            val.setToolTip(tip)
        col.addWidget(lab)
        col.addWidget(val)
        row.addLayout(col)
        return val

    def _on_gbp_toggled(self, _checked: bool) -> None:
        self._render_gbp_line()

    def _render_gbp_line(self) -> None:
        rate = getattr(self, "_gbp_rate", None)
        value = getattr(self, "_gbp_value", None)
        if not self._gbp_btn.isChecked() or rate is None or value is None:
            self._gbp_line.hide()
            return
        gbp = value * rate
        note = getattr(self, "_gbp_note", "")
        self._gbp_line.setText(
            f"GBP view: {gbp:,.2f} GBP at {rate:.4f} · ECB reference rate, "
            f"as of {getattr(self, '_gbp_as_of', '')} · ledger remains USD"
            + (f" · {note}" if note else ""))
        self._gbp_line.show()

    def _empty_text(self) -> str:
        return f"No open positions - starting cash {_money(self._starting_cash)}"

    @Slot(object)
    def set_view(self, view: object) -> None:
        if not isinstance(view, PortfolioView):
            return
        self._starting_cash = view.starting_cash
        self._v_cash.setText(_money(view.cash))
        self._v_value.setText(_money(view.total_value) if view.has_marks else "-")
        # stash the GBP inputs; actual render waits on the toggle and a rate
        self._gbp_rate = view.gbp_rate
        self._gbp_as_of = view.gbp_as_of
        self._gbp_note = view.gbp_note
        self._gbp_value = (float(view.total_value) if view.has_marks else None)
        self._gbp_btn.setEnabled(view.gbp_rate is not None)
        self._render_gbp_line()
        self._set_pnl(self._v_realised, view.realised_pnl)
        if view.has_marks:
            self._set_pnl(self._v_unreal, view.unrealised_pnl)
            self._set_pnl(self._v_total, view.total_pnl)
        else:
            self._v_unreal.setText("-"); self._v_unreal.setObjectName("StatValue")
            self._v_total.setText("-"); self._v_total.setObjectName("StatValue")
            self._restyle(self._v_unreal); self._restyle(self._v_total)

        if view.is_empty:
            self._empty.setText(self._empty_text())
            self._empty.show()
            self._table.hide()
            return
        self._empty.hide()
        self._table.show()
        self._fill_table(view)

    def _set_pnl(self, label: QLabel, value) -> None:
        d = Decimal(value)
        label.setText(_signed(d))
        label.setObjectName("StatValuePos" if d > 0 else
                            ("StatValueNeg" if d < 0 else "StatValue"))   # flat gets no colour
        self._restyle(label)

    @staticmethod
    def _restyle(w: QWidget) -> None:
        w.style().unpolish(w)
        w.style().polish(w)

    def _fill_table(self, view: PortfolioView) -> None:
        self._table.setRowCount(len(view.positions))
        for r, p in enumerate(view.positions):
            cells = [
                (p.symbol, Qt.AlignmentFlag.AlignLeft, None),
                (_qty(p.quantity), Qt.AlignmentFlag.AlignRight, None),
                (_money(p.avg_cost), Qt.AlignmentFlag.AlignRight, None),
                (_money(p.mark) if p.mark is not None else "-", Qt.AlignmentFlag.AlignRight, None),
                (_signed(p.unrealised) if p.unrealised is not None else "as of last price",
                 Qt.AlignmentFlag.AlignRight,
                 (None if (p.unrealised is not None and Decimal(p.unrealised) == 0)
                  else (theme.GREEN if (p.unrealised is not None and Decimal(p.unrealised) > 0)
                        else theme.RED)) if p.unrealised is not None else theme.TEXT_3),
                (_money(p.value) if p.value is not None else "-", Qt.AlignmentFlag.AlignRight, None),
            ]
            for c, (text, align, colour) in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setTextAlignment(int(align | Qt.AlignmentFlag.AlignVCenter))
                if colour is not None:
                    from PySide6.QtGui import QColor
                    item.setForeground(QColor(theme._qcolor(colour)))
                self._table.setItem(r, c, item)
