from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QIcon, QMouseEvent, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout,
                               QLabel, QMainWindow, QPushButton, QScrollArea,
                               QSplitter, QStatusBar, QTabBar, QTabWidget,
                               QToolButton, QVBoxLayout, QWidget)

from mahad import config
from mahad.data.symbols import AlertsView, WatchlistState
from mahad.engine.snapshot import RenderSnapshot
from mahad.ui import theme
from mahad.ui.alert_dialog import AlertDialog
from mahad.ui.alerts_tab import AlertsTab
from mahad.ui.chart_view import ChartView
from mahad.ui.indicator_popover import IndicatorPopover
from mahad.ui.toast import ToastHost
from mahad.ui.order_ticket import OrderTicket
from mahad.ui.portfolio_panel import PortfolioPanel
from mahad.ui.reset_dialog import ResetDialog
from mahad.ui.trade_log_panel import TradeLogPanel
from mahad.ui.watchlist_panel import WatchlistPanel
from mahad.ui.risk_panel import RiskPanel
from mahad.ui.settings_dialog import SettingsDialog
from mahad.ui.widgets import (IconButton, SegmentedControl, StatusDot,
                              WinControlButton, _DockTabBar, edge_at,
                              start_system_move, start_system_resize)
from mahad.worker import PollWorker

SWITCH_DEBOUNCE_MS = 250  # symbol/timeframe switch window


class _ScrimOverlay(QFrame):
    # full-window dim behind a modal dialog

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.setObjectName("ScrimOverlay")
        self.setStyleSheet(f"QFrame#ScrimOverlay {{ background: {theme.SCRIM}; }}")
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.hide()

    def cover(self) -> None:
        p = self.parentWidget()
        if p is not None:
            self.setGeometry(p.rect())
        self.show()
        self.raise_()


