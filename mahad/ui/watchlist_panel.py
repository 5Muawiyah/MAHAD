from __future__ import annotations

from PySide6.QtCore import Qt, QTimer, Signal, Slot
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QMenu,
                               QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from mahad.data.symbols import (WatchlistRow, WatchlistState, classify,
                                effective_active, normalize_symbol)
from mahad.ui import theme
from mahad.ui.widgets import AssetGlyph, Chevron, StatusDot


class _Row(QFrame):
    selected = Signal(str)
    removed = Signal(str)

    def __init__(self, row: WatchlistRow, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._symbol = row.symbol
        self._active = row.active
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_active_style(row.active)

        self.setFixedHeight(52)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(theme.S4 - 3, theme.S1, theme.S3, theme.S1)
        lay.setSpacing(theme.S3)

        self._dot = StatusDot(row.dot)
        lay.addWidget(self._dot)

        asset_class, _quote = classify(row.symbol)
        lay.addWidget(AssetGlyph(asset_class))

        col_host = QWidget()
        col_host.setMinimumWidth(72)
        col_host.setStyleSheet("background: transparent;")
        col = QVBoxLayout(col_host)
        col.setContentsMargins(0, 0, 0, 0)
        col.setSpacing(1)
        col.addStretch(1)
        sym = QLabel(row.symbol)
        sym.setTextFormat(Qt.TextFormat.PlainText)        # symbol is external-origin, never rich text
        sym.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 14px;"
            f" font-weight: 600; color: {theme.TEXT_1}; background: transparent; }}")
        col.addWidget(sym)
        self._sub = QLabel("")
        self._sub.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 10px;"
            f" color: {theme.TEXT_3}; background: transparent; }}")
        col.addWidget(self._sub)
        col.addStretch(1)
        self._apply_sub(row)
        lay.addWidget(col_host)

        lay.addStretch(1)

        self._mark = QLabel(f"{row.mark:,.2f}" if (row.has_quote and row.mark is not None) else "-")
        self._mark.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self._mark)
        self._style_mark(row, row.active)

        # a visible remove chip, not an invisible hover target
        rm = QPushButton("✕")
        rm.setToolTip(f"Remove {row.symbol}")
        rm.setFixedSize(22, 22)
        rm.setCursor(Qt.CursorShape.PointingHandCursor)
        rm.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {theme.HAIRLINE};"
            f" color: {theme.TEXT_2}; font-family: {theme.FONT_SANS}; font-size: 12px;"
            f" border-radius: 6px; padding: 0; }}"
            f"QPushButton:hover {{ background: {theme.NESTED}; color: {theme.TEXT_1};"
            f" border-color: {theme.DIVIDER}; }}")
        rm.clicked.connect(lambda: self.removed.emit(self._symbol))
        lay.addWidget(rm)

    def symbol(self) -> str:
        return self._symbol

    def _apply_sub(self, row: WatchlistRow) -> None:
        # status token under the symbol; hidden once the quote is live
        if not row.has_quote and getattr(row, "needs_key", False):
            # TEXT_2 to clear the AA contrast floor over the active backing
            self._sub.setStyleSheet(
                f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 10px;"
                f" color: {theme.TEXT_2}; background: transparent; }}")
            self._sub.setText("needs key")
            self._sub.setVisible(True)
            self.setToolTip("Needs a free Finnhub key (finnhub.io) - add it "
                            "to .env and restart. Crypto runs without it.")
        elif not row.has_quote:
            self._sub.setStyleSheet(
                f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 10px;"
                f" color: {theme.TEXT_3}; background: transparent; }}")
            self._sub.setText("warming up")
            self._sub.setVisible(True)
            self.setToolTip("Warming up - no quote yet")
        elif row.dot == "stale":
            self._sub.setText("last known")
            self._sub.setVisible(True)
            self.setToolTip("Last known price - not continuously polled")
        else:
            self._sub.setVisible(False)
            self.setToolTip("")

    def _style_mark(self, row: WatchlistRow, active: bool) -> None:
        # stale marks drop to TEXT_2 so the read survives greyscale
        if not row.has_quote:
            colour = theme.TEXT_3
        elif row.dot == "stale":
            colour = theme.TEXT_2
        else:
            colour = theme.TEXT_1
        weight = 600 if active else 400
        self._mark.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 14px;"
            f" font-weight: {weight}; color: {colour}; background: transparent; }}")

    def update_row(self, row: WatchlistRow, active: bool) -> None:
        # in-place refresh, no widget teardown
        self._dot.set_state(row.dot)
        self._mark.setText(f"{row.mark:,.2f}" if (row.has_quote and row.mark is not None) else "-")
        self._apply_sub(row)
        self._style_mark(row, active)
        self.set_active(active)

    def contextMenuEvent(self, event) -> None:  # noqa: N802 (Qt override)
        menu = QMenu(self)
        if not self._active:
            act_set = menu.addAction("Set as active")
            act_set.triggered.connect(lambda: self.selected.emit(self._symbol))
        act_rm = menu.addAction("Remove")
        act_rm.triggered.connect(lambda: self.removed.emit(self._symbol))
        menu.exec(event.globalPos())

    def set_active(self, active: bool) -> None:
        self._apply_active_style(active)

    def _apply_active_style(self, active: bool) -> None:
        # transparent (not absent) border on the idle state so width never shifts
        if active:
            self.setStyleSheet(
                f"_Row {{ background: {theme.NESTED}; border-radius: {theme.R_ATOM}px;"
                f" border: 1px solid {theme.DIVIDER}; }}")
        else:
            self.setStyleSheet(
                f"_Row {{ background: transparent; border-radius: {theme.R_ATOM}px;"
                f" border: 1px solid transparent; }}"
                f"_Row:hover {{ background: {theme.NESTED}; }}")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.selected.emit(self._symbol)
        super().mousePressEvent(event)


