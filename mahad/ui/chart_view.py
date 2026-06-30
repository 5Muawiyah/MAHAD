from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Signal, Slot, QSize, QPointF
from PySide6.QtGui import QColor, QPainter, QIcon, QPixmap, QPen
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QPushButton,
                               QStackedWidget, QVBoxLayout, QWidget)

from mahad.engine.snapshot import RenderSnapshot
from mahad.ui import theme
from mahad.ui.widgets import LegendChip


class _PriceAxis(pg.AxisItem):
    # plain comma-grouped numbers, never an exponent

    def tickStrings(self, values, scale, spacing):  # noqa: N802 (pg override)
        out = []
        for v in values:
            av = abs(v)
            if av >= 1000:
                out.append(f"{v:,.0f}")
            elif av >= 1:
                out.append(f"{v:,.2f}")
            else:
                out.append(f"{v:.4f}")
        return out


class _SwitchBar(QWidget):
    # 2px accent loading filament along the plot's top edge

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setFixedHeight(2)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(30)
        self._timer.timeout.connect(self._tick)
        self.hide()

    def _tick(self) -> None:
        self._phase = (self._phase + 0.018) % 1.0
        self.update()

    def showEvent(self, e) -> None:  # noqa: N802
        self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e) -> None:  # noqa: N802
        self._timer.stop()
        super().hideEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        w = self.width()
        seg = max(60, int(w * 0.28))
        x = int(self._phase * (w + seg)) - seg
        p.fillRect(x, 0, seg, 2, QColor(theme.ACCENT))


def _fit_glyph() -> QPixmap:
    pm = QPixmap(28, 28)                       # 2x for HiDPI downscale
    pm.setDevicePixelRatio(2.0)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    pen = QPen(theme._qcolor(theme.TEXT_1))  # QColor("rgba(...)") is INVALID
    pen.setWidthF(1.5)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    p.setPen(pen)
    a, b, c = 2.0, 5.5, 12.0                   # corner arm: a to b along each edge
    for x0, y0, dx, dy in ((a, a, 1, 1), (c, a, -1, 1), (a, c, 1, -1), (c, c, -1, -1)):
        p.drawLine(QPointF(x0, y0), QPointF(x0 + (b - a) * dx, y0))
        p.drawLine(QPointF(x0, y0), QPointF(x0, y0 + (b - a) * dy))
    p.end()
    return pm


class _LoadOverlay(QWidget):
    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._label = QLabel("", self)
        self._label.setTextFormat(Qt.TextFormat.PlainText)   # symbol text
        self._label.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 14px;"
            f" color: {theme.TEXT_2}; background: transparent; }}")
        self.hide()

    def set_symbol(self, symbol: str) -> None:
        self._label.setText(f"Loading {symbol}...")
        self._label.adjustSize()
        self._center()

    def _center(self) -> None:
        lw, lh = self._label.width(), self._label.height()
        self._label.move((self.width() - lw) // 2, (self.height() - lh) // 2)

    def resizeEvent(self, e) -> None:  # noqa: N802
        self._center()
        super().resizeEvent(e)

    def paintEvent(self, _e) -> None:  # noqa: N802
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(11, 12, 15, 148))    # 0.58 alpha dim