class MainWindow(QMainWindow):
    _stop_worker = Signal()
    _alert_remove = Signal(int)                # queued alert delete

    def __init__(self, symbol: str | None = None, timeframe: str | None = None) -> None:
        super().__init__()
        _app = QApplication.instance()
        if _app is not None:
            _app.setApplicationDisplayName("")
        self._symbol = symbol or config.DEFAULT_SYMBOL
        self._timeframe = timeframe or config.DEFAULT_TIMEFRAME
        self._risk_timeframe = config.RISK_TIMEFRAME
        # custom frameless frame; guarded for platforms without a window handle
        try:
            self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        except Exception:  # nosec B110 - degrade boundary
            pass
        self._resize_margin = 6
        self._resize_edges = None                # active manual-resize edge set
        self._move_origin = None                 # manual-move drag origin
        self._is_maxed = False                   # explicit maximise state
        self._normal_geom = None                 # geometry to restore to
        self._wl_collapsed = False               # right-dock collapse memory
        self._risk_collapsed = False
        self._clamping = False                   # work-area clamp re-entry guard
        self._screen_conn = False
        # launch size, clamped to the work area
        self.resize(1280, 1040)
        self._update_title()
        self._apply_window_icon()

        # alert/dialog state
        self._last_snapshot: RenderSnapshot | None = None
        self._last_alerts: AlertsView | None = None
        self._dialog: AlertDialog | None = None
        self._arm_pending = False
        self._arm_pre_count = 0
        self._unread = 0
        self._deleting_alert_ids: set[int] = set()         # de-dupe rapid deletes
        self._modal_busy = False                           # one modal at a time
        self._ticket: OrderTicket | None = None
        self._ticket_symbol: str | None = None

        # header on top; below it a horizontal splitter, the left column a
        # vertical splitter [chart | bottom dock]
        central = QWidget()
        cv = QVBoxLayout(central)
        # edge-to-edge outer inset
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(theme.S2)
        cv.addWidget(self._build_header())                 # full-width top bar

        self._chart = ChartView(self._symbol, self._timeframe)
        chart_card = QFrame()
        chart_card.setObjectName("PlotCard")               # solid deep surround
        chart_card.setMinimumHeight(240)
        ccl = QVBoxLayout(chart_card)
        ccl.setContentsMargins(theme.S1, theme.S1, theme.S1, theme.S1)
        ccl.addWidget(self._chart)

        bottom = self._build_bottom_dock()
        self._v_split = QSplitter(Qt.Orientation.Vertical)
        self._v_split.setChildrenCollapsible(False)
        self._v_split.setHandleWidth(6)            # grab affordance
        self._v_split.addWidget(chart_card)
        self._v_split.addWidget(bottom)
        self._v_split.setStretchFactor(0, 1)               # chart absorbs resize
        self._v_split.setStretchFactor(1, 0)               # tabs hold their height

        right = self._build_right_dock()
        self._h_split = QSplitter(Qt.Orientation.Horizontal)
        self._h_split.setChildrenCollapsible(False)
        self._h_split.setHandleWidth(6)            # grab affordance
        self._h_split.addWidget(self._v_split)
        self._h_split.addWidget(right)
        self._h_split.setStretchFactor(0, 1)               # left column absorbs resize
        self._h_split.setStretchFactor(1, 0)               # dock holds its width
        # uniform small body inset
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(theme.S2, 0, theme.S2, theme.S2)
        bl.setSpacing(0)
        bl.addWidget(self._h_split)
        cv.addWidget(body, 1)
        self.setCentralWidget(central)

        self._build_status_bar()
        self._install_shortcuts()

        self._popover = IndicatorPopover(self)
        self._toasts = ToastHost(self)                     # overlay child of the window
        self._scrim = _ScrimOverlay(self)  # modal dim behind dialogs

        self._init_worker()
        self._connect_intents()

    # -- shell construction -------------------------------------------------- #
    def _build_header(self) -> QWidget:
        # two rows: chrome strip over the working bar
        header = QFrame()
        header.setObjectName("ChromeHeader")  # full-width square
        outer = QVBoxLayout(header)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # ---- strip 1: the chrome strip ----------
        self._chrome_strip = QFrame()
        self._chrome_strip.setObjectName("ChromeStrip")
        self._chrome_strip.setFixedHeight(32)
        strip = QHBoxLayout(self._chrome_strip)
        # right margin 0 so the Close X sits flush in the corner
        strip.setContentsMargins(theme.S3, 0, 0, 0)
        strip.setSpacing(theme.S1)
        # LEFT: gear + help icon buttons
        left = QHBoxLayout()
        left.setSpacing(theme.S1)
        self._btn_settings = IconButton("gear", "Settings")
        self._btn_settings.clicked.connect(self._show_settings)
        self._btn_help = IconButton("help", "Help")
        self._btn_help.clicked.connect(self._show_help)
        left.addWidget(self._btn_settings)
        left.addWidget(self._btn_help)
        strip.addLayout(left)
        strip.addStretch(1)
        # CENTRE: app-icon tile + name
        center = QHBoxLayout()
        center.setSpacing(theme.S2)
        icon_tile = QLabel()
        icon_tile.setFixedSize(16, 16)
        path = self._icon_path()
        if path:
            pm = QPixmap(path)
            if not pm.isNull():
                icon_tile.setPixmap(pm.scaled(16, 16, Qt.AspectRatioMode.KeepAspectRatio,
                                              Qt.TransformationMode.SmoothTransformation))
        icon_tile.setStyleSheet("background: transparent;")
        name = QLabel(theme.APP_NAME)
        name.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 10.5px;"
            f" letter-spacing: 0.3px; color: {theme.TEXT_3}; background: transparent; }}")
        center.addWidget(icon_tile)
        center.addWidget(name)
        strip.addLayout(center)
        strip.addStretch(1)
        # RIGHT: window controls
        wins = QHBoxLayout()
        wins.setSpacing(theme.S1)
        self._btn_min = WinControlButton("min")
        self._btn_min.clicked.connect(self.showMinimized)
        self._btn_max = WinControlButton("max")
        self._btn_max.clicked.connect(self._toggle_maximise)
        self._btn_close = WinControlButton("close")
        self._btn_close.clicked.connect(self.close)
        wins.addWidget(self._btn_min)
        wins.addWidget(self._btn_max)
        wins.addWidget(self._btn_close)
        strip.addLayout(wins)
        outer.addWidget(self._chrome_strip)

        # ---- hairline between the strips ----------
        seam = QFrame()
        seam.setFixedHeight(1)
        seam.setStyleSheet("QFrame { background: rgba(255,255,255,0.05); }")
        outer.addWidget(seam)

        # ---- strip 2: the working bar ----------
        bar = QWidget()
        work = QHBoxLayout(bar)
        work.setContentsMargins(theme.S5, theme.S3, theme.S4, theme.S3)
        work.setSpacing(theme.S4)
        self._symbol_label = QLabel(self._symbol)
        self._symbol_label.setTextFormat(Qt.TextFormat.PlainText)   # user-typed text
        # incoming symbol at reduced opacity while a switch is in flight
        self._symbol_style_full = (
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 19px; font-weight: 600;"
            f" color: {theme.TEXT_1}; background: transparent; }}")
        self._symbol_style_pending = (
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 19px; font-weight: 600;"
            f" color: rgba(234,240,250,0.45); background: transparent; }}")
        self._symbol_label.setStyleSheet(self._symbol_style_full)
        self._segmented = SegmentedControl(list(config.VALID_CHART_TIMEFRAMES), self._timeframe)
        work.addWidget(self._symbol_label)
        work.addWidget(self._segmented)
        # market session line, text only
        self._status_label = QLabel("connecting...")
        self._status_label.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 12px;"
            f" color: {theme.TEXT_2}; background: transparent; }}")
        work.addWidget(self._status_label)
        self._had_quote = False                  # warm "connecting..." until the first quote
        # right-aligned actions: stretch first, then the buttons
        work.addStretch(1)
        self._btn_new_alert = QPushButton("New Alert")     # the one accent-filled element
        self._btn_new_alert.setProperty("variant", "primary")
        self._btn_new_alert.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_new_alert.clicked.connect(self._new_alert)
        work.addWidget(self._btn_new_alert)
        # the armed count lives on the Alerts tab label
        self._btn_add = self._work_button("Add symbol", self._focus_add_symbol)
        self._btn_ind = self._work_button("Indicators", self._toggle_popover)
        self._btn_new_order = self._work_button("New Order", self._new_order)
        work.addWidget(self._btn_add)
        work.addWidget(self._btn_ind)
        work.addWidget(self._btn_new_order)
        # Reset lives inside Settings
        outer.addWidget(bar)
        return header

    # -- the armed-count chip on the Alerts tab --------------------- #
    def _set_armed_count(self, n: int) -> None:
        self._tab_count.setText(str(min(n, 99)))
        self._tab_count.setVisible(n > 0)

    # -- frameless window behaviour ------------------------- #
    def _toggle_maximise(self) -> None:
        if self._is_maxed or self.isMaximized():
            if self.isMaximized():
                self.showNormal()                  # native fallback path
            elif self._normal_geom is not None:
                self.setGeometry(self._normal_geom)
            self._is_maxed = False
            self._btn_max.set_kind("max")
        else:
            self._normal_geom = self.geometry()
            scr = self.screen() or QApplication.primaryScreen()
            if scr is not None:
                self.setGeometry(scr.availableGeometry())  # not the full screen
            else:
                self.showMaximized()
            self._is_maxed = True
            self._btn_max.set_kind("restore")

    def _in_chrome_strip(self, gpos) -> bool:
        strip = getattr(self, "_chrome_strip", None)
        if strip is None:
            return False
        local = strip.mapFromGlobal(gpos)
        if not strip.rect().contains(local):
            return False
        child = strip.childAt(local)
        # only the bare strip / labels initiate a move, never a button
        from PySide6.QtWidgets import QAbstractButton
        node = child
        while node is not None and node is not strip:
            if isinstance(node, QAbstractButton):
                return False
            node = node.parentWidget()
        return True

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and not (self._is_maxed or self.isMaximized())):
            edges = edge_at(self, event.position().toPoint(), self._resize_margin)
            if edges:
                if not start_system_resize(self, edges):     # native, else manual
                    self._resize_edges = edges
                    self._move_origin = event.globalPosition().toPoint()
                    self._start_geom = self.geometry()
                event.accept(); return
            if self._in_chrome_strip(event.globalPosition().toPoint()):
                if not start_system_move(self):              # native, else manual
                    self._move_origin = event.globalPosition().toPoint()
                    self._start_geom = self.geometry()
                event.accept(); return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        # manual degrade path only
        if self._move_origin is not None:
            delta = event.globalPosition().toPoint() - self._move_origin
            g = self._start_geom
            if self._resize_edges:
                from PySide6.QtCore import QRect
                r = QRect(g)
                if self._resize_edges & Qt.Edge.LeftEdge:
                    r.setLeft(g.left() + delta.x())
                if self._resize_edges & Qt.Edge.RightEdge:
                    r.setRight(g.right() + delta.x())
                if self._resize_edges & Qt.Edge.TopEdge:
                    r.setTop(g.top() + delta.y())
                if self._resize_edges & Qt.Edge.BottomEdge:
                    r.setBottom(g.bottom() + delta.y())
                if r.width() >= self.minimumWidth() and r.height() >= self.minimumHeight():
                    self.setGeometry(r)
            else:
                self.move(g.topLeft() + delta)
            event.accept(); return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        self._move_origin = None
        self._resize_edges = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if (event.button() == Qt.MouseButton.LeftButton
                and self._in_chrome_strip(event.globalPosition().toPoint())):
            self._toggle_maximise(); event.accept(); return
        super().mouseDoubleClickEvent(event)

    def _work_button(self, text: str, on_click) -> QToolButton:
        b = QToolButton()
        b.setText(text)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setFixedHeight(34)
        b.setStyleSheet(
            f"QToolButton {{ color: {theme.TOOLWORK_LABEL}; background: transparent;"
            f" border: 1px solid {theme.TOOLWORK_BORDER}; border-radius: {theme.R_ATOM}px;"
            f" padding: 0 14px; font-size: 13px; font-weight: 500; }}"
            f"QToolButton:hover {{ background: {theme.NESTED}; color: {theme.TEXT_1}; }}"
            f"QToolButton:disabled {{ color: {theme.TEXT_3}; border-color: {theme.HAIRLINE}; }}")
        if on_click is not None:
            b.clicked.connect(on_click)
        return b

    def _build_bottom_dock(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setObjectName("DockTabs")
        tabs.setTabBar(_DockTabBar())  # fixed-width painted indicator
        tabs.setMinimumHeight(200)                 # floor; the splitter owns the split
        self._tabs = tabs
        self._alerts_tab = AlertsTab()
        self._alerts_tab.armed_count_changed.connect(self._set_armed_count)
        tabs.addTab(self._alerts_tab, "Alerts")
        self._portfolio_panel = PortfolioPanel()
        tabs.addTab(self._portfolio_panel, "Portfolio")
        self._trade_log_panel = TradeLogPanel()
        tabs.addTab(self._trade_log_panel, "Trade log")
        # armed count chip on RightSide; unread-fired badge on LeftSide
        self._tab_count = QLabel("")
        self._tab_count.setObjectName("TabCount")
        self._tab_count.setAutoFillBackground(True)  # opaque on inactive tabs
        self._tab_count.setToolTip("Armed alerts")
        self._tab_count.hide()
        tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.RightSide, self._tab_count)
        self._badge = QLabel("")                           # unread-fired count
        self._badge.setObjectName("Badge")
        self._badge.setToolTip("Unread fired alerts")
        self._badge.hide()
        tabs.tabBar().setTabButton(0, QTabBar.ButtonPosition.LeftSide, self._badge)
        # "alerts paused" pill in the tab bar's right corner
        self._alerts_paused = False
        self._paused_pill = QLabel("alerts paused")
        self._paused_pill.setStyleSheet(
            f"QLabel {{ color: {theme.AMBER}; background: {theme.AMBER_SOFT};"
            f" border: 1px solid rgba(217,165,33,0.28); border-radius: 8px;"
            f" padding: 3px 10px; font-family: {theme.FONT_MONO}; font-size: 11px;"
            f" margin-right: {theme.S3}px; }}")
        self._paused_pill.setToolTip("Active symbol is stale - alerts are paused"
                                     " until a fresh quote")
        self._paused_pill.hide()
        tabs.setCornerWidget(self._paused_pill, Qt.Corner.TopRightCorner)
        self._alerts_tab.paused_changed.connect(self._on_alerts_paused)
        self._refresh_badge()                              # hide empty badge
        tabs.currentChanged.connect(self._on_tab_changed)
        return tabs

    @Slot(bool)
    def _on_alerts_paused(self, paused: bool) -> None:
        self._alerts_paused = bool(paused)
        self._sync_paused_pill()

    def _sync_paused_pill(self) -> None:
        self._paused_pill.setVisible(self._alerts_paused
                                     and self._tabs.currentIndex() == 0)

    def _build_right_dock(self) -> QWidget:
        self._watchlist = WatchlistPanel()
        host = QFrame()
        host.setObjectName("Glass")  # glass dock, no glow
        hl = QVBoxLayout(host)
        hl.setContentsMargins(theme.S4, theme.S4, theme.S4, theme.S4)
        hl.setSpacing(0)                  # inner scroll owns the seam
        self._risk_panel = RiskPanel()
        self._risk_panel.setObjectName("Panel")  # the same card
        # watchlist + risk in a height-bounded scroll area inside the glass dock
        content = QWidget()
        content.setObjectName("DockContent")
        cl = QVBoxLayout(content)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(theme.S3)           # watchlist/risk seam
        self._dock_layout = cl                                 # rebalance targets this column
        cl.addWidget(self._watchlist, 1)                       # watchlist scrolls/shrinks first
        cl.addWidget(self._risk_panel, 0)                      # pinned beneath the watchlist
        cl.addStretch(0)                                       # pins collapsed headers to the top
        dock_scroll = QScrollArea()
        dock_scroll.setObjectName("DockScroll")
        dock_scroll.setWidgetResizable(True)
        dock_scroll.setFrameShape(QFrame.Shape.NoFrame)
        dock_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        dock_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        dock_scroll.setWidget(content)
        dock_scroll.viewport().setAutoFillBackground(False)    # let the glass show through
        self._dock_scroll = dock_scroll
        hl.addWidget(dock_scroll)
        # re-balance the dock flex on section toggle
        self._watchlist.collapse_toggled.connect(self._on_wl_collapse)
        self._risk_panel.collapse_toggled.connect(self._on_risk_collapse)
        outer = QWidget()
        ol = QVBoxLayout(outer)
        ol.setContentsMargins(0, 0, 0, 0)  # body wrapper owns the inset
        ol.addWidget(host)
        outer.setMinimumWidth(380)
        return outer

    def _rebalance_dock(self) -> None:
        # expanded section fills, collapsed one yields
        wl_c, risk_c = self._wl_collapsed, self._risk_collapsed
        wl_stretch = 0 if wl_c else 1
        # risk fills only when expanded AND the watchlist is collapsed
        risk_stretch = 1 if (not risk_c and wl_c) else 0
        self._dock_layout.setStretch(0, wl_stretch)            # watchlist
        self._dock_layout.setStretch(1, risk_stretch)          # risk
        # trailing stretch absorbs space only when both collapse
        self._dock_layout.setStretch(self._dock_layout.count() - 1,
                                     1 if (wl_c and risk_c) else 0)
        self._risk_panel.set_roomy(wl_c and not risk_c)
        # force the dock re-layout now
        self._watchlist.updateGeometry()
        self._risk_panel.updateGeometry()
        self._dock_layout.invalidate()
        self._clamp_to_workarea()  # never grow off-screen

    def _on_wl_collapse(self, collapsed: bool) -> None:
        self._wl_collapsed = collapsed
        self._rebalance_dock()

    def _on_risk_collapse(self, collapsed: bool) -> None:
        self._risk_collapsed = collapsed
        self._rebalance_dock()

    def _build_status_bar(self) -> None:
        status = QStatusBar(self)
        status.setSizeGripEnabled(False)           # no native grip notch
        # align items with the content margins
        status.setContentsMargins(theme.S6, 0, theme.S6, theme.S1)
        self.setStatusBar(status)
        # data-health chip, shown only while degraded
        self._health_dot = StatusDot("stale")
        self._health_label = QLabel("")
        self._health_label.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 11px;"
            f" color: {theme.TEXT_2}; background: transparent;"
            f" padding-right: 14px; }}")
        self._health_dot.hide()
        self._health_label.hide()
        status.addWidget(self._health_dot)
        status.addWidget(self._health_label)
        self._health_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._health_label.mousePressEvent = \
            lambda _e: self._toggle_integrity_popover()
        self._integrity_view = None
        self._integrity_pop = None
        self._statusbar_label = QLabel("USD · last poll -")
        self._statusbar_label.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 11px; color: {theme.TEXT_3};"
            f" background: transparent; }}")
        self._statusbar_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._statusbar_label.mousePressEvent = \
            lambda _e: self._toggle_integrity_popover()
        status.addWidget(self._statusbar_label)
        # shown once the worker reports the in-memory fallback
        self._db_notice_label = QLabel("NO SAVED DATA")
        self._db_notice_label.setObjectName("InlineWarn")
        self._db_notice_label.hide()
        status.addPermanentWidget(self._db_notice_label)

    # -- worker lifecycle ---------------------------------------------------- #
    def _init_worker(self) -> None:
        self._thread = QThread(self)
        self._worker = PollWorker(self._symbol, self._timeframe,
                                  poll_interval_s=config.POLL_INTERVAL_S,
                                  render_cap=config.RENDER_CAP,
                                  request_timeout_s=config.REQUEST_TIMEOUT_S,
                                  venue=config.DEFAULT_CRYPTO_VENUE)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start)
        # worker -> UI (queued), connected before the thread starts
        self._worker.snapshot_ready.connect(self._chart.update_snapshot)
        self._worker.snapshot_ready.connect(self._on_snapshot)
        self._worker.snapshot_ready.connect(self._popover.sync_warnings)
        self._worker.watchlist_ready.connect(self._watchlist.set_state)
        self._worker.watchlist_ready.connect(self._on_watchlist)
        self._worker.indicator_settings_ready.connect(self._popover.set_settings)
        self._worker.add_rejected.connect(self._watchlist.show_add_error)
        self._worker.remove_rejected.connect(self._watchlist.show_remove_error)
        self._worker.alerts_ready.connect(self._on_alerts_ready)
        self._worker.alert_events.connect(self._on_alert_events)
        self._worker.db_notice.connect(self._on_db_notice)
        self._worker.alert_rejected.connect(self._on_alert_rejected)
        self._worker.order_result.connect(self._on_order_result)   # never-dropped
        self._worker.settings_applied.connect(self._on_settings_applied)
        self._alert_remove.connect(self._worker.remove_alert)   # queued, one-writer
        self._stop_worker.connect(self._worker.stop)
        self._thread.start()

    def _connect_intents(self) -> None:
        # UI -> worker (queued cross-thread)
        self._watchlist.add_requested.connect(self._worker.add_symbol)
        self._watchlist.remove_requested.connect(self._worker.remove_symbol)
        # selects + timeframe clicks coalesce through one 250ms single-shot timer
        self._switch_timer = QTimer(self)
        self._switch_timer.setSingleShot(True)
        self._switch_timer.setInterval(SWITCH_DEBOUNCE_MS)
        self._switch_timer.timeout.connect(self._fire_switch)
        self._pending_sym: str | None = None
        self._pending_tf: str | None = None
        self._watchlist.select_requested.connect(self._on_select_intent)
        self._popover.settings_changed.connect(self._worker.set_indicator_settings)
        self._segmented.changed.connect(self._on_timeframe_intent)
        self._chart.retry_requested.connect(self._worker.request_poll)
        self._alerts_tab.rearm_requested.connect(self._worker.rearm_alert)
        self._alerts_tab.remove_requested.connect(self._worker.remove_alert)
        self._alerts_tab.delete_requested.connect(self._on_alert_delete)  # unread fixup
        self._alerts_tab.disarm_requested.connect(self._worker.disarm_alert)
        self._toasts.rearm_requested.connect(self._worker.rearm_alert)
        self._trade_log_panel.clear_requested.connect(self._worker.clear_trade_log)

    # -- worker -> UI slots -------------------------------------------------- #
    @Slot(object)
    def _on_snapshot(self, snap: RenderSnapshot) -> None:
        self._last_snapshot = snap
        if snap.symbol and snap.symbol != self._symbol:
            self._set_active_symbol(snap.symbol)
        # the header shows the market session, not Live/Stale
        self._had_quote = bool(snap.last_update_ts) or self._had_quote
        self._render_session(snap)
        self._sync_header_pending()  # confirm-or-revert
        if snap.last_update_ts:
            hhmmss = time.strftime("%H:%M:%S", time.localtime(snap.last_update_ts))
            self._statusbar_label.setText(f"USD · last poll {hhmmss}")
        if snap.portfolio is not None:  # mark-to-market render
            self._portfolio_panel.set_view(snap.portfolio)
            self._trade_log_panel.set_view(snap.portfolio)
        if snap.risk is not None:  # risk panel
            self._risk_panel.set_view(snap.risk)
            self._risk_timeframe = snap.risk.timeframe
        if snap.context is not None:  # context tiles
            self._risk_panel.set_context(snap.context)
        if snap.analytics is not None:
            self._risk_panel.set_analytics(snap.analytics)
        if snap.health is not None:  # health chip
            self._render_health(snap.health)
        if snap.integrity is not None:
            self._integrity_view = snap.integrity
        if self._ticket is not None and snap.symbol == self._ticket_symbol:   # live refresh
            q = snap.quote
            self._ticket.update_quote(
                q.mark if q is not None else None, q.ts if q is not None else None,
                bool(snap.last_update_ts is not None and not snap.live),
                bool(snap.last_update_ts is None))

    @Slot(object)
    def _on_watchlist(self, state: WatchlistState) -> None:
        if state.active and state.active != self._symbol:
            self._set_active_symbol(state.active)
        elif state.active is None and state.is_empty and self._symbol:
            # last symbol removed; clear the residue
            self._set_active_symbol(None)
            self._chart.show_no_symbol()

    @Slot(object)
    def _on_alerts_ready(self, view: object) -> None:
        if not isinstance(view, AlertsView):
            return
        self._last_alerts = view
        self._deleting_alert_ids &= {r.id for r in view.rows}   # drop settled deletes
        self._alerts_tab.set_state(view)
        # close an open arm dialog once the worker has persisted the new alert
        if (self._arm_pending and self._dialog is not None
                and view.count > self._arm_pre_count):
            self._arm_pending = False
            self._dialog.accept()

    @Slot(object)
    def _on_alert_events(self, events: object) -> None:
        # never-dropped channel: one toast per fire, bump unread
        try:
            evs = list(events)
        except TypeError:
            return
        for ev in evs:
            self._toasts.add_event(ev)
        if self._tabs.currentIndex() != 0:                 # not viewing Alerts -> unread
            self._unread += len(evs)
            self._refresh_badge()

    @Slot(str)
    def _on_alert_rejected(self, reason: str) -> None:
        self._arm_pending = False
        if self._dialog is not None:
            self._dialog.show_reject(reason)
        else:
            self.statusBar().showMessage(f"Alert not armed - {reason}", 6000)

    @Slot(int, bool)
    def _on_alert_delete(self, alert_id: int, fired: bool) -> None:
        from mahad.data.symbols import unread_after_delete
        if alert_id in self._deleting_alert_ids:           # no double-decrement
            return
        self._deleting_alert_ids.add(alert_id)
        on_alerts = self._tabs.currentIndex() == 0
        self._unread = unread_after_delete(self._unread, fired, on_alerts)
        self._refresh_badge()
        self._alert_remove.emit(alert_id)                  # queued -> worker thread

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        if index == 0:                                     # viewing Alerts clears unread
            self._unread = 0
            self._refresh_badge()
        self._sync_paused_pill()  # per-tab visibility

    def _refresh_badge(self) -> None:
        if self._unread > 0:
            self._badge.setText(str(self._unread))
            self._badge.show()
        else:
            self._badge.hide()

    @Slot(str)
    # -- the 250ms switch coalescer ------------------------------- #
    def _on_select_intent(self, symbol: str) -> None:
        # strict first-wins while a switch is in flight
        if self._chart.switch_in_flight() and symbol != self._chart.pending_symbol():
            # the blocked click gets no pending highlight
            self._watchlist.clear_pending_select()
            sym_now = self._chart.pending_symbol() or self._symbol
            self.statusBar().showMessage(f"loading {sym_now}...", 1500)
            return
        if symbol == self._symbol and self._pending_sym in (None, symbol) \
                and self._pending_tf is None:
            return                                          # pure no-op click
        self._pending_sym = symbol
        if symbol != self._symbol:
            self._chart.begin_switch(symbol)               # symbol switches own the loading UI
        else:
            self._chart.cancel_switch()                    # re-click back to current mid-window
        self._sync_header_pending()  # the headline follows
        self._switch_timer.start()

    def _on_timeframe_intent(self, tf: str) -> None:
        if tf == (self._pending_tf or self._timeframe):
            return
        self._pending_tf = tf
        self._switch_timer.start()

    def _fire_switch(self) -> None:
        # timer expiry: send the latest pair, one fetch
        sym, tf = self._pending_sym, self._pending_tf
        self._pending_sym = None
        self._pending_tf = None
        if sym is not None and sym == self._symbol:
            sym = None                                     # net no-op select
        if tf is not None and tf == self._timeframe:
            tf = None                                      # net no-op tf
        if sym is None and tf is None:
            self._chart.cancel_switch()                    # nothing to do - clear any overlay
            self._sync_header_pending()  # restore the headline
            return
        if tf is not None:
            self._worker.set_timeframe(tf)                 # queued cross-thread
            self._on_timeframe_changed(tf)
        if sym is not None:
            self._worker.select_symbol(sym)                # queued cross-thread

    def _render_session(self, snap: RenderSnapshot | None = None) -> None:
        if not self._symbol:
            self._status_label.setText("")
            self._status_label.setToolTip("")
            return
        if not self._had_quote or snap is None:
            self._status_label.setText("connecting...")
            self._status_label.setToolTip("")
            return
        self._status_label.setText(snap.session_summary)
        if snap.session_state in ("open", "open24") or not snap.last_update_ts:
            self._status_label.setToolTip("")
        else:
            hhmmss = time.strftime("%H:%M:%S", time.localtime(snap.last_update_ts))
            self._status_label.setToolTip(f"Last update {hhmmss}")

    def _sync_header_pending(self) -> None:
        pend = self._chart.pending_symbol() if self._chart.switch_in_flight() else None
        if pend:
            self._symbol_label.setText(pend)
            self._symbol_label.setStyleSheet(self._symbol_style_pending)
        else:
            self._symbol_label.setText(self._symbol or "")
            self._symbol_label.setStyleSheet(self._symbol_style_full)

    def _on_timeframe_changed(self, tf: str) -> None:
        if tf == self._timeframe:                          # a redundant re-select keeps the view
            return
        self._timeframe = tf
        self._update_title()
        self._chart.defer_fit()       # fit the new timeframe's first frame

    def _set_active_symbol(self, symbol: str | None) -> None:
        self._symbol = symbol
        self._symbol_label.setText(symbol or "")
        self._update_title()
        self._render_session()                       # the session rule follows the symbol

    def _update_title(self) -> None:
        # compact live title for the taskbar / alt-tab
        if self._symbol:
            self.setWindowTitle(
                f"{theme.APP_NAME} · {self._symbol} {self._timeframe}")
        else:                                  # emptied watchlist
            self.setWindowTitle(theme.APP_NAME)

    # -- New Alert ----------------------------------------------------------- #
    def _new_alert(self) -> None:
        if self._modal_busy:                               # refuse a stacked open
            return
        snap = self._last_snapshot
        mark = snap.quote.mark if (snap is not None and snap.quote is not None) else None
        warming = bool(snap is not None and snap.last_update_ts is None)
        stale = bool(snap is not None and snap.last_update_ts is not None and not snap.live)
        closed = snap.closed_count if snap is not None else 0
        fired = {(r.symbol, r.summary)
                 for r in (self._last_alerts.rows if self._last_alerts else ())
                 if not r.armed}
        dlg = AlertDialog(self._symbol, mark, stale=stale, warming=warming,
                          closed_count=closed, fired_summaries=fired, parent=self)
        dlg.arm_requested.connect(self._worker.arm_alert)
        dlg.arm_requested.connect(self._on_arm_requested)
        self._dialog = dlg
        try:
            self._exec_modal(dlg)
        finally:
            self._dialog = None
            self._arm_pending = False

    @Slot(object)
    def _on_arm_requested(self, _payload: object) -> None:
        self._arm_pre_count = self._last_alerts.count if self._last_alerts else 0
        self._arm_pending = True

    # -- New Order / Reset ----------------------------------------- #
    def _new_order(self) -> None:
        if self._modal_busy:                               # refuse a stacked open
            return
        snap = self._last_snapshot
        symbol = self._symbol
        mark = snap.quote.mark if (snap is not None and snap.quote is not None) else None
        ts = snap.quote.ts if (snap is not None and snap.quote is not None) else None
        warming = bool(snap is None or snap.last_update_ts is None)
        stale = bool(snap is not None and snap.last_update_ts is not None and not snap.live)
        asset_class = "crypto" if (symbol and "/" in symbol) else "stock"
        dlg = OrderTicket(symbol, asset_class, mark, ts, stale, warming, parent=self)
        dlg.order_requested.connect(self._worker.place_order)
        self._ticket = dlg
        self._ticket_symbol = symbol
        try:
            self._exec_modal(dlg)
        finally:
            self._ticket = None
            self._ticket_symbol = None

    def _reset(self) -> None:
        if self._modal_busy:                               # refuse a stacked open
            return
        export_ok = self._trade_log_panel.export_succeeded()
        dlg = ResetDialog(config.STARTING_CASH, export_ok, parent=self)
        dlg.reset_requested.connect(self._worker.reset_portfolio)
        self._exec_modal(dlg)

    @Slot(object)
    def _on_order_result(self, result: object) -> None:
        if self._ticket is not None:
            self._ticket.show_result(result)
        elif isinstance(result, dict):                     # ticket gone, never lose feedback
            if result.get("ok"):
                self.statusBar().showMessage(f"Order {result.get('summary')}", 6000)
            else:
                self.statusBar().showMessage(f"Order not placed - {result.get('reason')}", 6000)

    # -- action handlers ----------------------------------------------------- #
    def _focus_add_symbol(self) -> None:
        self._watchlist._input.setFocus()

    def _toggle_popover(self) -> None:
        if self._popover.isVisible():
            self._popover.hide()
            return
        # clamp the popover to the work area, opening above if no room below
        self._popover.adjustSize()
        pw, ph = self._popover.width(), self._popover.height()
        scr = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        top_left = self._btn_ind.mapToGlobal(QPoint(0, self._btn_ind.height() + 4))
        x, y = top_left.x(), top_left.y()
        if x + pw > scr.right():
            x = scr.right() - pw                      # shift left to stay on-screen
        x = max(x, scr.left())
        if y + ph > scr.bottom():                     # no room below -> open above
            y = self._btn_ind.mapToGlobal(QPoint(0, -ph - 4)).y()
        y = max(y, scr.top())
        self._popover.move(QPoint(x, y))
        self._popover.show()

    @Slot(object)
    def _render_health(self, hv: object) -> None:
        state = getattr(hv, "state", "ok")
        if state == "ok":
            self._health_dot.hide()
            self._health_label.hide()
            return
        provider_lines = "".join(
            f"\n{name}: {st}" for name, st in getattr(hv, "providers", ()) or ())
        if provider_lines:
            provider_lines = "\nProviders:" + provider_lines
        self._health_dot.set_state("stale")
        self._health_label.setText(getattr(hv, "reason", "retrying"))
        self._health_dot.show()
        self._health_label.show()
        if state == "needs_key":
            # configuration, not an outage
            self._health_label.setToolTip(
                f"{getattr(hv, 'detail', '')}\nAdd the free key to .env "
                "(see .env.example) and restart. Crypto, FX, and the "
                "context tiles run keyless." + provider_lines)
            return
        since = getattr(hv, "since_ts", None)
        since_txt = (time.strftime("%H:%M:%S", time.localtime(since))
                     if since else "-")
        self._health_label.setToolTip(
            f"Last error: {getattr(hv, 'detail', '')}\nSince {since_txt}. "
            "MAHAD keeps the last good data, marks it stale, and retries "
            "with capped backoff." + provider_lines)

    def _toggle_integrity_popover(self) -> None:
        from PySide6.QtWidgets import QFrame, QGridLayout, QLabel
        if self._integrity_pop is not None and self._integrity_pop.isVisible():
            self._integrity_pop.hide()
            return
        view = self._integrity_view
        pop = QFrame(self)
        pop.setObjectName("IntegrityPop")
        pop.setStyleSheet(
            f"QFrame#IntegrityPop {{ background: {theme.SURFACE}; "
            f"border: 1px solid {theme.DIVIDER}; border-radius: 12px; }}")
        grid = QGridLayout(pop)
        grid.setContentsMargins(theme.S4, theme.S3, theme.S4, theme.S3)
        grid.setHorizontalSpacing(theme.S4)
        grid.setVerticalSpacing(4)
        title = QLabel("DATA INTEGRITY")
        title.setObjectName("RiskMetricKicker")
        title.setToolTip("Per-provider feed state and the daily-history "
                         "gap check against the computed NYSE calendar "
                         "(missing trading days inside each symbol's "
                         "cached range).")
        grid.addWidget(title, 0, 0, 1, 2)
        r = 1
        rows = list(getattr(view, "providers", ()) or ())
        if not rows:
            none_lbl = QLabel("no provider activity yet")
            none_lbl.setObjectName("CtxValMuted")
            grid.addWidget(none_lbl, r, 0, 1, 2)
            r += 1
        for row in rows:
            n = QLabel(row.provider)
            n.setObjectName("CtxName")
            v = QLabel(row.state)
            v.setObjectName("CtxVal" if row.state == "ok" else "CtxValMuted")
            v.setTextFormat(Qt.TextFormat.PlainText)
            if row.detail:
                v.setToolTip(f"Last error: {row.detail}")
            grid.addWidget(n, r, 0)
            grid.addWidget(v, r, 1)
            r += 1
        gaps = list(getattr(view, "gaps", ()) or ())
        if gaps:
            gt = QLabel("HISTORY GAP CHECK")
            gt.setObjectName("RiskMetricKicker")
            grid.addWidget(gt, r, 0, 1, 2)
            r += 1
            for gap in gaps:
                n = QLabel(gap.symbol)
                n.setObjectName("CtxName")
                ok_g = gap.missing_days == 0
                v = QLabel(f"{gap.cached_days}d cached · "
                           + ("no gaps" if ok_g
                              else f"{gap.missing_days} missing"))
                v.setObjectName("CtxVal" if ok_g else "CtxValMuted")
                v.setTextFormat(Qt.TextFormat.PlainText)
                v.setToolTip(f"{gap.first} to {gap.last} - US trading days "
                             "only; weekends/holidays never count as "
                             "missing.")
                grid.addWidget(n, r, 0)
                grid.addWidget(v, r, 1)
                r += 1
        pop.adjustSize()
        # clamp above the chip
        from PySide6.QtCore import QPoint
        anchor_pt = self._health_label.mapTo(self, QPoint(0, 0))
        x = max(8, min(anchor_pt.x(), self.width() - pop.width() - 8))
        y = max(8, anchor_pt.y() - pop.height() - 8)
        pop.move(QPoint(x, y))
        pop.show()
        pop.raise_()
        if self._integrity_pop is not None:
            self._integrity_pop.deleteLater()
        self._integrity_pop = pop

    @Slot(str)
    def _on_db_notice(self, message: str) -> None:
        self._db_notice_label.setToolTip(str(message))
        self._db_notice_label.show()

    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut
        pairs = (
            ("Ctrl+N", self._new_order),
            ("Ctrl+Shift+A", self._new_alert),
            ("Ctrl+K", self._focus_add_symbol),
            ("Ctrl+I", self._toggle_popover),
            ("Ctrl+E", self._trade_log_panel.request_export),
            ("Ctrl+Shift+E", self._risk_panel.export_value_history),
            ("Ctrl+,", self._show_settings),
            ("Ctrl+Shift+P", self._open_command_palette),
            ("F1", self._show_help),
        )
        for seq, handler in pairs:
            QShortcut(QKeySequence(seq), self, activated=handler)
        for tf, seq in (("1m", "Ctrl+1"), ("1h", "Ctrl+2"), ("1d", "Ctrl+3")):
            QShortcut(QKeySequence(seq), self,
                      activated=lambda t=tf: self._timeframe_shortcut(t))
        self._btn_new_order.setToolTip("Place a simulated order (Ctrl+N)")
        self._btn_new_alert.setToolTip("Arm a one-shot alert (Ctrl+Shift+A)")
        self._btn_add.setToolTip("Add a symbol to the watchlist (Ctrl+K)")
        self._btn_ind.setToolTip("Indicator overlays (Ctrl+I)")
        self._btn_help.setToolTip("Help (F1) · command palette Ctrl+Shift+P")

    def _timeframe_shortcut(self, tf: str) -> None:
        # route through the same path as a segmented click
        self._segmented.set_active(tf)
        self._on_timeframe_intent(tf)

    def _command_registry(self) -> list:
        rp = self._risk_panel
        return [
            ("New simulated order", "Ctrl+N", self._new_order),
            ("New alert", "Ctrl+Shift+A", self._new_alert),
            ("Add symbol to watchlist", "Ctrl+K", self._focus_add_symbol),
            ("Indicator overlays", "Ctrl+I", self._toggle_popover),
            ("Settings", "Ctrl+,", self._show_settings),
            ("Help", "F1", self._show_help),
            ("Timeframe 1m", "Ctrl+1", lambda: self._timeframe_shortcut("1m")),
            ("Timeframe 1h", "Ctrl+2", lambda: self._timeframe_shortcut("1h")),
            ("Timeframe 1d", "Ctrl+3", lambda: self._timeframe_shortcut("1d")),
            ("Export trades CSV", "Ctrl+E", self._trade_log_panel.request_export),
            ("Export value-history CSV", "Ctrl+Shift+E", rp.export_value_history),
            ("Export risk-metrics CSV", "", rp.export_risk_snapshot),
            ("Show Alerts tab", "", lambda: self._tabs.setCurrentIndex(0)),
            ("Show Portfolio tab", "", lambda: self._tabs.setCurrentIndex(1)),
            ("Show Trade log tab", "", lambda: self._tabs.setCurrentIndex(2)),
            ("Toggle Risk Analytics", "", rp.toggle_analytics),
            ("Toggle Market Context", "", rp.toggle_context),
        ]

    def _open_command_palette(self) -> None:
        # chosen handler runs after the modal closes
        if self._modal_busy:
            return
        from mahad.ui.command_palette import CommandPalette
        dlg = CommandPalette(self._command_registry(), parent=self)
        self._exec_modal(dlg)
        if dlg.chosen is not None:
            dlg.chosen()

    def _show_help(self) -> None:
        if self._modal_busy:                               # refuse a stacked open
            return
        from mahad.ui.glass_dialog import GlassDialog
        dlg = GlassDialog(f"{theme.APP_NAME} - Help", width=560, parent=self)
        b = dlg.body()
        body = QLabel(theme.HELP_TEXT)
        body.setWordWrap(True)
        body.setTextFormat(Qt.TextFormat.PlainText)
        body.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_2}; font-size: 13px; background: transparent; }}")
        b.addWidget(body)
        meth_note = QLabel(theme.HELP_METHODOLOGY)
        meth_note.setWordWrap(True)
        meth_note.setTextFormat(Qt.TextFormat.PlainText)
        meth_note.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-size: 11.5px; background: transparent; }}")
        b.addWidget(meth_note)
        ctx_note = QLabel(theme.HELP_CONTEXT)  # sources + notices
        ctx_note.setWordWrap(True)
        ctx_note.setTextFormat(Qt.TextFormat.PlainText)
        ctx_note.setStyleSheet(
            f"QLabel {{ color: {theme.TEXT_3}; font-size: 11.5px; background: transparent; }}")
        b.addWidget(ctx_note)
        rule = QFrame()                                   # hairline above the identity line
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"QFrame {{ background: {theme.HAIRLINE}; }}")
        b.addWidget(rule)
        ident_line = QLabel(theme.HELP_IDENTITY)          # identity line
        ident_line.setStyleSheet(
            f"QLabel {{ font-family: {theme.FONT_MONO}; font-size: 11px;"
            f" color: {theme.TEXT_3}; background: transparent; }}")
        b.addWidget(ident_line)
        footer = QHBoxLayout()
        footer.addStretch(1)
        ok = QPushButton("Got it")
        ok.setProperty("variant", "primary")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(dlg.accept)
        footer.addWidget(ok)
        dlg.add_footer(footer)
        self._exec_modal(dlg)

    def _show_settings(self) -> None:
        if self._modal_busy:                               # refuse a stacked open
            return
        dlg = SettingsDialog(self._risk_timeframe, parent=self)
        dlg.risk_timeframe_changed.connect(self._worker.set_risk_timeframe)
        self._exec_modal(dlg)
        # open the reset-confirm after exec unwound, via a 0ms singleShot
        if getattr(dlg, "_reset_clicked", False):
            QTimer.singleShot(0, self._reset)

    @Slot(str)
    def _on_settings_applied(self, msg: str) -> None:
        self.statusBar().showMessage(f"Risk timeframe {msg}", 5000)

    # -- app icon ------------------------------------------------------------ #
    def _icon_path(self) -> str | None:
        p = Path(__file__).resolve().parents[2] / "assets" / "mahad.ico"
        return str(p) if p.exists() else None

    def _apply_window_icon(self) -> None:
        path = self._icon_path()
        if not path:
            return
        icon = QIcon(path)
        if not icon.isNull():
            self.setWindowIcon(icon)
            app = QApplication.instance()
            if app is not None:
                app.setWindowIcon(icon)

    # -- modal scrim ----------------------------------------------- #
    def _exec_modal(self, dlg) -> int:
        # dialog runs with the chart dimmed behind it
        self._modal_busy = True                            # block re-entrant opens
        self._scrim.cover()
        try:
            return dlg.exec()
        finally:
            self._scrim.hide()
            self._modal_busy = False

    def showEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().showEvent(event)
        # connect screen changes once the platform window exists
        wh = self.windowHandle()
        if wh is not None and not self._screen_conn:
            wh.screenChanged.connect(lambda _s: self._clamp_to_workarea())
            self._screen_conn = True
        self._clamp_to_workarea()  # fit the work area on launch

    def _clamp_to_workarea(self) -> None:
        # keep the frameless window off the taskbar / work-area edges
        if self._clamping:
            return
        from PySide6.QtCore import QRect
        scr = self.screen() or QApplication.primaryScreen()
        if scr is None:
            return
        avail = scr.availableGeometry()
        g = self.geometry()
        new = QRect(g)
        if new.width() > avail.width():
            new.setWidth(avail.width())
        if new.height() > avail.height():
            new.setHeight(avail.height())
        if new.right() > avail.right():
            new.moveRight(avail.right())
        if new.bottom() > avail.bottom():          # bottom never below the
            new.moveBottom(avail.bottom())         # work area (taskbar)
        if new.left() < avail.left():
            new.moveLeft(avail.left())
        if new.top() < avail.top():
            new.moveTop(avail.top())
        if new != g:
            self._clamping = True
            try:
                self.setGeometry(new)
            finally:
                self._clamping = False

    # -- overlay placement + shutdown ---------------------------------------- #
    def resizeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().resizeEvent(event)
        if hasattr(self, "_toasts"):
            self._toasts.reposition()
        if hasattr(self, "_scrim") and self._scrim.isVisible():
            self._scrim.cover()
        self._clamp_to_workarea()  # never exceed the work area

    def moveEvent(self, event) -> None:  # noqa: N802 (Qt override)
        super().moveEvent(event)
        if hasattr(self, "_toasts"):
            self._toasts.reposition()

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt override)
        # cooperative bounded shutdown, no orphaned threads
        try:
            self._thread.requestInterruption()       # in-flight/queued work bails
            self._stop_worker.emit()                 # queued stop on the worker thread
            self._thread.quit()
            # wait budget covers a worst legal poll cycle before terminate
            budget_s = (2 * config.REQUEST_TIMEOUT_S
                        + config.HELD_POLL_BUDGET * config.HELD_REQUEST_TIMEOUT_S + 5)
            if not self._thread.wait(int(budget_s * 1000)):
                self._thread.terminate()
                self._thread.wait(2000)
        finally:
            event.accept()