class WatchlistPanel(QFrame):
    add_requested = Signal(str)
    remove_requested = Signal(str)
    select_requested = Signal(str)
    collapse_toggled = Signal(bool)

    _PENDING_SELECT_TIMEOUT_MS = 10_000        # revert the optimistic accent if no confirmation lands

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Panel")
        self._pending: str | None = None       # awaiting the add to land, then clear the input
        self._pending_select: str | None = None  # optimistic accent, awaiting worker confirmation
        self._pending_timer = QTimer(self)
        self._pending_timer.setSingleShot(True)
        self._pending_timer.timeout.connect(self._clear_pending_select)
        self._state_active: str | None = None
        self._marks: dict[str, object] = {}     # symbol -> mark, for the collapsed summary
        self._collapsed = False
        self._row_symbols: tuple[str, ...] = ()
        self._row_widgets: list[_Row] = []
        self._row_sig: tuple = ()              # (symbol, has_quote) per row; the fast-path key

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        head = QWidget()
        head.setObjectName("PanelHead")
        hh = QHBoxLayout(head)
        hh.setContentsMargins(theme.S5, theme.S4, theme.S5, theme.S4)
        self._chevron = Chevron()
        self._chevron.clicked.connect(self.toggle_collapsed)
        title = QLabel("Watchlist")
        title.setObjectName("PanelTitle")
        self._count = QLabel("0")
        self._count.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 11px; color: {theme.TEXT_3};"
            f" background: {theme.NESTED}; border-radius: 9px; padding: 1px 8px; }}")
        hh.addWidget(self._chevron)
        hh.addSpacing(theme.S2)
        hh.addWidget(title)
        hh.addSpacing(theme.S3)
        hh.addWidget(self._count)
        hh.addStretch(1)
        self._summary = QLabel("")
        self._summary.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 12.5px;"
            f" color: {theme.TEXT_2}; background: transparent; }}")
        self._summary.hide()
        hh.addWidget(self._summary)
        head.setCursor(Qt.CursorShape.PointingHandCursor)
        self._head = head
        head.mousePressEvent = self._on_head_press           # click anywhere on the header to toggle
        root.addWidget(head)

        add_box = QWidget()
        add_box.setObjectName("WlAddBox")
        self._add_box = add_box
        ab = QVBoxLayout(add_box)
        ab.setContentsMargins(theme.S4, theme.S4, theme.S4, theme.S2)
        ab.setSpacing(theme.S2)
        field_row = QHBoxLayout()
        field_row.setSpacing(theme.S2)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Add symbol")
        self._input.returnPressed.connect(self._submit)
        self._input.textEdited.connect(lambda _t: self._clear_error())
        add_btn = QPushButton("+")
        add_btn.setFixedWidth(40)
        add_btn.clicked.connect(self._submit)
        field_row.addWidget(self._input)
        field_row.addWidget(add_btn)
        ab.addLayout(field_row)
        self._error = QLabel("")
        self._error.setTextFormat(Qt.TextFormat.PlainText)
        self._error.setWordWrap(True)
        self._error.setStyleSheet(
            f"QLabel {{ color: {theme.RED}; font-size: 12px; background: transparent; }}")
        self._error.hide()
        ab.addWidget(self._error)
        root.addWidget(add_box)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rows_host = QWidget()
        self._rows_host.setObjectName("WlRowsHost")   # near-solid backing comes from the app QSS
        self._rows_layout = QVBoxLayout(self._rows_host)
        self._rows_layout.setContentsMargins(theme.S2, 0, theme.S3, theme.S3)
        self._rows_layout.setSpacing(2)
        self._rows_layout.addStretch(1)
        self._scroll.setWidget(self._rows_host)
        # three whole 52px rows so the list never cuts a row
        self._scroll.setMinimumHeight(160)
        root.addWidget(self._scroll, 1)

    # -- intents ------------------------------------------------------------- #
    @Slot(str)
    def _on_row_selected(self, symbol: str) -> None:
        # accent the click immediately; the worker remains authoritative
        self._pending_select = symbol
        self._pending_timer.start(self._PENDING_SELECT_TIMEOUT_MS)
        self._restyle_rows()
        self.select_requested.emit(symbol)

    def clear_pending_select(self) -> None:
        # called when the window decides to ignore a selection we accented
        self._pending_timer.stop()
        self._clear_pending_select()

    def _clear_pending_select(self) -> None:
        self._pending_select = None
        self._pending_timer.stop()
        self._restyle_rows()

    def _restyle_rows(self) -> None:
        shown = effective_active(self._pending_select, self._state_active,
                                 self._row_symbols)
        for w in self._row_widgets:
            w.set_active(w.symbol() == shown)

    # -- collapse ------------------------------------------------------------ #
    def _on_head_press(self, _event) -> None:
        self.toggle_collapsed()

    @Slot()
    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
        self.collapse_toggled.emit(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        self._collapsed = collapsed
        self._chevron.set_expanded(not collapsed)
        self._add_box.setVisible(not collapsed)
        self._scroll.setVisible(not collapsed)
        self._summary.setVisible(collapsed)
        if collapsed:
            self._refresh_summary()

    def is_collapsed(self) -> bool:
        return self._collapsed

    def _refresh_summary(self) -> None:
        sym = self._state_active
        if not sym:
            self._summary.setText("")
            return
        mark = self._marks.get(sym)
        self._summary.setText(f"{sym}  {mark:,.2f}" if mark is not None else f"{sym}  -")

    def _submit(self) -> None:
        text = self._input.text().strip()
        if not text:
            return
        self._pending = normalize_symbol(text)
        # neutral hint (not an error) while the worker probes the symbol
        self._error.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-size: 12px; background: transparent; }}")
        self._error.setText(f"checking {self._pending}...")
        self._error.show()
        self.add_requested.emit(text)

    def _clear_error(self) -> None:
        self._error.hide()
        self._error.setText("")
        self._input.setProperty("error", False)
        self._restyle(self._input)

    @staticmethod
    def _restyle(widget: QWidget) -> None:
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    # -- slots from the worker ---------------------------------------------- #
    @Slot(str, str)
    def show_remove_error(self, _symbol: str, reason: str) -> None:
        self._error.setStyleSheet(                         # force red, in case a neutral hint style lingers
            f"QLabel {{ color: {theme.RED}; font-size: 12px; background: transparent; }}")
        self._error.setText(reason)
        self._error.show()

    @Slot(str, str)
    def show_add_error(self, text: str, reason: str) -> None:
        self._pending = None
        self._input.setText(text)                        # keep what the user typed
        self._input.setProperty("error", True)
        self._restyle(self._input)
        self._error.setStyleSheet(
            f"QLabel {{ color: {theme.RED}; font-size: 12px; background: transparent; }}")
        self._error.setText(reason)
        self._error.show()

    @Slot(object)
    def set_state(self, state: WatchlistState) -> None:
        # once the submitted add shows up in the state, clear the input
        if self._pending is not None and any(r.symbol == self._pending for r in state.rows):
            self._input.clear()
            self._clear_error()
            self._pending = None

        # a state that confirms our optimistic selection clears it
        self._state_active = state.active
        self._row_symbols = tuple(r.symbol for r in state.rows)
        if self._pending_select is not None and state.active == self._pending_select:
            self._pending_select = None
            self._pending_timer.stop()

        self._count.setText(str(len(state.rows)))
        self._marks = {r.symbol: (r.mark if r.has_quote else None) for r in state.rows}
        if self._collapsed:
            self._refresh_summary()

        # same set of rows: update them in place rather than rebuilding
        new_sig = tuple((r.symbol, r.has_quote) for r in state.rows)
        if (state.rows and new_sig == self._row_sig
                and len(self._row_widgets) == len(state.rows)):
            shown = effective_active(self._pending_select, state.active,
                                     self._row_symbols)
            for w, row in zip(self._row_widgets, state.rows, strict=True):
                w.update_row(row, active=(row.symbol == shown))
            return

        # otherwise tear down and rebuild; the list is small so this is cheap
        while self._rows_layout.count():
            item = self._rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._row_widgets = []

        if not state.rows:
            empty = QLabel("Add a symbol to get started")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setProperty("tier", "3")
            empty.setStyleSheet(
                f"QLabel {{ color: {theme.TEXT_3}; background: transparent; }}")
            self._rows_layout.addStretch(1)
            self._rows_layout.addWidget(empty)
            self._rows_layout.addStretch(1)
            return

        shown = effective_active(self._pending_select, state.active,
                                 self._row_symbols)
        self._row_sig = tuple((r.symbol, r.has_quote) for r in state.rows)
        for row in state.rows:
            w = _Row(row)
            w.set_active(row.symbol == shown)              # shown folds in any pending selection
            w.selected.connect(self._on_row_selected)
            w.removed.connect(self.remove_requested)
            self._rows_layout.addWidget(w)
            self._row_widgets.append(w)
        self._rows_layout.addStretch(1)
