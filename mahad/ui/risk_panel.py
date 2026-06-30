from __future__ import annotations

from typing import ClassVar, Optional

from PySide6.QtCore import QSize, QPointF, Qt
from PySide6.QtGui import QPainter, QPen, QPolygonF
from PySide6.QtWidgets import (QSizePolicy, QFrame, QGridLayout, QHBoxLayout, QLabel,
                               QVBoxLayout, QWidget)

from mahad.data.context_view import MarketContextView
from mahad.data.portfolio_view import (RiskAnalyticsView, RiskView,
                                       analytics_summary, backtest_chip_text,
                                       build_risk_snapshot_csv,
                                       build_value_history_csv)
from mahad.engine.portfolio import money
from mahad.engine.risk import VOL_CAVEAT
from mahad.ui import theme
from mahad.ui.widgets import Chevron, StatusDot

EMPTY_TEXT = "Place a trade to populate risk metrics."


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")  # locale-proof


def _fmt_ts(ts: Optional[float]) -> str:
    # today as HH:MM:SS, older as "Jun 03 14:02"
    if ts is None:
        return "-"
    import time as _t
    lt = _t.localtime(float(ts))
    now = _t.localtime()
    if (lt.tm_year, lt.tm_yday) == (now.tm_year, now.tm_yday):
        return _t.strftime("%H:%M:%S", lt)
    return f"{_MONTHS[lt.tm_mon - 1]} {lt.tm_mday:02d} {_t.strftime('%H:%M', lt)}"


class _WrapMinLabel(QLabel):
    # wrapping label whose minimum height is its wrapped height

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        base = super().minimumSizeHint()
        if self.wordWrap() and self.width() > 0:
            h = self.heightForWidth(self.width())
            if h > 0:
                return QSize(base.width(), h)
        return base

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(e)
        self.updateGeometry()           # re-query wrapped height


class _ElideRightLabel(QLabel):
    # elides right, keeps the full text in the tooltip

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._full = ""
        self.setMinimumWidth(0)

    def minimumSizeHint(self):  # noqa: N802 (Qt override)
        base = super().minimumSizeHint()
        return QSize(0, base.height())

    def set_full_text(self, text: str) -> None:
        self._full = text
        self.setToolTip(text)
        self._apply()

    def _apply(self) -> None:
        from PySide6.QtGui import QFontMetrics
        fm = QFontMetrics(self.font())
        super().setText(fm.elidedText(self._full, Qt.TextElideMode.ElideRight,
                                      max(0, self.width())))

    def resizeEvent(self, e) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(e)
        self._apply()


class Sparkline(QWidget):
    # value-history sparkline; readable from shape, not colour

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._series: tuple[float, ...] = ()
        self._trough_idx: Optional[int] = None
        self.setMinimumHeight(54)
        self.setMaximumHeight(64)

    def set_data(self, series, trough_idx: Optional[int] = None) -> None:
        self._series = tuple(float(v) for v in (series or ()))
        self._trough_idx = trough_idx
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, pad = self.width(), self.height(), 6.0
        series = self._series
        if len(series) < 2:                                  # flat baseline
            pen = QPen(theme._qcolor(theme.TEXT_3))
            pen.setWidthF(1.5)
            pen.setStyle(Qt.PenStyle.DashLine)
            p.setPen(pen)
            y = h / 2.0
            p.drawLine(QPointF(pad, y), QPointF(w - pad, y))
            if len(series) == 1:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme._qcolor(theme.TEXT_2))
                p.drawEllipse(QPointF(w * 0.5, y), 3.0, 3.0)
            return
        lo, hi = min(series), max(series)
        rng = (hi - lo) or 1.0
        n = len(series)

        def xs(i: int) -> float:
            return pad + (i / (n - 1)) * (w - 2 * pad)

        def ys(v: float) -> float:
            return h - pad - ((v - lo) / rng) * (h - 2 * pad)

        poly = QPolygonF([QPointF(xs(i), ys(v)) for i, v in enumerate(series)])
        pen = QPen(theme._qcolor(theme.TEXT_2))              # quiet neutral line
        pen.setWidthF(1.6)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPolyline(poly)
        if self._trough_idx is not None and 0 <= self._trough_idx < n:   # trough ring
            tp = QPen(theme._qcolor(theme.TEXT_2))
            tp.setWidthF(1.4)
            p.setPen(tp)
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QPointF(xs(self._trough_idx), ys(series[self._trough_idx])), 3.4, 3.4)
        p.setPen(Qt.PenStyle.NoPen)                          # latest point
        p.setBrush(theme._qcolor(theme.TEXT_1))
        p.drawEllipse(QPointF(xs(n - 1), ys(series[-1])), 3.0, 3.0)


# hover tooltips per metric
TIP_EXPOSURE = ("Exposure = (sum of qty x mark) / portfolio value, absolute (USD) and %; "
                "per-position figures share the denominator and sum to the total.")
TIP_VOLATILITY = ("Volatility = sample standard deviation (ddof=1) of the simple per-period "
                  "returns, annualised by sqrt(periods per year).")
TIP_DRAWDOWN = ("Max drawdown = min over t of (value_t / running-max_t - 1) against the "
                "all-time peak; 0% when flat or rising.")

TIP_CTX_YIELDS = ("US Treasury par yields (3M / 2Y / 10Y / 30Y) and the 2s10s spread; a "
                  "negative spread is an inverted curve (the recession-watch signal). "
                  "Source: the US Treasury daily par yield curve (keyless).")
TIP_CTX_VIX = ("VIX - the CBOE 30-day implied S&P 500 volatility. "
               "Indicative bands: under 15 calm, 15-25 normal, 25-35 elevated, 35+ extreme. "
               "Source: FRED series VIXCLS. This product uses the FRED API but is not "
               "endorsed or certified by the Federal Reserve Bank of St. Louis. "
               "VIX data are copyright Cboe.")
TIP_CTX_FNG = ("Crypto Fear & Greed index (0-100): low = fear, high = greed, the "
               "provider's own classification; data from alternative.me (keyless).")
TIP_CTX_UKRATES = ("SONIA (IUDSOIA) and Bank Rate (IUDBEDR) from the Bank of England IADB "
                   "(keyless); each value shows its own as-of date.")

TIP_RA_VAR = ("Historical VaR: sort the window's returns ascending, m = floor((1-c)T)+1, "
              "VaR = -r(m) (no interpolation); 250-day window, 1-day horizon.")
TIP_RA_ES = ("Expected Shortfall 97.5% (the FRTB measure): the mean of the m worst returns, "
             "tail inclusive of the VaR observation, so ES >= VaR.")
TIP_RA_PVAR = ("Parametric VaR: -(mu - z_c sigma) from the window's sample mean and sd "
               "(ddof 1); the gap from the historical figure signals fat tails.")
TIP_RA_BETA = ("beta = Cov(r_p, r_b) / Var(r_b) over the common window vs SPY; cash and "
               "crypto positions lower it.")
TIP_RA_SHARPE = ("Sharpe: mean(r - rf) / sd(r - rf, ddof 1), annualised x sqrt(252); rf = "
                 "the US Treasury 3M par yield / 252.")
TIP_RA_SORTINO = ("Sortino: (mean(r) - target) / downside deviation (full-N, target 0), "
                  "annualised x sqrt(252).")
TIP_RA_EWMA = ("EWMA volatility (RiskMetrics): sigma_t^2 = 0.94 sigma_(t-1)^2 + 0.06 "
               "r_(t-1)^2, seeded with the window variance.")