class ChartView(QWidget):
    retry_requested = Signal()

    _LOADING, _EMPTY, _ERROR, _CHART = 0, 1, 2, 3

    def __init__(self, symbol: str, timeframe: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._symbol = symbol
        self._timeframe = timeframe
        # view-control state
        self._fit_pending = True          # fit on the next data frame
        self._user_locked = False         # a manual pan/zoom suppresses auto-fit
        self._ext: tuple[float, float, float, float] | None = None   # (x0,x1,ylo,yhi)

        self._pending_switch: str | None = None  # the awaited symbol
        self._switch_safety = QTimer(self)           # 10s wedge guard
        self._switch_safety.setSingleShot(True)
        self._switch_safety.setInterval(10_000)
        self._switch_safety.timeout.connect(self.cancel_switch)

        self._stack = QStackedWidget(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._stack)

        self._loading_label = self._centred("connecting...")
        self._stack.addWidget(self._loading_label)
        self._empty_label = QLabel(f"No data yet for {symbol}")
        self._empty_label.setTextFormat(Qt.TextFormat.PlainText)    # symbol text
        self._stack.addWidget(self._with_retry(self._empty_label))
        self._error_label = QLabel(f"Couldn't load {symbol}")
        self._error_label.setTextFormat(Qt.TextFormat.PlainText)    # symbol + provider text
        self._stack.addWidget(self._with_retry(self._error_label))
        self._stack.addWidget(self._build_chart_page())

        self._stack.setCurrentIndex(self._LOADING)

    # -- construction helpers ------------------------------------------------ #
    @staticmethod
    def _centred(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setProperty("tier", "2")
        return lbl

    def _with_retry(self, label: QLabel) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setProperty("tier", "2")
        btn = QPushButton("Retry")
        btn.clicked.connect(self.retry_requested)
        v.addWidget(label)
        v.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return page

    def _build_chart_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)

        # header: live mark + delta (left) | Fit + legend chips + stale badge (right)
        header = QWidget()
        header.setObjectName("PanelHead")
        h = QHBoxLayout(header)
        h.setContentsMargins(theme.S5, theme.S3, theme.S5, theme.S3)
        h.setSpacing(theme.S4)
        self._price_label = QLabel("")
        self._price_label.setProperty("mono", "true")     # hero price - SF Mono
        self._price_label.setStyleSheet(  # 30px hero
            f"QLabel {{ font-size: 30px; font-weight: 600; color: {theme.TEXT_1}; }}")
        self._usd_label = QLabel("")
        self._usd_label.setProperty("mono", "true")
        self._usd_label.setStyleSheet(                    # neutral unit, never coloured
            f"QLabel {{ font-size: 13px; color: {theme.TEXT_3}; }}")
        self._delta_label = QLabel("")
        self._delta_label.setProperty("mono", "true")
        # the delta names its basis per timeframe
        self._basis_label = QLabel("")
        self._basis_label.setProperty("mono", "true")
        self._basis_label.setStyleSheet(
            f"QLabel {{ font-size: 11px; color: {theme.TEXT_3}; }}")
        h.addWidget(self._price_label, 0, Qt.AlignmentFlag.AlignBottom)
        h.addWidget(self._usd_label, 0, Qt.AlignmentFlag.AlignBottom)    # baseline-seat satellites
        h.addWidget(self._delta_label, 0, Qt.AlignmentFlag.AlignBottom)
        h.addWidget(self._basis_label, 0, Qt.AlignmentFlag.AlignBottom)
        h.addStretch(1)
        self._sma_chip = LegendChip("SMA 20", theme.SMA_COLOR)
        self._ema_chip = LegendChip("EMA 12", theme.EMA_COLOR)
        self._sma_chip.hide()
        self._ema_chip.hide()
        self._stale_badge = QLabel("")
        self._stale_badge.setProperty("mono", "true")
        self._stale_badge.setStyleSheet(
            f"QLabel {{ color: {theme.AMBER}; font-weight: 600; }}")
        h.addWidget(self._sma_chip)
        h.addWidget(self._ema_chip)
        h.addWidget(self._stale_badge)
        _sep = QFrame()                                   # hairline before Fit
        _sep.setFixedSize(1, 22)
        _sep.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        h.addWidget(_sep)
        # Fit / auto-scale control (chart-local)
        self._fit_btn = QPushButton("Fit")
        self._fit_btn.setIcon(QIcon(_fit_glyph()))  # expand glyph
        self._fit_btn.setIconSize(QSize(14, 14))
        self._fit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._fit_btn.setToolTip("Fit the chart to the data (auto-scale)")
        self._fit_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.NESTED}; color: {theme.TEXT_1};"  # bold + white
            f" border: 1px solid {theme.HAIRLINE}; border-radius: {theme.R_CTRL}px;"
            f" padding: 4px 12px; font-size: 12px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {theme.TEXT_1}; border-color: {theme.DIVIDER}; }}")
        self._fit_btn.clicked.connect(self.request_fit)
        h.addWidget(self._fit_btn)
        v.addWidget(header)

        # price plot: comma-grouped price axis, real date x-axis
        self._price_plot = pg.PlotWidget(axisItems={
            "bottom": pg.DateAxisItem(orientation="bottom"),
            "left": _PriceAxis(orientation="left"),
        })
        # the hero owns the unit, so no rotated axis label
        self._price_plot.getPlotItem().hideButtons()    # hide auto-range "A"
        self._price_plot.showGrid(x=True, y=True, alpha=0.12)
        self._price_plot.getAxis("left").enableAutoSIPrefix(False)   # no exponent
        self._price_plot.getAxis("left").setTickFont(theme.mono_axis_font())
        self._price_plot.getAxis("bottom").setTickFont(theme.mono_axis_font())
        # a manual pan/zoom locks the view
        self._price_plot.getViewBox().setMenuEnabled(False)   # no View-All bypass
        self._price_plot.getViewBox().sigRangeChangedManually.connect(self._on_user_range)
        # overlays first, price last (on top)
        self._sma_curve = self._price_plot.plot([], [], pen=theme.sma_pen())
        self._ema_curve = self._price_plot.plot([], [], pen=theme.ema_pen())
        self._price_curve = self._price_plot.plot([], [], pen=theme.price_pen())
        v.addWidget(self._price_plot, 76)

        # RSI sub-plot: x-linked, fixed 0-100, dashed 30/70 guides
        self._rsi_plot = pg.PlotWidget(
            axisItems={"bottom": pg.DateAxisItem(orientation="bottom")})
        self._rsi_plot.setXLink(self._price_plot.getPlotItem())
        self._rsi_plot.setYRange(0, 100, padding=0)
        self._rsi_plot.setMouseEnabled(x=True, y=False)
        self._rsi_plot.getViewBox().setYRange(0, 100, padding=0)
        self._rsi_plot.getViewBox().setMenuEnabled(False)    # no View-All bypass
        self._rsi_plot.getViewBox().sigRangeChangedManually.connect(self._on_user_range)  # RSI pan locks too
        # a horizontal corner tag replaces the rotated axis label
        self._rsi_tag = pg.TextItem(text="RSI 14", color=(255, 255, 255, 128), anchor=(0, 0))
        self._rsi_tag.setFont(theme.mono_axis_font())
        self._rsi_plot.addItem(self._rsi_tag, ignoreBounds=True)
        # re-pin the tag to the visible gutter on every range change
        self._rsi_plot.getViewBox().sigRangeChanged.connect(self._place_rsi_tag)
        self._place_rsi_tag()
        self._rsi_plot.getPlotItem().hideButtons()       # hide auto-range "A"
        self._rsi_plot.getAxis("left").setTickFont(theme.mono_axis_font())
        self._rsi_plot.getAxis("bottom").setTickFont(theme.mono_axis_font())
        self._rsi_plot.getAxis("left").setTicks([[(30, "30"), (50, "50"), (70, "70")]])
        for level in (70, 30):
            self._rsi_plot.addItem(pg.InfiniteLine(pos=level, angle=0, pen=theme.guide_pen()))
        self._rsi_curve = self._rsi_plot.plot([], [], pen=theme.rsi_pen())
        v.addWidget(self._rsi_plot, 24)
        self._rsi_plot.hide()

        # loading overlays parented to the page so the dim covers all of it
        self._chart_page = page
        self._load_overlay = _LoadOverlay(page)
        self._switch_bar = _SwitchBar(page)
        return page

    # -- the symbol-switch loading treatment ------------------------ #
    def begin_switch(self, symbol: str) -> None:
        self._pending_switch = symbol
        self._switch_safety.start()
        # the hero never claims the old symbol's number for the new name
        self._price_label.setText("--")
        self._price_label.setStyleSheet(
            "QLabel { font-size: 30px; font-weight: 600;"
            " color: rgba(234,240,250,0.45); }")          # large-text AA class
        self._delta_label.setText("")
        self._stale_badge.setText("")                      # loading owns the plot
        if self._ext is not None:                          # a previous good frame exists
            self._stack.setCurrentIndex(self._CHART)
        else:
            self._stack.setCurrentIndex(self._LOADING)     # cold case
        self._load_overlay.set_symbol(symbol)
        self._place_switch_overlays()
        self._load_overlay.show()
        self._load_overlay.raise_()
        self._switch_bar.show()
        self._switch_bar.raise_()

    def switch_in_flight(self) -> bool:
        return self._pending_switch is not None

    def pending_symbol(self) -> str | None:
        return self._pending_switch

    @Slot()
    def cancel_switch(self) -> None:
        self._pending_switch = None
        self._switch_safety.stop()
        self._load_overlay.hide()
        self._switch_bar.hide()
        self._price_label.setStyleSheet(
            f"QLabel {{ font-size: 30px; font-weight: 600; color: {theme.TEXT_1}; }}")

    def _place_switch_overlays(self) -> None:
        if not hasattr(self, "_chart_page"):
            return
        r = self._chart_page.rect()
        self._load_overlay.setGeometry(r)
        # flush to the top edge of the plot area
        top = self._price_plot.geometry().top()
        self._switch_bar.setGeometry(0, top, r.width(), 2)

    def resizeEvent(self, e) -> None:  # noqa: N802
        super().resizeEvent(e)
        if self._pending_switch is not None:
            self._place_switch_overlays()

    @Slot()
    def show_no_symbol(self) -> None:
        # watchlist empty: invite the next action, name no symbol
        self._symbol = ""
        self._ext = None
        self._fit_pending = True
        self._empty_label.setText("Add a symbol to get started")
        self._stack.setCurrentIndex(self._EMPTY)

    # -- the one render slot ------------------------------------------------- #
    @Slot(object)
    def update_snapshot(self, snap: RenderSnapshot) -> None:
        match = False
        if self._pending_switch is not None:
            if snap.symbol and snap.symbol != self._pending_switch:
                return                                     # stale-symbol frame: discard
            if snap.symbol == self._pending_switch and not (snap.has_data or snap.error):
                return                                     # matching warming frame: hold
            if snap.symbol == self._pending_switch:
                match = True  # render now, clear after
        else:
            match = False
        new_symbol = snap.symbol or self._symbol
        if new_symbol != self._symbol:                    # symbol switch -> re-fit
            self._symbol = new_symbol
            self._fit_pending = True
            self._user_locked = False

        if snap.has_data:
            xs = [p[0] for p in snap.points]
            ys = [p[1] for p in snap.points]
            self._price_curve.setData(xs, ys)
            self._render_overlays(snap)
            self._render_rsi(snap)
            self._align_left_axes()  # shared axis gutter
            self._render_header(snap)
            self._ext = self._extents(snap, xs, ys)
            if self._fit_pending:
                self._apply_view(reset_y=True)            # full fit
                self._fit_pending = False
                self._user_locked = False
            elif not self._user_locked:
                self._apply_view(reset_y=False)           # bounded auto-scroll
            opacity = 1.0 if snap.live else 0.45          # dim the last good frame when stale
            for item in (self._price_curve, self._sma_curve, self._ema_curve):
                item.setOpacity(opacity)
            self._stale_badge.setText("" if snap.live else "STALE - last good price")
            self._stack.setCurrentIndex(self._CHART)
        elif snap.error:
            self._error_label.setText(f"Couldn't load {self._symbol} ({snap.error})")
            self._stack.setCurrentIndex(self._ERROR)
        else:
            self._empty_label.setText(f"No data yet for {self._symbol}")
            self._stack.setCurrentIndex(self._EMPTY)

        if match:  # clear after the chart has painted
            target = self._pending_switch
            QTimer.singleShot(0, lambda t=target: self._finish_switch(t))

    def _finish_switch(self, target: str) -> None:
        if self._pending_switch == target:
            self.cancel_switch()

    # -- view fitting + bounds ----------------------------------------------- #
    @staticmethod
    def _extents(snap: RenderSnapshot, xs, ys):
        all_y = list(ys)
        if snap.sma is not None and snap.sma.points:
            all_y += [v for _, v in snap.sma.points]
        if snap.ema is not None and snap.ema.points:
            all_y += [v for _, v in snap.ema.points]
        if not xs or not all_y:
            return None
        return (xs[0], xs[-1], min(all_y), max(all_y))

    def _apply_view(self, reset_y: bool) -> None:
        # fit X to the data extent and bound the ViewBox; reset_y also re-fits Y
        if self._ext is None:
            return
        x0, x1, ylo, yhi = self._ext
        vb = self._price_plot.getViewBox()

        xspan = x1 - x0
        if xspan <= 0:                                    # single point -> 1h window
            xpad = 3600.0
            x0v, x1v = x0 - xpad, x1 + xpad
        else:
            xpad = xspan * 0.10                           # headroom for live bars
            x0v, x1v = x0, x1
        yspan = yhi - ylo
        if yspan <= 0:
            yspan = max(abs(yhi) * 0.01, 1.0)

        vb.enableAutoRange(x=False)                       # we own X
        vb.setXRange(x0v, x1v, padding=0.02)              # latest near the right edge
        if reset_y:
            vb.enableAutoRange(y=True)
            vb.setAutoVisible(y=True)                     # Y re-fits to the visible X window

        limits = {
            "xMin": x0v - xpad, "xMax": x1v + xpad,
            "yMin": max(0.0, ylo - yspan),                # floor at >= 0
            "yMax": yhi + yspan,
            "maxYRange": yspan * 5.0,                     # cap zoom-out
        }
        if xspan > 0:
            limits["maxXRange"] = xspan * 1.5
        vb.setLimits(**limits)

    @Slot()
    def defer_fit(self) -> None:
        # arm a full fit for the next data frame, e.g. on a timeframe change
        self._user_locked = False
        self._fit_pending = True

    @Slot()
    def request_fit(self) -> None:
        self._user_locked = False
        if self._ext is not None:
            self._apply_view(reset_y=True)
        else:
            self._fit_pending = True

    def _place_rsi_tag(self, *_args) -> None:
        vb = self._rsi_plot.getViewBox()
        (x0, x1), (y0, y1) = vb.viewRange()
        self._rsi_tag.setPos(x0 + (x1 - x0) * 0.012, y1 - (y1 - y0) * 0.03)

    def _on_user_range(self, *_args) -> None:
        # manual pan/zoom suppresses auto-fit and auto-scroll until the next Fit
        self._user_locked = True

    # -- overlays / rsi / header ----------------------- #
    def _render_overlays(self, snap: RenderSnapshot) -> None:
        if snap.sma is not None and snap.sma.points:
            self._sma_curve.setData([p[0] for p in snap.sma.points],
                                    [p[1] for p in snap.sma.points])
            self._sma_chip.set_text(f"SMA {snap.sma.period}")
            self._sma_chip.show()
        else:
            self._sma_curve.setData([], [])
            self._sma_chip.setVisible(snap.sma is not None)   # warming up
            if snap.sma is not None:
                self._sma_chip.set_text(f"SMA {snap.sma.period}")

        if snap.ema is not None and snap.ema.points:
            self._ema_curve.setData([p[0] for p in snap.ema.points],
                                    [p[1] for p in snap.ema.points])
            self._ema_chip.set_text(f"EMA {snap.ema.period}")
            self._ema_chip.show()
        else:
            self._ema_curve.setData([], [])
            self._ema_chip.setVisible(snap.ema is not None)
            if snap.ema is not None:
                self._ema_chip.set_text(f"EMA {snap.ema.period}")

    def _align_left_axes(self) -> None:
        def _need(ax) -> int:
            try:
                off = ax.style.get("tickTextOffset", (5, 2))[0]
                tick = ax.style.get("tickLength", 5)
                return int(ax.textWidth + off + max(0, tick))
            except Exception:  # nosec B110 - degrade boundary
                return 56
        price_ax = self._price_plot.getAxis("left")
        rsi_ax = self._rsi_plot.getAxis("left")
        want = max(_need(price_ax), _need(rsi_ax), 56)
        try:
            price_ax.setWidth(want)
            rsi_ax.setWidth(want)
        except Exception:  # nosec B110 - degrade boundary
            pass

    def _render_rsi(self, snap: RenderSnapshot) -> None:
        rsi_on = snap.rsi is not None
        if rsi_on:
            try:
                self._rsi_tag.setText(f"RSI {snap.rsi.period}")
                self._place_rsi_tag()
            except Exception:  # nosec B110 - degrade boundary
                pass
        if rsi_on and snap.rsi.points:
            self._rsi_curve.setData([p[0] for p in snap.rsi.points],
                                    [p[1] for p in snap.rsi.points])
            self._rsi_curve.setOpacity(1.0 if snap.live else 0.45)
        else:
            self._rsi_curve.setData([], [])
        self._rsi_plot.setVisible(rsi_on)
        # quiet the price x labels when RSI carries the shared axis
        try:
            self._price_plot.getAxis("bottom").setStyle(showValues=not rsi_on)
        except Exception:  # nosec B110 - degrade boundary
            pass

    def _render_header(self, snap: RenderSnapshot) -> None:
        last = snap.points[-1][1]
        self._price_label.setText(f"{last:,.2f}")
        self._usd_label.setText("USD")                         # neutral unit
        if len(snap.points) >= 2 and snap.points[-2][1]:
            prev = snap.points[-2][1]
            move = last - prev
            pct = move / prev * 100.0
            # classify on the displayed values: a display-zero is neutral
            move_txt, pct_txt = f"{abs(move):,.2f}", f"{abs(pct):.2f}"
            shown_zero = move_txt == "0.00" and pct_txt == "0.00"
            if shown_zero:
                colour, sign = theme.TEXT_2, ""
                move_txt, pct_txt = "0.00", "0.00"
            elif pct > 0:
                colour, sign = theme.GREEN, "+"
            else:
                colour, sign = theme.RED, "-"
            self._delta_label.setStyleSheet(
                f"QLabel {{ color: {colour}; font-size: 14px; }}")
            # absolute move + percent
            self._delta_label.setText(f"{sign}{move_txt} ({sign}{pct_txt}%)")
            self._basis_label.setText("vs prev close" if snap.timeframe == "1d"
                                      else ("vs prev bar" if snap.timeframe else ""))
            # note that intraday stock bars are sampled from live quotes
            if snap.timeframe in ("1m", "1h") and "/" not in (snap.symbol or ""):
                self._basis_label.setToolTip(
                    "Intraday stock bars are sampled from live quotes, "
                    "not exchange aggregates (source: Finnhub).")
            else:
                self._basis_label.setToolTip("")
        else:
            self._delta_label.setText("")
            self._basis_label.setText("")