TIP_RA_CONC = ("Concentration on position weights (cash excluded): HHI = sum w_i^2, "
               "effective N = 1/HHI, plus the largest weight and the sector roll-up.")
TIP_RA_DDUR = ("Drawdown duration: the time from the worst peak to the first sample back "
               "at or above it ('ongoing' until recovered).")
TIP_RA_BACKTEST = ("Kupiec proportion-of-failures and the Basel traffic light (bcbs22) on "
                   "the 99%/250d series: GREEN 0-4, YELLOW 5-9, RED 10+ exceptions; too few "
                   "also fails coverage.")
TIP_RA_CORR = ("Pearson correlation of the held assets' daily returns over 90 trading days; "
               "the rho is printed in every cell, never colour-only.")
TIP_RA_STRESS = ("Dated historical windows re-priced linearly on today's book: P&L = V x "
                 "sum(w_i x R_i); cached history, else a cited constant, else 'no data'.")
TIP_RA_CONTRIB = ("Risk contributions (parametric Euler component VaR): each position's "
                  "share of portfolio risk; a hedge shows a negative contribution.")
TIP_RA_DIVERS = ("Diversification: the average pairwise correlation, the most- and "
                 "least-correlated pairs, and the full sector breakdown.")
TIP_RA_PNL = ("P&L vs risk: open and realised P&L against the 1-day 95% VaR; return on "
              "VaR = P&L / VaR.")
TIP_RA_VARHIST = ("VaR history: the 1-day 95% VaR on a rolling 60-day window, read by "
                  "shape; the trend compares the latest with the oldest shown.")


class _Metric(QWidget):
    def __init__(self, kicker: str, tip: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("RiskMetric")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.S4, theme.S3, theme.S4, theme.S3)
        lay.setSpacing(3)
        k = QLabel(kicker)
        k.setObjectName("RiskMetricKicker")
        k.setToolTip(tip)
        lay.addWidget(k)
        row = QHBoxLayout()
        row.setSpacing(theme.S3)
        self.value = QLabel("-")
        self.value.setObjectName("RiskValue")
        self.value.setToolTip(tip)
        self.value.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.sub = QLabel("")
        self.sub.setObjectName("RiskSub")
        self.sub.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self.value)
        row.addStretch(1)
        row.addWidget(self.sub)
        lay.addLayout(row)
        self.caption = QLabel("")
        self.caption.setObjectName("RiskCaption")
        lay.addWidget(self.caption)
        self.state = QLabel("")
        self.state.setObjectName("RiskState")
        self.state.setWordWrap(True)
        lay.addWidget(self.state)

    def set_value(self, text: str, object_name: str = "RiskValue") -> None:
        self.value.setText(text)
        if self.value.objectName() != object_name:
            self.value.setObjectName(object_name)
            self.value.style().unpolish(self.value)
            self.value.style().polish(self.value)


class _TrafficChip(QWidget):
    _FILL: ClassVar[dict] = {"green": theme.GREEN_SOFT,
                             "yellow": theme.AMBER_SOFT,
                             "red": theme.RED_SOFT}
    _INK: ClassVar[dict] = {"green": theme.GREEN, "yellow": theme.AMBER,
                            "red": theme.RED}

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._zone = ""
        self._text = "no observations yet"
        self.setMinimumHeight(24)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,
                           QSizePolicy.Policy.Fixed)

    def set_state(self, zone: str, text: str) -> None:
        self._zone = zone if zone in self._FILL else ""
        self._text = text or ""
        self.update()

    def paintEvent(self, _event) -> None:
        from PySide6.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(0, 1, -1, -2)
        fill = self._FILL.get(self._zone, theme.NESTED)
        ink = self._INK.get(self._zone, theme.TEXT_2)
        p.setBrush(theme._qcolor(fill))
        p.setPen(QPen(theme._qcolor(ink)))
        p.drawRoundedRect(rect, 6, 6)
        p.setPen(QPen(theme._qcolor(ink)))  # fresh pen
        f = self.font()
        f.setFamily("IBM Plex Mono")
        f.setPixelSize(11)
        p.setFont(f)
        p.drawText(rect, Qt.AlignmentFlag.AlignCenter, self._text)
        p.end()


class _CorrHeatmap(QWidget):
    # rho numerals painted in every cell, never colour-only

    _MAX = 6                                   # readable cell budget

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        import pyqtgraph as pg
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._pg = pg
        self._glw = pg.GraphicsLayoutWidget()
        self._glw.setBackground(None)
        self._vb = self._glw.addViewBox(lockAspect=True, enableMouse=False)
        self._vb.setDefaultPadding(0.02)
        self._img = pg.ImageItem(axisOrder="row-major")
        self._vb.addItem(self._img)
        self._texts: list = []
        lay.addWidget(self._glw)
        self.setMinimumHeight(120)
        self.setMaximumHeight(170)
        self.hide()

    def set_matrix(self, symbols, matrix) -> None:
        if not symbols or len(symbols) < 2:
            self.hide()
            return
        symbols = list(symbols[:self._MAX])
        n = len(symbols)
        for t in self._texts:
            self._vb.removeItem(t)
        self._texts = []
        import numpy as np
        grid = np.zeros((n, n))
        for i in range(n):
            for j in range(n):
                v = matrix[i][j] if (i < len(matrix) and j < len(matrix[i])) else None
                grid[i][j] = 0.0 if v is None else float(v)
        # tonal map by rho sign
        img = np.zeros((n, n, 4), dtype=np.ubyte)
        for i in range(n):
            for j in range(n):
                v = grid[i][j]
                if v >= 0:
                    img[i, j] = (37, 99, 235, int(40 + 120 * min(v, 1.0)))
                else:
                    img[i, j] = (248, 81, 73, int(40 + 120 * min(-v, 1.0)))
        # flip rows so each fill sits under its numeral
        self._img.setImage(img[::-1, :])
        self._img.setRect(0.0, 0.0, float(n), float(n))
        for i in range(n):
            for j in range(n):
                v = matrix[i][j] if (i < len(matrix) and j < len(matrix[i])) else None
                label = "-" if v is None else f"{v:+.2f}"
                # numeral ink against the composited fill for AA
                vv = grid[i][j]
                if vv >= 0:
                    _fill = (37, 99, 235, int(40 + 120 * min(vv, 1.0)))
                else:
                    _fill = (248, 81, 73, int(40 + 120 * min(-vv, 1.0)))
                _cell = theme.composite_over(_fill, theme._rgb_tuple(theme.ROW_SOLID))
                t = self._pg.TextItem(label,
                                      color=theme._qcolor(theme.aa_ink_for(_cell)),
                                      anchor=(0.5, 0.5))
                f = t.textItem.font()
                f.setFamily("IBM Plex Mono")
                f.setPixelSize(10)
                t.textItem.setFont(f)
                t.setPos(j + 0.5, n - i - 0.5)
                self._vb.addItem(t)
                self._texts.append(t)
        for k, sym in enumerate(symbols):
            base = sym.split("/")[0][:4]
            t = self._pg.TextItem(base, color=theme._qcolor(theme.TEXT_2),
                                  anchor=(0.5, 0.5))
            f = t.textItem.font()
            f.setFamily("IBM Plex Mono")
            f.setPixelSize(9)
            t.textItem.setFont(f)
            t.setPos(k + 0.5, n + 0.32)
            self._vb.addItem(t)
            self._texts.append(t)
        self._vb.setRange(xRange=(0, n), yRange=(-0.1, n + 0.6), padding=0.02)
        self.show()


class RiskPanel(QFrame):
    # collapsible right-dock panel beneath the watchlist

    from PySide6.QtCore import Signal as _Signal
    collapse_toggled = _Signal(bool)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("RiskPanelRoot")
        self._collapsed = False
        self._roomy = False
        self._last_view = None
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(theme.S3)

        # header: chevron + PanelTitle + status slot
        head = QHBoxLayout()
        head.setContentsMargins(theme.S5, theme.S4, theme.S5, theme.S4)
        head.setSpacing(theme.S2)
        self._chevron = Chevron()
        self._chevron.clicked.connect(self.toggle_collapsed)
        head.addWidget(self._chevron)
        head.addSpacing(theme.S2)
        kick = QLabel("Risk")
        kick.setObjectName("PanelTitle")
        head.addWidget(kick)
        head.addStretch(1)
        # value-history CSV export chip
        from PySide6.QtWidgets import QPushButton
        self._csv_btn = QPushButton("CSV")
        self._csv_btn.setObjectName("CsvChip")
        self._csv_btn.setFixedSize(40, 22)
        self._csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._csv_btn.setToolTip("Export value history (CSV) - the sampled "
                                 "portfolio-value series behind these metrics "
                                 "(Ctrl+Shift+E). Disabled until a sample exists.")
        self._csv_btn.setEnabled(False)
        self._csv_btn.clicked.connect(self.export_value_history)
        head.addWidget(self._csv_btn)
        head.addSpacing(theme.S2)
        self._head_dot = StatusDot("warm")
        self._head_dot.hide()
        self._head_status = QLabel("")
        self._head_status.setObjectName("RiskCaption")
        head.addWidget(self._head_dot)
        head.addWidget(self._head_status)
        head_w = QWidget()
        head_w.setObjectName("PanelHead")        # shared header band QSS
        head_w.setLayout(head)
        head_w.setCursor(Qt.CursorShape.PointingHandCursor)
        head_w.mousePressEvent = self._on_head_press
        root.addWidget(head_w)
        self._csv_err = QLabel("")                       # inline export failure
        self._csv_err.setObjectName("RiskHint")
        self._csv_err.setWordWrap(True)
        self._csv_err.setContentsMargins(theme.S5, 0, theme.S5, 0)
        self._csv_err.hide()
        root.addWidget(self._csv_err)

        # the continuous #161A20 data region
        body = QFrame()
        self._body_frame = body
        body.setObjectName("RiskBody")
        body.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._body = QVBoxLayout(body)
        self._body.setContentsMargins(0, theme.S2, 0, theme.S3)
        self._body.setSpacing(0)

        # empty state
        self._empty = QWidget()
        self._empty.setObjectName("RiskContent")
        _el = QVBoxLayout(self._empty)
        _el.setContentsMargins(theme.S4, theme.S6, theme.S4, theme.S4)
        _el.setSpacing(theme.S4)
        _emsg = QLabel(EMPTY_TEXT)
        _emsg.setObjectName("RiskEmpty")
        _emsg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        _emsg.setWordWrap(True)
        _el.addWidget(_emsg)
        self._empty_spark = Sparkline()
        _el.addWidget(self._empty_spark)
        self._body.addWidget(self._empty)

        # content (hidden when empty)
        self._content = QWidget()
        self._content.setObjectName("RiskContent")
        cl = QVBoxLayout(self._content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(0)

        self._exp = _Metric("EXPOSURE", TIP_EXPOSURE)
        self._exp.value.setObjectName("RiskValueBig")  # focal number
        cl.addWidget(self._exp)
        self._exp_flag = QLabel("")                          # out-of-range flag
        self._exp_flag.setObjectName("RiskFlag")
        self._exp_flag.setContentsMargins(theme.S4, 0, theme.S4, 0)
        self._exp_flag.hide()
        cl.addWidget(self._exp_flag)
        self._exp_basis = QLabel("by position · % of NAV")   # denominator note
        self._exp_basis.setObjectName("RiskCaption")
        self._exp_basis.setContentsMargins(theme.S4, 0, theme.S4, 0)
        self._exp_basis.hide()
        cl.addWidget(self._exp_basis)
        self._pos_wrap = QWidget()                           # per-position mini-rows
        self._pos_wrap.setObjectName("RiskPosWrap")
        self._pos_grid = QGridLayout(self._pos_wrap)
        self._pos_grid.setContentsMargins(theme.S4, 0, theme.S4, theme.S2)
        self._pos_grid.setHorizontalSpacing(theme.S4)
        self._pos_grid.setVerticalSpacing(2)
        cl.addWidget(self._pos_wrap)
        cl.addWidget(self._sep())

        self._vol = _Metric("VOLATILITY", TIP_VOLATILITY)
        cl.addWidget(self._vol)
        self._caveat = _WrapMinLabel(VOL_CAVEAT)             # full caveat, wraps
        self._caveat.setObjectName("RiskCaveat")
        self._caveat.setWordWrap(True)
        self._caveat.setContentsMargins(theme.S4, theme.S2, theme.S4, theme.S2)
        cl.addWidget(self._caveat)
        self._vol_hint = QLabel("returns skipped - stale")   # stale-skip hint
        self._vol_hint.setObjectName("RiskHint")
        self._vol_hint.setContentsMargins(theme.S4, 0, theme.S4, 0)
        self._vol_hint.hide()
        cl.addWidget(self._vol_hint)
        cl.addWidget(self._sep())

        self._dd = _Metric("MAX DRAWDOWN", TIP_DRAWDOWN)
        cl.addWidget(self._dd)

        spark_cap = QLabel("VALUE")
        spark_cap.setObjectName("RiskMetricKicker")
        spark_cap.setContentsMargins(theme.S4, theme.S2, theme.S4, 4)
        cl.addWidget(spark_cap)
        self._spark = Sparkline()
        spark_row = QWidget()
        spark_row.setObjectName("RiskSparkRow")
        sr = QHBoxLayout(spark_row)
        sr.setContentsMargins(theme.S4, 0, theme.S4, theme.S2)
        sr.addWidget(self._spark)
        cl.addWidget(spark_row)

        self._body.addWidget(self._content)

        # ---- RISK ANALYTICS - the trading-day suite, default collapsed
        self._body.addWidget(self._sep())
        ra_head = QHBoxLayout()
        ra_head.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        ra_head.setSpacing(6)
        self._ra_chevron = Chevron()
        self._ra_chevron.set_expanded(False)
        self._ra_chevron.clicked.connect(self.toggle_analytics)
        ra_head.addWidget(self._ra_chevron)
        ra_kick = QLabel("RISK ANALYTICS")
        ra_kick.setObjectName("RiskMetricKicker")
        ra_kick.setToolTip(
            "The trading-day risk suite: historical-simulation "
            "VaR + a parametric cross-check, Expected Shortfall (FRTB "
            "97.5%), the Kupiec/Basel VaR backtest, beta vs SPY, Sharpe + "
            "Sortino, EWMA volatility, correlation, concentration, "
            "drawdown duration, and dated stress replays. A SEPARATE "
            "series from the three metrics above: daily TRADING-DAY "
            "returns of asset history (252/yr where annualised), today's "
            "weights held constant, cash earning zero - not the "
            "wall-clock value-history basis.")
        ra_head.addWidget(ra_kick)
        self._ra_summary = _ElideRightLabel()
        self._ra_summary.setObjectName("CtxSummary")
        self._ra_summary.setAlignment(Qt.AlignmentFlag.AlignRight
                                      | Qt.AlignmentFlag.AlignVCenter)
        ra_head.addWidget(self._ra_summary, 1)     # the one stretching member
        from PySide6.QtWidgets import QPushButton
        self._ra_csv_btn = QPushButton("CSV")
        self._ra_csv_btn.setObjectName("CsvChip")
        self._ra_csv_btn.setFixedSize(40, 22)
        self._ra_csv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._ra_csv_btn.setToolTip(
            "Export the risk-metrics snapshot (CSV): date-stamped metric "
            "values with a conventions column per metric - the locked "
            "wall-clock metrics ride along on their own labelled basis.")
        self._ra_csv_btn.setEnabled(False)
        self._ra_csv_btn.clicked.connect(self.export_risk_snapshot)
        ra_head.addWidget(self._ra_csv_btn)
        ra_head_w = QWidget()
        ra_head_w.setObjectName("CtxHead")
        ra_head_w.setLayout(ra_head)
        ra_head_w.setCursor(Qt.CursorShape.PointingHandCursor)
        ra_head_w.mousePressEvent = lambda _e: self.toggle_analytics()
        self._body.addWidget(ra_head_w)
        self._ra_body = QWidget()
        self._ra_body.setObjectName("RiskSubGroup")
        ra_col = QVBoxLayout(self._ra_body)
        ra_col.setContentsMargins(theme.S4, 0, theme.S4, theme.S2)
        ra_col.setSpacing(4)
        self._ra_state = QLabel("")
        self._ra_state.setObjectName("CtxValMuted")
        self._ra_state.setWordWrap(True)
        ra_col.addWidget(self._ra_state)
        ra_grid = QGridLayout()
        ra_grid.setContentsMargins(0, 0, 0, 0)
        ra_grid.setHorizontalSpacing(theme.S4)
        ra_grid.setVerticalSpacing(5)
        self._ra_rows: dict = {}
        for r, (key, name, tip) in enumerate((
                ("var95", "VAR 95 (1D)", TIP_RA_VAR),
                ("var99", "VAR 99 (1D)", TIP_RA_VAR),
                ("es", "ES 97.5 (1D)", TIP_RA_ES),
                ("pvar", "PARAMETRIC 95/99", TIP_RA_PVAR),
                ("beta", "BETA VS SPY", TIP_RA_BETA),
                ("sharpe", "SHARPE (252D ANN.)", TIP_RA_SHARPE),
                ("rf", "RISK-FREE (3M PAR)", TIP_RA_SHARPE),
                ("sortino", "SORTINO (252D ANN.)", TIP_RA_SORTINO),
                ("ewma", "EWMA VOL 0.94 (1D)", TIP_RA_EWMA),
                ("conc", "CONCENTRATION", TIP_RA_CONC),
                ("top", "TOP / SECTOR (% INV)", TIP_RA_CONC),
                ("ddur", "DRAWDOWN DURATION", TIP_RA_DDUR))):
            n = QLabel(name)
            n.setObjectName("CtxName")
            n.setToolTip(tip)
            v = QLabel("-")
            v.setObjectName("CtxVal")
            v.setToolTip(tip)
            v.setTextFormat(Qt.TextFormat.PlainText)
            v.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            ra_grid.addWidget(n, r, 0)
            ra_grid.addWidget(v, r, 1)
            self._ra_rows[key] = (n, v, tip)
        ra_col.addLayout(ra_grid)
        ra_col.addSpacing(theme.S2)                  # group metrics | P&L-vs-risk
        pnl_name = QLabel("P&L vs RISK")
        pnl_name.setObjectName("CtxName")
        pnl_name.setToolTip(TIP_RA_PNL)
        self._ra_pnl_name = pnl_name
        ra_col.addWidget(pnl_name)
        pnl_grid = QGridLayout()
        pnl_grid.setContentsMargins(0, 0, 0, 0)
        pnl_grid.setHorizontalSpacing(theme.S4)
        pnl_grid.setVerticalSpacing(5)
        self._ra_pnl_rows: dict = {}
        for r, (key, name) in enumerate((("total", "TOTAL P&L"),
                                         ("open", "UNREALISED"),
                                         ("real", "REALISED"))):
            n = QLabel(name)
            n.setObjectName("CtxName")
            n.setToolTip(TIP_RA_PNL)
            v = QLabel("-")
            v.setObjectName("CtxVal")
            v.setToolTip(TIP_RA_PNL)
            v.setTextFormat(Qt.TextFormat.PlainText)
            v.setAlignment(Qt.AlignmentFlag.AlignRight
                           | Qt.AlignmentFlag.AlignVCenter)
            pnl_grid.addWidget(n, r, 0)
            pnl_grid.addWidget(v, r, 1)
            self._ra_pnl_rows[key] = (n, v)
        ra_col.addLayout(pnl_grid)
        ra_col.addSpacing(theme.S2)                  # group metrics | backtest
        bt_name = QLabel("VAR BACKTEST (99%)")
        bt_name.setObjectName("CtxName")
        bt_name.setToolTip(TIP_RA_BACKTEST)
        ra_col.addWidget(bt_name)
        self._ra_chip = _TrafficChip()
        self._ra_chip.setToolTip(TIP_RA_BACKTEST)
        ra_col.addWidget(self._ra_chip)
        ra_col.addSpacing(theme.S2)                  # group backtest | VaR history
        vh_name = QLabel("VAR HISTORY")
        vh_name.setObjectName("CtxName")
        vh_name.setToolTip(TIP_RA_VARHIST)
        self._ra_varhist_name = vh_name
        ra_col.addWidget(vh_name)
        self._ra_varhist_line = QLabel("")
        self._ra_varhist_line.setObjectName("RiskCaption")
        self._ra_varhist_line.setToolTip(TIP_RA_VARHIST)
        ra_col.addWidget(self._ra_varhist_line)
        self._ra_varhist_spark = Sparkline()
        self._ra_varhist_spark.setToolTip(TIP_RA_VARHIST)
        ra_col.addWidget(self._ra_varhist_spark)
        ra_col.addSpacing(theme.S2)                  # group backtest | correlation
        corr_name = QLabel("CORRELATION (90D)")
        corr_name.setObjectName("CtxName")
        corr_name.setToolTip(TIP_RA_CORR)
        self._ra_corr_name = corr_name
        ra_col.addWidget(corr_name)
        self._ra_heatmap = _CorrHeatmap()
        self._ra_heatmap.setToolTip(TIP_RA_CORR)
        ra_col.addWidget(self._ra_heatmap)
        ra_col.addSpacing(theme.S2)                  # group correlation | diversification
        divers_name = QLabel("DIVERSIFICATION")
        divers_name.setObjectName("CtxName")
        divers_name.setToolTip(TIP_RA_DIVERS)
        self._ra_divers_name = divers_name
        ra_col.addWidget(divers_name)
        self._ra_divers_line = QLabel("")
        self._ra_divers_line.setObjectName("RiskCaption")
        self._ra_divers_line.setWordWrap(True)
        self._ra_divers_line.setToolTip(TIP_RA_DIVERS)
        ra_col.addWidget(self._ra_divers_line)
        self._ra_sector_grid = QGridLayout()
        self._ra_sector_grid.setContentsMargins(0, 0, 0, 0)
        self._ra_sector_grid.setHorizontalSpacing(theme.S4)
        self._ra_sector_grid.setVerticalSpacing(2)
        ra_col.addLayout(self._ra_sector_grid)
        ra_col.addSpacing(theme.S2)                  # group correlation | contributions
        contrib_name = QLabel("RISK CONTRIBUTIONS")
        contrib_name.setObjectName("CtxName")
        contrib_name.setToolTip(TIP_RA_CONTRIB)
        self._ra_contrib_name = contrib_name
        ra_col.addWidget(contrib_name)
        self._ra_contrib_state = QLabel("")
        self._ra_contrib_state.setObjectName("RiskCaption")
        self._ra_contrib_state.setWordWrap(True)
        self._ra_contrib_state.setToolTip(TIP_RA_CONTRIB)
        ra_col.addWidget(self._ra_contrib_state)
        self._ra_contrib_grid = QGridLayout()
        self._ra_contrib_grid.setContentsMargins(0, 0, 0, 0)
        self._ra_contrib_grid.setHorizontalSpacing(theme.S4)
        self._ra_contrib_grid.setVerticalSpacing(3)
        ra_col.addLayout(self._ra_contrib_grid)
        ra_col.addSpacing(theme.S2)                  # group correlation | stress
        stress_name = QLabel("STRESS REPLAYS")
        stress_name.setObjectName("CtxName")
        stress_name.setToolTip(TIP_RA_STRESS)
        ra_col.addWidget(stress_name)
        self._ra_stress_grid = QGridLayout()
        self._ra_stress_grid.setContentsMargins(0, 0, 0, 0)
        self._ra_stress_grid.setHorizontalSpacing(theme.S4)
        self._ra_stress_grid.setVerticalSpacing(3)
        ra_col.addLayout(self._ra_stress_grid)
        self._ra_body.hide()                             # default collapsed
        self._ra_collapsed = True
        self._body.addWidget(self._ra_body)

        # ---- market CONTEXT - exogenous market data, default collapsed
        self._body.addWidget(self._sep())
        ctx_head = QHBoxLayout()
        ctx_head.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        ctx_head.setSpacing(6)
        self._ctx_chevron = Chevron()
        self._ctx_chevron.set_expanded(False)
        self._ctx_chevron.clicked.connect(self.toggle_context)
        ctx_head.addWidget(self._ctx_chevron)
        ctx_kick = QLabel("MARKET CONTEXT")
        ctx_kick.setObjectName("RiskMetricKicker")
        ctx_kick.setToolTip("Exogenous market data shown for context - not "
                            "portfolio risk metrics (those are above).")
        ctx_head.addWidget(ctx_kick)
        self._ctx_summary = _ElideRightLabel()
        self._ctx_summary.setObjectName("CtxSummary")
        self._ctx_summary.setAlignment(Qt.AlignmentFlag.AlignRight
                                       | Qt.AlignmentFlag.AlignVCenter)
        ctx_head.addWidget(self._ctx_summary, 1)   # the one stretching member
        ctx_head_w = QWidget()
        ctx_head_w.setObjectName("CtxHead")
        ctx_head_w.setLayout(ctx_head)
        ctx_head_w.setCursor(Qt.CursorShape.PointingHandCursor)
        ctx_head_w.mousePressEvent = lambda _e: self.toggle_context()
        self._body.addWidget(ctx_head_w)
        self._ctx_body = QWidget()
        self._ctx_body.setObjectName("RiskSubGroup")
        ctx_grid = QGridLayout(self._ctx_body)
        ctx_grid.setContentsMargins(theme.S4, 0, theme.S4, theme.S2)
        ctx_grid.setHorizontalSpacing(theme.S4)
        ctx_grid.setVerticalSpacing(4)
        self._ctx_rows = {}
        for r, (key, name, tip) in enumerate((
                ("yields", "YIELDS", TIP_CTX_YIELDS),
                ("vix", "VIX", TIP_CTX_VIX),
                ("fng", "CRYPTO F&G", TIP_CTX_FNG),
                ("ukrates", "UK RATES", TIP_CTX_UKRATES))):
            n = QLabel(name)
            n.setObjectName("CtxName")
            n.setToolTip(tip)
            v = QLabel("-")
            v.setObjectName("CtxValMuted")
            v.setToolTip(tip)
            v.setTextFormat(Qt.TextFormat.PlainText)     # external-origin text
            v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            ctx_grid.addWidget(n, r, 0)
            ctx_grid.addWidget(v, r, 1)
            self._ctx_rows[key] = (n, v, tip)
        self._ctx_body.hide()                            # default collapsed
        self._ctx_collapsed = True
        self._body.addWidget(self._ctx_body)

        root.addWidget(body)
        root.addStretch(0)
        self._content.hide()

    def toggle_analytics(self) -> None:
        self._ra_collapsed = not self._ra_collapsed
        self._ra_chevron.set_expanded(not self._ra_collapsed)
        self._ra_body.setVisible(not self._ra_collapsed)
        self._ra_summary.setVisible(self._ra_collapsed)
        self.updateGeometry()

    def set_analytics(self, view: object) -> None:
        if not isinstance(view, RiskAnalyticsView):
            return
        self._ra_summary.set_full_text(analytics_summary(view))
        self._last_analytics = view  # CSV export input
        self._ra_csv_btn.setEnabled(view.available)
        if not view.available:
            self._ra_state.setText(view.note or "warming")
            self._ra_state.show()
            for _n, v, _t in self._ra_rows.values():
                v.setText("-")
            for _n2, v2 in self._ra_pnl_rows.values():
                v2.setText("-")
            self._ra_chip.set_state("", "no observations yet")
            self._ra_heatmap.set_matrix((), ())
            self._ra_corr_name.setVisible(False)
            self._render_stress(())
            self._render_contributions(None)
            self._render_diversification(None)
            self._render_varhistory(None)
            return
        self._ra_state.setText(
            f"window {view.n}/{view.window}d · as of {view.as_of}"
            + (f" · excludes {', '.join(view.excluded)} (no history)"
               if view.excluded else ""))
        self._ra_state.show()

        def pct(x):
            return "-" if x is None else f"{x * 100.0:.2f}%"

        def usd(x):
            return "" if x is None else f" · {x:,.0f} USD"

        def signed_usd(x):
            return "-" if x is None else f"{x:+,.0f} USD"

        def rovar(r):
            return "" if r is None else f" · {r:+.1f}x VaR95"

        rows = self._ra_rows
        rows["var95"][1].setText(pct(view.var95_pct) + usd(view.var95_usd))
        rows["var99"][1].setText(pct(view.var99_pct) + usd(view.var99_usd))
        rows["es"][1].setText(pct(view.es975_pct) + usd(view.es975_usd))
        if view.pvar95_pct is not None and view.pvar99_pct is not None:
            rows["pvar"][1].setText(f"{pct(view.pvar95_pct)} / "
                                    f"{pct(view.pvar99_pct)}")
        else:
            rows["pvar"][1].setText("-")
        rows["beta"][1].setText("-" if view.beta_spy is None
                                else f"{view.beta_spy:.2f}")
        if view.sharpe_annual is not None:
            rows["sharpe"][1].setText(f"{view.sharpe_annual:.2f}")
        else:
            rows["sharpe"][1].setText("- needs the risk-free")
        if view.rf_annual_pct is not None:
            rows["rf"][1].setText(f"{view.rf_annual_pct:.2f}% · {view.rf_as_of}")
        else:
            rows["rf"][1].setText("- (US Treasury feed)")
        rows["sortino"][1].setText("-" if view.sortino_annual is None
                                   else f"{view.sortino_annual:.2f}")
        rows["ewma"][1].setText("-" if view.ewma_vol_pct is None
                                else f"{view.ewma_vol_pct:.2f}% daily")
        if view.hhi is not None:
            rows["conc"][1].setText(f"HHI {view.hhi:.2f} · "
                                    f"effN {view.effective_n:.1f}")
            top_sector = (view.sector_weights[0][0] if view.sector_weights
                          else "")
            top = (f"{view.top_symbol} {view.top_weight * 100.0:.0f}%"
                   if view.top_weight is not None else "-")
            rows["top"][1].setText(f"{top}"
                                   + (f" · {top_sector}" if top_sector else ""))
        else:
            rows["conc"][1].setText("-")
            rows["top"][1].setText("-")
        if view.dd_depth_pct is None:
            rows["ddur"][1].setText("-")
        elif view.dd_duration_periods is not None:
            rows["ddur"][1].setText(f"{view.dd_depth_pct:.2f}% · recovered "
                                    f"in {view.dd_duration_periods}")
        elif view.dd_ongoing_periods is not None:
            rows["ddur"][1].setText(f"{view.dd_depth_pct:.2f}% · ongoing "
                                    f"({view.dd_ongoing_periods})")
        else:
            rows["ddur"][1].setText(f"{view.dd_depth_pct:.2f}%")
        self._ra_pnl_rows["total"][1].setText(
            signed_usd(view.pnl_total_usd) + rovar(view.pnl_to_var95))
        self._ra_pnl_rows["open"][1].setText(
            signed_usd(view.pnl_unrealised_usd) + rovar(view.unreal_to_var95))
        self._ra_pnl_rows["real"][1].setText(signed_usd(view.pnl_realised_usd))
        self._ra_chip.set_state(view.backtest_zone, backtest_chip_text(view))
        kup = ("" if view.kupiec_p is None else
               f"\nKupiec POF p = {view.kupiec_p:.3f} "
               f"({'reject' if view.kupiec_reject else 'accept'} at 5%). ")
        self._ra_chip.setToolTip(TIP_RA_BACKTEST + kup)
        self._ra_heatmap.set_matrix(view.corr_symbols, view.corr_matrix)
        n_corr = len(view.corr_symbols)
        cap = self._ra_heatmap._MAX
        self._ra_corr_name.setText(
            f"CORRELATION ({view.corr_window}D)"
            + (f" · FIRST {cap} OF {n_corr}" if n_corr > cap else ""))
        self._ra_corr_name.setVisible(n_corr >= 2)
        self._render_stress(view.stress)
        self._render_contributions(view)
        self._render_diversification(view)
        self._render_varhistory(view)

    def export_risk_snapshot(self) -> None:
        view = getattr(self, "_last_analytics", None)
        locked = getattr(self, "_last_view", None)
        if view is None or not getattr(view, "available", False):
            self._csv_err.setText("No analytics yet - the suite needs daily "
                                  "history (see the section state line).")
            self._csv_err.show()
            return
        self._ra_csv_btn.setEnabled(False)               # single-flight
        try:
            from PySide6.QtWidgets import QFileDialog
            import datetime as _dt
            path, _ = QFileDialog.getSaveFileName(
                self, "Export risk snapshot CSV", "mahad-risk-snapshot.csv",
                "CSV files (*.csv)")
            if not path:
                return
            try:
                now_iso = _dt.date.today().isoformat()
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(build_risk_snapshot_csv(view, locked,
                                                     now_iso=now_iso))
                self._csv_err.hide()                     # clear on success
            except Exception as exc:                     # nothing escapes
                self._csv_err.setText(f"Could not write CSV ({exc}). "
                                      "Try another path.")
                self._csv_err.show()
        finally:
            self._ra_csv_btn.setEnabled(True)

    def _render_stress(self, rows: tuple) -> None:
        while self._ra_stress_grid.count():
            it = self._ra_stress_grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        for r, row in enumerate(rows):
            n = QLabel(f"{row.scenario}\n{row.start} to {row.end}")
            n.setObjectName("CtxName")
            tip = (f"{row.start} to {row.end}. Linear re-pricing: P&L = V x "
                   "sum(w_i x R_i(window)) - exact for this long-only "
                   "book. ")
            if row.constant_legs:
                tip += ("Fixed historical constant legs: "
                        + ", ".join(row.constant_legs)
                        + " (approximate close-to-close, owner-verifiable). ")
            if row.legs_no_data:
                tip += ("No data for this window: "
                        + ", ".join(row.legs_no_data) + ". ")
            n.setToolTip(tip)
            full_tip = tip + f"Covered weight {row.covered_weight * 100.0:.0f}%."
            cell: QWidget                                  # QLabel or value box
            if row.pl_usd is None:
                cell = QLabel("no data")
                cell.setObjectName("CtxVal")
                cell.setTextFormat(Qt.TextFormat.PlainText)
                cell.setAlignment(Qt.AlignmentFlag.AlignRight
                                  | Qt.AlignmentFlag.AlignVCenter)
                cell.setToolTip(full_tip)
            else:
                # magnitude over a muted "scenario" basis tag
                cell = QWidget()
                cell.setObjectName("StressVal")
                cv = QVBoxLayout(cell)
                cv.setContentsMargins(0, 0, 0, 0)
                cv.setSpacing(0)
                mag = QLabel(f"{row.pl_usd:,.0f} USD")
                mag.setObjectName("CtxVal")
                mag.setTextFormat(Qt.TextFormat.PlainText)
                mag.setAlignment(Qt.AlignmentFlag.AlignRight
                                 | Qt.AlignmentFlag.AlignVCenter)
                mag.setToolTip(full_tip)
                basis = QLabel("scenario")
                basis.setObjectName("StressBasis")
                basis.setAlignment(Qt.AlignmentFlag.AlignRight
                                   | Qt.AlignmentFlag.AlignVCenter)
                basis.setToolTip(full_tip)
                cv.addWidget(mag)
                cv.addWidget(basis)
            n.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
            self._ra_stress_grid.addWidget(n, r, 0)
            self._ra_stress_grid.addWidget(cell, r, 1, Qt.AlignmentFlag.AlignTop)

    def _render_varhistory(self, view: object) -> None:
        hist = getattr(view, "var_history", ()) if view else ()
        if not hist:
            self._ra_varhist_name.setVisible(False)
            self._ra_varhist_line.setVisible(False)
            self._ra_varhist_spark.setVisible(False)
            self._ra_varhist_spark.set_data(())
            return
        self._ra_varhist_name.setVisible(True)
        self._ra_varhist_spark.setVisible(True)
        self._ra_varhist_spark.set_data(hist)
        trend = f" · {view.var_trend}" if view.var_trend else ""
        self._ra_varhist_line.setText(
            f"VaR95 {hist[-1] * 100.0:.2f}% (60d roll){trend}")
        self._ra_varhist_line.setVisible(True)

    def _render_diversification(self, view: object) -> None:
        grid = self._ra_sector_grid
        while grid.count():
            it = grid.takeAt(0)
            wdg = it.widget()
            if wdg is not None:
                wdg.hide()
                wdg.setParent(None)
                wdg.deleteLater()
        sectors = getattr(view, "sector_weights", ()) if view else ()
        avg = getattr(view, "corr_avg", None) if view else None
        if not sectors and avg is None:
            self._ra_divers_name.setVisible(False)
            self._ra_divers_line.setVisible(False)
            return
        self._ra_divers_name.setVisible(True)
        self._ra_divers_name.setText("DIVERSIFICATION · % OF INVESTED")
        if avg is not None:
            parts = [f"avg rho {avg:+.2f}"]
            mx, mn = view.corr_max_pair, view.corr_min_pair
            if mx:
                parts.append(f"most {mx[0]}-{mx[1]} {mx[2]:+.2f}")
            if mn:
                parts.append(f"least {mn[0]}-{mn[1]} {mn[2]:+.2f}")
            self._ra_divers_line.setText(" · ".join(parts))
            self._ra_divers_line.setVisible(True)
        else:
            self._ra_divers_line.setVisible(False)
        for r, (sec, wt) in enumerate(sectors):
            nm = QLabel(sec)
            nm.setObjectName("CtxName")
            nm.setTextFormat(Qt.TextFormat.PlainText)
            nm.setToolTip(TIP_RA_DIVERS)
            nm.setAlignment(Qt.AlignmentFlag.AlignLeft
                            | Qt.AlignmentFlag.AlignVCenter)
            val = QLabel(f"{wt * 100.0:.1f}%")
            val.setObjectName("CtxValMuted")
            val.setTextFormat(Qt.TextFormat.PlainText)
            val.setAlignment(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter)
            val.setToolTip(TIP_RA_DIVERS)
            grid.addWidget(nm, r, 0)
            grid.addWidget(val, r, 1)

    def _render_contributions(self, view: object) -> None:
        grid = self._ra_contrib_grid
        while grid.count():
            it = grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        contribs = getattr(view, "contributions", ()) if view else ()
        if not contribs:
            self._ra_contrib_name.setVisible(False)
            self._ra_contrib_state.setVisible(False)
            return
        cap = 6
        n = len(contribs)
        conf = getattr(view, "comp_confidence", 0.95)
        self._ra_contrib_name.setText(
            f"RISK CONTRIBUTIONS · COMP VAR {conf * 100.0:.0f}%"
            + (f" · FIRST {cap} OF {n}" if n > cap else ""))
        self._ra_contrib_name.setVisible(True)
        if view.comp_var_pct is not None and view.comp_sigma_pct is not None:
            usd = ("" if view.comp_var_usd is None
                   else f" ({view.comp_var_usd:,.0f} USD)")
            self._ra_contrib_state.setText(
                f"sigma {view.comp_sigma_pct * 100.0:.2f}% · "
                f"VaR {view.comp_var_pct * 100.0:.2f}%{usd}")
            self._ra_contrib_state.setVisible(True)
        else:
            self._ra_contrib_state.setVisible(False)
        hint = QLabel("% of risk · VaR USD")          # denominator note
        hint.setObjectName("RiskCaption")
        hint.setAlignment(Qt.AlignmentFlag.AlignRight
                          | Qt.AlignmentFlag.AlignVCenter)
        hint.setToolTip(TIP_RA_CONTRIB)
        self._ra_contrib_grid.addWidget(hint, 0, 1)
        for r, c in enumerate(contribs[:cap], start=1):
            nm = QLabel(c.symbol)
            nm.setObjectName("CtxName")
            nm.setToolTip(TIP_RA_CONTRIB)
            nm.setAlignment(Qt.AlignmentFlag.AlignLeft
                            | Qt.AlignmentFlag.AlignVCenter)
            val = QLabel(f"{c.pct * 100.0:+.1f}% · {c.comp_var_usd:+,.0f} USD")
            val.setObjectName("CtxVal")
            val.setTextFormat(Qt.TextFormat.PlainText)
            val.setAlignment(Qt.AlignmentFlag.AlignRight
                             | Qt.AlignmentFlag.AlignVCenter)
            val.setToolTip(TIP_RA_CONTRIB)
            grid.addWidget(nm, r, 0)
            grid.addWidget(val, r, 1)

    def _sep(self) -> QFrame:
        line = QFrame()
        line.setFixedHeight(1)
        line.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        return line

    # -- collapse ------------------------------------------ #
    def _on_head_press(self, _event) -> None:
        self.toggle_collapsed()

    def toggle_collapsed(self) -> None:
        self.set_collapsed(not self._collapsed)
        self.collapse_toggled.emit(self._collapsed)

    def set_collapsed(self, collapsed: bool) -> None:
        # hides the data region; header stays
        self._collapsed = collapsed
        self._chevron.set_expanded(not collapsed)
        self._body_frame.setVisible(not collapsed)

    def is_collapsed(self) -> bool:
        return self._collapsed

    def set_roomy(self, roomy: bool) -> None:
        # grow into freed space with a taller sparkline, or restore
        if roomy == self._roomy:
            return
        self._roomy = roomy
        if self._last_view is not None:          # re-render row cap
            self._render_pos_rows(self._last_view)
        sp = self.sizePolicy()
        sp.setVerticalPolicy(QSizePolicy.Policy.Expanding if roomy
                             else QSizePolicy.Policy.Preferred)
        self.setSizePolicy(sp)
        for spark in (self._spark, self._empty_spark):
            spark.setMinimumHeight(88 if roomy else 54)
            spark.setMaximumHeight(140 if roomy else 64)

    def is_roomy(self) -> bool:
        return self._roomy

    def _render_pos_rows(self, view: RiskView) -> None:
        while self._pos_grid.count():
            it = self._pos_grid.takeAt(0)
            w = it.widget()
            if w is not None:
                w.hide()                         # remove old rows now
                w.setParent(None)
                w.deleteLater()
        rows = list(view.exp_rows)
        cap = len(rows) if self._roomy else 3
        for r, row in enumerate(rows[:cap]):
            sym = QLabel(row.symbol)
            sym.setTextFormat(Qt.TextFormat.PlainText)      # external-origin text
            sym.setObjectName("RiskPosSym")
            pct = QLabel(f"{row.pct * 100:.2f}%")
            pct.setObjectName("RiskPosPct")
            pct.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._pos_grid.addWidget(sym, r, 0)
            self._pos_grid.addWidget(pct, r, 1)
        if len(rows) > cap:
            more = QLabel(f"+{len(rows) - cap} more")
            more.setObjectName("RiskPosSym")
            self._pos_grid.addWidget(more, cap, 0)
        self._pos_wrap.setVisible(len(rows) > 0)
        self._exp_basis.setVisible(len(rows) > 0)

    # -- render ------------------------------------------------------------- #
    def set_view(self, view: object) -> None:
        if not isinstance(view, RiskView):
            return
        self._last_view = view                   # roomy re-renders rows
        self._history_rows = tuple(view.history)         # export rows
        self._csv_btn.setEnabled(bool(self._history_rows))
        if view.empty:
            self._content.hide()
            self._empty.show()
            self._head_dot.hide()
            self._head_status.setText("")
            self._empty_spark.set_data((), None)   # flat dashed baseline
            return
        self._empty.hide()
        self._content.show()

        # header stale/warming indicator
        if view.any_stale:
            self._head_dot.set_state("stale")
            self._head_dot.show()
            self._head_status.setText("as of last good data")
        elif view.warming:
            self._head_dot.hide()
            self._head_status.setText("warming up")
        else:
            self._head_dot.hide()
            self._head_status.setText("")

        # EXPOSURE
        if view.exp_defined and view.exp_pct is not None:
            self._exp.set_value(f"{money(view.exp_abs):,.2f}" if view.exp_abs is not None else "-",
                                "RiskValueBig")  # focal number
            self._exp.sub.setText(f"{view.exp_pct * 100:.2f}%")
        else:
            self._exp.set_value("-", "RiskValueBigMuted")
            self._exp.sub.setText("")
        self._exp.caption.setText("as of last good price" if view.any_stale else "now")
        # pre-trade hint
        self._exp.state.setText("" if view.exp_rows else "populates on the first trade")
        if view.exp_out_of_range:                            # visible flag
            self._exp_flag.setText("out of range - check marks")
            self._exp_flag.show()
        else:
            self._exp_flag.hide()
        self._fill_positions(view)

        # VOLATILITY
        self._vol.caption.setText("last <= 30 returns")
        if view.vol_defined and view.vol_period_pct is not None:
            self._vol.set_value(f"{view.vol_period_pct:.2f}%")
            ann = f"{view.vol_annual_pct:,.2f}% ann." if view.vol_annual_pct is not None else ""
            self._vol.sub.setText(ann)
            self._vol.state.setText(f"per-period ({view.timeframe}) · annualised x sqrt(periods/yr)")
            self._caveat.show()
        else:
            self._vol.set_value("-", "RiskValueMuted")
            self._vol.sub.setText("")
            self._vol.state.setText("needs >= 2 returns")  # header owns "warming up"
            self._caveat.hide()
        self._vol_hint.setVisible(bool(view.returns_skipped_stale))

        # MAX DRAWDOWN
        self._dd.caption.setText("since inception")
        if view.dd_pct < 0.0:
            self._dd.set_value(f"{view.dd_pct:.2f}%", "RiskValueNeg")
            self._dd.state.setText(f"peak {_fmt_ts(view.dd_peak_ts)} · trough {_fmt_ts(view.dd_trough_ts)}")
        else:
            self._dd.set_value("0.0%", "RiskValue")          # flat -> neutral
            self._dd.state.setText("")  # state slot reserved for stale/skip msgs
        self._dd.sub.setText("")

        # SPARKLINE
        self._spark.set_data(view.spark, view.spark_trough_idx)

    def _fill_positions(self, view: RiskView) -> None:
        self._render_pos_rows(view)

    # -- the market CONTEXT section -------------------- #
    def toggle_context(self) -> None:
        self.set_context_collapsed(not self._ctx_collapsed)

    def set_context_collapsed(self, collapsed: bool) -> None:
        # collapses independently of the Risk section
        self._ctx_collapsed = collapsed
        self._ctx_chevron.set_expanded(not collapsed)
        self._ctx_body.setVisible(not collapsed)
        self._ctx_summary.setVisible(collapsed)

    def is_context_collapsed(self) -> bool:
        return self._ctx_collapsed

    @staticmethod
    def _ctx_suffix(as_of: str, note: str) -> str:
        extra = f" · as of {as_of}" if as_of else ""
        fail = f"\n{note}" if note else ""
        return extra + fail

    @staticmethod
    def _degraded(value_text: str, as_of: str) -> str:
        # cached-degraded form: value plus a short as-of marker
        short = as_of[5:] if len(as_of) >= 10 else as_of
        return f"{value_text} · as of {short}" if short else value_text

    def set_context(self, view: object) -> None:
        if not isinstance(view, MarketContextView):
            return
        self._ctx_summary.set_full_text(view.summary)

        def put(key: str, text: str, muted: bool, tip_extra: str) -> None:
            _n, v, tip = self._ctx_rows[key]
            v.setText(text)
            name = "CtxValMuted" if muted else "CtxVal"
            if v.objectName() != name:
                v.setObjectName(name)
                v.style().unpolish(v)
                v.style().polish(v)
            v.setToolTip(tip + tip_extra)

        y = view.yields
        if y.available and y.y10y is not None:
            sp = (f" · 2s10s {y.spread_bp:+.0f} bp {y.reading}"
                  if y.spread_bp is not None else "")
            text = f"10Y {y.y10y:.2f}%{sp}"
            tip = (self._ctx_suffix(y.as_of, y.note)
                   + (f"\n3M {y.y3m:.2f} · 2Y {y.y2y:.2f} · 10Y {y.y10y:.2f}"
                      f" · 30Y {y.y30y:.2f}"
                      if None not in (y.y3m, y.y2y, y.y30y) else ""))
            if y.note:                                   # cached + refresh failed
                put("yields", self._degraded(f"10Y {y.y10y:.2f}%", y.as_of),
                    True, tip)
            else:
                put("yields", text, False, tip)
        else:
            put("yields", y.note or "unavailable - retrying", True, "")

        v = view.vix
        if v.needs_key:
            put("vix", "needs a free FRED key", True,
                "\nAdd FRED_API_KEY to the git-ignored .env (see .env.example"
                " and the README; free, no card) - everything else runs"
                " without it.")
        elif v.available and v.value is not None:
            chg = f" ({v.change:+.2f})" if v.change is not None else ""
            if v.note:                                   # cached + refresh failed
                put("vix", self._degraded(f"{v.value:.1f}", v.as_of), True,
                    self._ctx_suffix(v.as_of, v.note))
            else:
                put("vix", f"{v.value:.1f}{chg} · {v.band}", False,
                    self._ctx_suffix(v.as_of, v.note))
        else:
            put("vix", v.note or "unavailable - retrying", True, "")

        f = view.sentiment
        if f.available and f.value is not None:
            if f.note:                                   # cached + refresh failed
                put("fng", self._degraded(str(f.value), f.as_of), True,
                    self._ctx_suffix(f.as_of, f.note))
            else:
                put("fng", f"{f.value} · {f.classification}", False,
                    self._ctx_suffix(f.as_of, f.note))
        else:
            put("fng", f.note or "unavailable - retrying", True, "")

        u = view.ukrates
        if u.available and (u.sonia is not None or u.bank_rate is not None):
            parts = []
            if u.sonia is not None:
                parts.append(f"SONIA {u.sonia:.2f}%")
            if u.bank_rate is not None:
                parts.append(f"Bank Rate {u.bank_rate:.2f}%")
            text = " · ".join(parts)
            tip_dates = ""
            if u.sonia is not None and u.sonia_as_of:
                tip_dates += f"\nSONIA as of {u.sonia_as_of}"
            if u.bank_rate is not None and u.bank_rate_as_of:
                tip_dates += f"\nBank Rate as of {u.bank_rate_as_of}"
            if u.note:                                   # cached + refresh failed
                put("ukrates", self._degraded(text, u.as_of), True,
                    self._ctx_suffix(u.as_of, u.note) + tip_dates)
            else:
                put("ukrates", text, False,
                    self._ctx_suffix(u.as_of, u.note) + tip_dates)
        else:
            put("ukrates", u.note or "unavailable - retrying", True, "")

    # -- the value-history CSV export ----------------- #
    def export_value_history(self) -> None:
        rows = getattr(self, "_history_rows", ())
        if not rows:
            self._csv_err.setText("No value history yet - it accrues on the "
                                  "risk timeframe.")
            self._csv_err.show()
            return
        self._csv_btn.setEnabled(False)                  # single-flight
        try:
            from PySide6.QtWidgets import QFileDialog
            path, _ = QFileDialog.getSaveFileName(
                self, "Export value history CSV", "mahad-value-history.csv",
                "CSV files (*.csv)")
            if not path:
                return
            try:
                with open(path, "w", encoding="utf-8", newline="") as fh:
                    fh.write(build_value_history_csv(rows))
            except Exception as exc:                     # nothing escapes
                self._csv_err.setText(f"Could not write CSV ({exc}). "
                                      "Try another path.")
                self._csv_err.show()
                return
            self._csv_err.hide()
        finally:
            self._csv_btn.setEnabled(bool(getattr(self, "_history_rows", ())))
