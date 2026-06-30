from __future__ import annotations

import logging
import random
import time
from collections import deque
from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation
from typing import Optional, cast

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from mahad import config
from mahad.data.models import Candle, Quote
from mahad.data.portfolio_view import (ExposureRow, PortfolioView, PositionRow,
                                       ContributionRow, RiskAnalyticsView,
                                       RiskView, StressRow,
                                       TradeRow)
from mahad.data.context_sources import (fetch_boe_rates, fetch_fear_greed,
                                        fetch_gbp_rate,
                                        fetch_treasury_yields, fetch_vix,
                                        read_env_key)
from mahad.data.context_view import (DataIntegrityView, FxRateView, GapRow,
                                     HealthView, IntegrityRow,
                                     MarketContextView, SentimentTile,
                                     UkRatesTile, VixTile, YieldCurveTile,
                                     classify_health)
from mahad.data.repository import (ALERT_CAP, CONTEXT_KEY, INDICATORS_KEY,
                                   RISK_TIMEFRAME_KEY, SECTORS_KEY,
                                   MahadRepository, PersistedTrade,
                                   open_repository)
from mahad.data.source import (MarketDataSource, SourceError,
                               SourceErrorKind, is_crypto_symbol,
                               source_for_symbol)
from mahad.data.symbols import (AlertRowView, AlertsView, WatchlistRow,
                                WatchlistState, validate_add)
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.portfolio import (PortfolioState, Position as EngPosition,
                                    unrealised, portfolio_value)
from mahad.engine.signals import (AlertSpec, evaluate_alert, summary,
                                  validate_params)
from mahad.engine.context import curve_reading, spread_bp, vix_band
from mahad.engine import returns as eng_returns
from mahad.engine import risk_metrics as eng_rm
from mahad.engine.returns import needs_full_repull
from mahad.engine.snapshot import build_render_snapshot
from mahad.engine.market_session import session_line
from mahad.engine.resample import RESAMPLE_TIMEFRAMES, resample_daily_candles
from mahad.engine.risk import (ValueSample, exposure as _exposure,
                               simple_returns as _simple_returns,
                               volatility as _volatility,
                               max_drawdown as _max_drawdown)

log = logging.getLogger("mahad.worker")


def _interrupted() -> bool:
    try:
        from PySide6.QtCore import QThread
        t = QThread.currentThread()
        return bool(t is not None and t.isInterruptionRequested())
    except Exception:
        return False


class PollWorker(QObject):
    snapshot_ready = Signal(object)            # RenderSnapshot (latest-wins, coalesced)
    watchlist_ready = Signal(object)           # WatchlistState
    indicator_settings_ready = Signal(object)  # IndicatorSettings (popover init)
    add_rejected = Signal(str, str)            # (typed_text, reason) - never dropped
    remove_rejected = Signal(str, str)         # (symbol, reason) - held-block feedback
    # -- channels -- #
    alert_events = Signal(object)              # tuple[AlertEvent] - non-coalesced, never dropped
    alerts_ready = Signal(object)              # AlertsView (latest-wins render state)
    alert_rejected = Signal(str)               # arm rejection reason (inline)
    # -- discrete order outcome, never dropped -- #
    order_result = Signal(object)              # dict(ok, fill_mark, summary, reason)
    settings_applied = Signal(str)             # "applied (next cycle)" confirmation
    # -- one-shot degraded-persistence notice -- #
    db_notice = Signal(str)                    # discrete, never dropped

    def __init__(self, symbol: Optional[str] = None, timeframe: Optional[str] = None,
                 poll_interval_s: float = config.POLL_INTERVAL_S,
                 render_cap: int = config.RENDER_CAP,
                 request_timeout_s: float = config.REQUEST_TIMEOUT_S,
                 venue: str = config.DEFAULT_CRYPTO_VENUE,
                 db_url: Optional[str] = None,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._symbol: Optional[str] = symbol or config.DEFAULT_SYMBOL
        self._timeframe = timeframe or config.DEFAULT_TIMEFRAME
        self._poll_interval_s = poll_interval_s
        self._render_cap = render_cap
        self._request_timeout_s = request_timeout_s
        self._venue = venue
        self._db_url = db_url
        self._stop = False
        self._timer: Optional[QTimer] = None
        self._source: Optional[MarketDataSource] = None
        self._repo: Optional[MahadRepository] = None
        self._candles: tuple = ()
        self._last_quote: Optional[Quote] = None
        self._marks: dict[str, Quote] = {}  # in-memory last-known marks
        self._persisted: list = []                  # cached PersistedSymbol list
        self._settings = IndicatorSettings()
        # -- alert state (worker-thread only) -- #
        self._alerts: list[AlertSpec] = []
        self._last_closed_ts: Optional[float] = None   # crossover no-replay baseline
        self._alerts_paused: bool = False
        # -- simulated-trade state (worker-thread only, single writer) -- #
        self._portfolio = PortfolioState(cash=Decimal(str(config.STARTING_CASH)),
                                         realised_pnl=Decimal("0"), positions=())
        self._starting_cash = Decimal(str(config.STARTING_CASH))
        self._trades: list = []
        self._order_in_flight = False
        self._reset_in_flight = False               # single-flight reset
        self._held_cursor = 0
        # -- risk state (worker-thread only) -- #
        self._risk_timeframe = config.RISK_TIMEFRAME
        self._value_history: deque = deque(maxlen=config.VALUE_HISTORY_CAP)
        self._peak_value: Optional[Decimal] = None
        self._peak_ts: Optional[float] = None
        # -- perf state (worker-confined) -- #
        self._adapters: dict[str, MarketDataSource] = {}   # cached provider adapters
        self._history: dict[tuple[str, str], tuple] = {}   # candle cache (symbol, timeframe)
        self._fail_streak = 0                              # consecutive active-fetch failures
        self._backoff_until = 0.0                          # capped backoff window
        self._monotonic = time.monotonic                   # injectable clock seam (tests)
        self._jitter = random.uniform                      # injectable jitter seam (tests)
        # -- state (worker-confined) -- #
        self._wallclock = time.time                # injectable wall-clock seam (tests)
        self._heartbeat: Optional[QTimer] = None   # the 5 s due-grid driver
        self._next_sample_due: Optional[float] = None   # the fixed wall-clock sample grid
        self._db_degraded = False                  # visible degraded persistence
        self._last_error: Optional[tuple] = None   # (kind, message, since_ts) -> health chip
        self._ctx_yields = YieldCurveTile()        # context tiles (last-known, worker-confined)
        self._ctx_sentiment = SentimentTile()
        self._ctx_vix = VixTile()
        self._ctx_ukrates = UkRatesTile()
        self._ctx_fx = FxRateView()  # display-only
        self._integrity = DataIntegrityView()
        self._ctx_due: dict[str, float] = {}       # per-source wall-clock refresh dues
        self._ctx_has_key = False                  # presence only - the value is never logged
        # -- daily-series state (worker-confined) -- #
        self._daily_series: dict[str, tuple] = {}  # official stock 1d candles (DailyBar/Tiingo)
        self._provider_errors: dict[str, object] = {}   # provider -> None | (kind, msg, since)
        self._daily_due: dict[str, float] = {}  # per-symbol daily-coverage dues
        # -- state (the risk-analytics suite; worker-confined) -- #
        self._risk_dirty = True                     # daily data changed -> rebuild
        self._asset_returns: dict[str, list] = {}   # sym -> [(date, r)] (ADJUSTED closes)
        self._asset_closes: dict[str, list] = {}    # sym -> [(date, adj_close)] (stress)
        self._analytics: Optional[RiskAnalyticsView] = None
        self._sectors: dict[str, str] = {}          # profile2 cache + the local fallback

    # -- lifecycle ----------------------------------------------------------- #
    @Slot()
    def start(self) -> None:
        # runs on the worker thread, wired to QThread.started
        self._open_repo()                            # opens DB on the worker thread
        self._run_data_migration()  # one-time, idempotent
        # load persisted indicator settings (defaults if absent/corrupt)
        self._settings = IndicatorSettings.from_dict(self._get_setting(INDICATORS_KEY))
        # seed + load watchlist; active symbol comes from the DB if present
        try:
            self._repo.seed_if_empty(config.DEFAULT_WATCHLIST, self._venue)  # type: ignore[union-attr] # repo seam guarded by the except boundary
            self._reload_watchlist()
            active = self._repo.active_symbol()  # type: ignore[union-attr] # repo seam guarded by the except boundary
            if active:
                self._symbol = active
        except Exception:                            # never crash on a DB hiccup
            log.exception("watchlist load failed; continuing with default symbol")

        self._load_alerts()                          # load armed/fired alerts
        self._load_portfolio()                       # load portfolio/positions/trades
        self._risk_timeframe = config.valid_risk_timeframe(self._get_setting(RISK_TIMEFRAME_KEY))
        self._load_value_history()                   # restore VH + peak (no seed point)
        self.indicator_settings_ready.emit(self._settings)
        self._emit_watchlist()
        self._emit_alerts()
        self._bind_source()
        self._ensure_stock_history(self._symbol)  # official 1d series
        self._load_sectors()  # the concentration roll-up
        self._risk_dirty = True  # first analytics build

        self._timer = QTimer(self)
        self._timer.setInterval(int(self._poll_interval_s * 1000))
        self._timer.timeout.connect(self._poll)
        self._timer.start()
        QTimer.singleShot(0, self._poll)             # immediate first poll
        self._load_context_cache()                   # tiles populate instantly offline
        self._start_heartbeat()                      # the wall-clock due grid
        if self._db_degraded:                        # degradation is never silent
            self.db_notice.emit("Running without saved data - the database "
                                "could not be opened; this session will not persist.")

    @Slot()
    def stop(self) -> None:
        # cooperative; the running poll checks self._stop between phases
        self._stop = True
        if self._timer is not None:
            self._timer.stop()
        if self._heartbeat is not None:              # no orphaned heartbeat
            self._heartbeat.stop()
            self._heartbeat = None
        if self._repo is not None:
            try:
                self._repo.close()
            except Exception:
                log.exception("error closing repository")
            self._repo = None

    # -- polling ------------------------------------------------------------- #
    @Slot()
    def request_poll(self) -> None:
        # Retry button: clears backoff so the user isn't made to wait it out
        if not self._stop:
            self._backoff_until = 0.0
            QTimer.singleShot(0, self._poll)

    @Slot()
    def _poll(self) -> None:
        if self._stop or _interrupted() or not self._symbol or self._source is None:
            return
        if self._monotonic() < self._backoff_until:                # capped backoff
            return                                                 # (timer ticks skipped; user
        result = self._source.fetch(self._symbol, self._timeframe)  # intents clear the window)
        _active_provider = "kraken" if is_crypto_symbol(self._symbol) else "finnhub"
        error_reason: Optional[str] = None
        if result.ok:
            self._fail_streak = 0
            self._last_error = None                            # health chip -> ok
            self._note_provider(_active_provider, None)
            candles = self._chart_candles(self._symbol, self._timeframe, result.candles)
            self._candles = candles
            self._history[(self._symbol, self._timeframe)] = candles  # cache
            self._last_quote = result.quote
            quote = result.quote
        else:
            self._note_provider(_active_provider, result.error)
            if (result.error is not None
                    and result.error.kind in (SourceErrorKind.NEEDS_KEY,
                                              SourceErrorKind.INVALID_KEY)):
                error_reason = result.error.message     # the friendly copy
            else:
                error_reason = str(result.error) if result.error else "unavailable"
            _kind = result.error.kind.value if result.error else "unknown"
            _since = self._last_error[2] if self._last_error else self._wallclock()
            self._last_error = (_kind, error_reason, _since)   # health chip
            log.warning("fetch failed for %s (%s): %s",
                        self._symbol, self._timeframe, error_reason)
            self._enter_backoff()                                  # this frame still emits below
            if self._last_quote is not None:
                quote = replace(self._last_quote, stale=True)     # keep last good, mark stale
                self._last_quote = quote
            else:
                quote = None                                       # warming up / no quote yet
            if result.candles and not self._candles:
                self._candles = result.candles
        if quote is not None:
            self._marks[self._symbol] = quote                      # cache last-known mark
        # emit the active-symbol frame first
        events = self._evaluate_alerts()                           # worker thread
        self._emit_snapshot(error_reason)
        self._emit_watchlist()
        if events:
            self.alert_events.emit(tuple(events))                  # never-dropped channel
        self._emit_alerts()
        if self._stop:                                             # stop between phases
            return
        if self._poll_held():                                      # held marks
            # refresh rows with the new held marks; same error reason
            self._emit_watchlist()
            self._emit_snapshot(error_reason)

    def _enter_backoff(self) -> None:
        self._fail_streak += 1
        delay = min(config.BACKOFF_CAP_S,
                    self._poll_interval_s * (2 ** self._fail_streak))
        self._backoff_until = self._monotonic() + delay * self._jitter(0.75, 1.25)

    def _emit_snapshot(self, error_reason: Optional[str] = None) -> None:
        snap = build_render_snapshot(self._candles, self._last_quote, self._render_cap,
                                     symbol=self._symbol, error=error_reason,
                                     settings=self._settings,
                                     poll_interval_s=self._poll_interval_s)
        sess_state: str
        sess_summary: str
        if self._symbol:                                  # session computed worker-side
            asset_cls = "crypto" if "/" in self._symbol else "stock"
            sess_state, sess_summary = session_line(asset_cls, time.time())
        else:
            sess_state, sess_summary = "", ""
        snap = replace(snap, portfolio=self._build_portfolio_view(),
                       risk=self._build_risk_view(),                  # mark-to-market + risk
                       timeframe=self._timeframe,                     # basis label
                       context=self._build_context_view(),            # context tiles
                       health=self._build_health_view(),              # health chip
                       analytics=self._analytics,
                       integrity=self._integrity_now(),
                       session_state=sess_state,                      # market-session line
                       session_summary=sess_summary)
        self.snapshot_ready.emit(snap)

    # -- alert evaluation (pure engine, gated here on staleness) ------------- #
    def _evaluate_alerts(self) -> list:
        active = self._symbol
        quote = self._last_quote
        if active is None:
            self._alerts_paused = False
            return []
        if (quote is None or quote.stale or
                config.is_stale(quote.ts, poll_interval_s=self._poll_interval_s)):
            self._alerts_paused = True                             # "alerts paused"
            return []
        self._alerts_paused = False

        closed = [c for c in self._candles if c.is_closed]
        closed_closes = [c.close for c in closed]
        closed_ts = [c.ts for c in closed]
        mark = quote.mark
        if self._last_closed_ts is None:                          # baseline: no replay
            new_indices: list[int] = []
        else:
            new_indices = [i for i, t in enumerate(closed_ts) if t > self._last_closed_ts]

        now = time.time()
        events: list = []
        for spec in list(self._alerts):                  # snapshot: tolerate a concurrent change
            if spec.symbol != active or not spec.armed:
                continue
            try:
                ev, new_spec = evaluate_alert(
                    spec, closed_closes=closed_closes, closed_ts=closed_ts, mark=mark,
                    timeframe=self._timeframe, new_indices=new_indices, now=now)
            except Exception:                                     # never crash on eval
                log.exception("alert eval failed (%s)", spec.condition_type)
                continue
            if ev is None:
                continue
            try:                                                  # persist before mutate
                if self._repo is not None and spec.id is not None:
                    self._repo.set_alert_state(spec.id, armed=False,
                                               fired_at=new_spec.fired_at)
            except Exception:
                log.exception("persist alert fire failed; keeping armed")
                continue                                          # no desync, drop the event
            for _j, _cur in enumerate(self._alerts):      # apply by identity (idx may be stale)
                if _cur is spec:
                    self._alerts[_j] = new_spec
                    break
            events.append(ev)

        if closed_ts:
            self._last_closed_ts = max(closed_ts)
        return events

    def _emit_alerts(self) -> None:
        active = self._symbol
        rows = tuple(
            AlertRowView(id=spec.id if spec.id is not None else -1, symbol=spec.symbol,
                         condition_type=spec.condition_type, direction=spec.direction,
                         summary=summary(spec), armed=spec.armed, fired_at=spec.fired_at,
                         not_active=(spec.symbol != active))
            for spec in self._alerts)
        self.alerts_ready.emit(AlertsView(rows=rows, paused=self._alerts_paused,
                                          active_symbol=active, count=len(rows),
                                          cap=ALERT_CAP))

    # -- alert intents (queued slots, all on the worker thread) -------------- #
    @Slot(object)
    def arm_alert(self, payload: object) -> None:
        if not isinstance(payload, dict) or self._repo is None or self._stop:
            return
        active = self._symbol
        if not active:
            self.alert_rejected.emit("add a symbol to the watchlist first")
            return
        condition_type = str(payload.get("condition_type") or "")
        direction = payload.get("direction")
        ok, params, reason = validate_params(condition_type,
                                             cast("Optional[dict[str, object]]",
                                                  payload.get("params")))
        if not ok:
            self.alert_rejected.emit(reason or "invalid parameters")
            return
        if direction not in ("up", "down"):
            self.alert_rejected.emit("choose a direction")
            return
        try:
            alert, reason = self._repo.add_alert(  # type: ignore[union-attr] # repo seam guarded by the except boundary
                active, condition_type,
                cast("dict[str, object]", params), direction)
        except Exception:
            log.exception("arm_alert failed")
            self.alert_rejected.emit("could not save - please retry")
            return
        if alert is None:
            self.alert_rejected.emit(reason)
            return
        self._alerts.append(self._spec_from_row(alert))
        self._emit_alerts()

    @Slot(int)
    def disarm_alert(self, alert_id: int) -> None:
        self._set_alert_state(alert_id, armed=False, fired_at=None)

    @Slot(int)
    def rearm_alert(self, alert_id: int) -> None:
        self._set_alert_state(alert_id, armed=True, fired_at=None)

    @Slot(int)
    def remove_alert(self, alert_id: int) -> None:
        if self._repo is not None:
            try:
                self._repo.remove_alert(alert_id)
            except Exception:
                log.exception("remove_alert failed")
        self._alerts = [s for s in self._alerts if s.id != alert_id]
        self._emit_alerts()

    # -- UI intents (queued slots, all on the worker thread) ----------------- #
    @Slot(str)
    def add_symbol(self, text: str) -> None:
        if self._stop or _interrupted():                    # no probe after shutdown
            return
        outcome = validate_add(text, self._watchlist_symbols(), config.WATCHLIST_CAP)
        if outcome.status == "rejected":
            self.add_rejected.emit(text, outcome.reason)
            return
        if outcome.status == "ok":
            # bounded existence probe, only on the "ok" branch
            ok, reason = self._probe_symbol(outcome.symbol)
            if not ok:
                self.add_rejected.emit(text, reason)
                return
            try:
                self._repo.add(outcome.symbol, outcome.asset_class,  # type: ignore[union-attr] # repo seam guarded by the except boundary
                               outcome.quote_currency,
                               _provider(outcome.asset_class, self._venue))
                self._fetch_sector_once(outcome.symbol)  # one profile2 call
                self._reload_watchlist()
                active = self._repo.active_symbol()  # type: ignore[union-attr] # repo seam guarded by the except boundary
                if active and active != self._symbol:    # first-ever symbol became active
                    self._switch_active(active)
                    return
            except Exception:
                log.exception("add_symbol failed")
                self.add_rejected.emit(text, "Could not save - please retry.")
                return
        # "ok" (added) or "duplicate" (ignored) -> just refresh the panel
        self._emit_watchlist()

    def _probe_symbol(self, symbol: str) -> tuple:
        # cheap quote-only existence check before we commit a new symbol
        try:
            res = self._get_source(symbol, held=True).fetch_mark(symbol)
        except Exception:                          # defensive: contract says values
            log.exception("symbol probe failed (%s)", symbol)
            return False, (f"Could not verify {symbol} - "
                           "check your connection and retry.")
        if res.ok:
            return True, ""
        kind = res.error.kind if res.error is not None else None
        if kind == SourceErrorKind.EMPTY:          # resolved venue, no instrument
            return False, f"{symbol} not found - check the ticker."
        return False, (f"Could not verify {symbol} - "
                       "check your connection and retry.")

    @Slot(str)
    def remove_symbol(self, symbol: str) -> None:
        if any(p.symbol == symbol for p in self._portfolio.positions):   # held -> blocked
            log.info("blocked remove of held symbol %s (close the position first)", symbol)
            self.remove_rejected.emit(symbol, "Close the position first.")  # inline
            self._emit_watchlist()
            return
        try:
            new_active = self._repo.remove(symbol)  # type: ignore[union-attr] # repo seam guarded by the except boundary
            self._reload_watchlist()
        except Exception:
            log.exception("remove_symbol failed")
            self._emit_watchlist()
            return
        self._marks.pop(symbol, None)
        self._daily_series.pop(symbol, None)  # evict the 1d series
        for key in [k for k in self._history if k[0] == symbol]:   # evict cache
            self._history.pop(key, None)
        if new_active != self._symbol:
            if new_active:
                self._switch_active(new_active)
            else:                                         # watchlist now empty
                self._symbol = None
                self._candles = ()
                self._last_quote = None
                self._source = None
                self._reset_alert_baseline()              # active-symbol change
                self._emit_snapshot(None)
                self._emit_watchlist()
                self._emit_alerts()
        else:
            self._emit_watchlist()

    @Slot(str)
    def select_symbol(self, symbol: str) -> None:
        if not symbol or symbol == self._symbol:
            self._emit_watchlist()
            return
        try:
            self._repo.set_active(symbol)  # type: ignore[union-attr] # repo seam guarded by the except boundary
            self._reload_watchlist()
        except Exception:
            log.exception("select_symbol failed")
            self._emit_watchlist()
            return
        self._switch_active(symbol)

    @Slot(object)
    def set_indicator_settings(self, settings: object) -> None:
        if not isinstance(settings, IndicatorSettings):
            return
        if settings == self._settings:                    # coalesce a redundant change
            return
        self._settings = settings
        try:
            self._set_setting(INDICATORS_KEY, settings.to_dict())
        except Exception:
            log.exception("persisting indicator settings failed")
        self._emit_snapshot(None)                         # reflect the toggle at once

    @Slot(str)
    def set_timeframe(self, timeframe: str) -> None:
        if not timeframe or timeframe == self._timeframe or not self._symbol:
            return
        self._timeframe = timeframe
        self._backoff_until = 0.0                         # user intent bypasses backoff
        self._candles = self._history.get((self._symbol, timeframe), ())  # cached render
        if not self._candles and self._symbol:            # instant official/resample
            self._candles = self._chart_candles(self._symbol, timeframe, ())
        self._last_quote = self._marks.get(self._symbol)
        self._reset_alert_baseline()                      # series changed
        self._emit_snapshot(None)
        if self._timer is not None:
            self._timer.start()                           # avoid a redundant back-to-back tick
        QTimer.singleShot(0, self._poll)

    # -- active-symbol switching --------------------------------------------- #
    def _switch_active(self, symbol: str) -> None:
        self._symbol = symbol
        self._backoff_until = 0.0                         # user intent bypasses backoff
        # cached series renders instantly; the singleShot refresh overwrites shortly
        self._candles = self._history.get((symbol, self._timeframe), ())
        self._last_quote = self._marks.get(symbol)        # show last-known mark if any
        self._reset_alert_baseline()                      # active-symbol change
        self._bind_source()
        self._ensure_stock_history(symbol)  # official 1d series
        if not self._candles and self._symbol:            # instant official/resample
            self._candles = self._chart_candles(symbol, self._timeframe, ())
        self._emit_snapshot(None)                         # immediate cached/warming frame
        self._emit_watchlist()
        self._emit_alerts()                               # not_active flags refresh
        if self._timer is not None:
            self._timer.start()                           # avoid a redundant back-to-back tick
        QTimer.singleShot(0, self._poll)                  # refresh the new symbol now

    def _reset_alert_baseline(self) -> None:
        # forget the last-closed bar so a series swap can't replay an old crossover
        self._last_closed_ts = None

    def _bind_source(self) -> None:
        self._source = self._get_source(self._symbol) if self._symbol else None

    def _get_source(self, symbol: str, held: bool = False) -> MarketDataSource:
        # adapters are cached per (asset, tier); held marks get a longer timeout
        tier = "held" if held else "active"
        key = (f"crypto:{self._venue}:{tier}" if is_crypto_symbol(symbol)
               else f"stock:{tier}")
        src = self._adapters.get(key)
        if src is None:
            timeout = (config.HELD_REQUEST_TIMEOUT_S if held
                       else self._request_timeout_s)
            src = source_for_symbol(symbol, request_timeout_s=timeout,
                                    venue=self._venue)
            self._adapters[key] = src
        return src

    # -- watchlist state ----------------------------------------------------- #
    def _emit_watchlist(self) -> None:
        rows = []
        for p in self._persisted:
            q = self._marks.get(p.symbol)
            if q is not None:
                stale = q.stale or config.is_stale(
                    q.ts, poll_interval_s=self._poll_interval_s)
                rows.append(WatchlistRow(symbol=p.symbol, asset_class=p.asset_class,
                                         mark=q.mark, stale=stale, has_quote=True,
                                         active=(p.symbol == self._symbol)))
            else:
                needs_key = False
                if p.asset_class == "stock":
                    try:                            # presence only; never the value
                        needs_key = bool(getattr(self._get_source(p.symbol),
                                                 "needs_key", False))
                    except Exception:               # nosec B110 - render-state probe
                        pass
                rows.append(WatchlistRow(symbol=p.symbol, asset_class=p.asset_class,
                                         has_quote=False, needs_key=needs_key,
                                         active=(p.symbol == self._symbol)))
        self.watchlist_ready.emit(WatchlistState(rows=tuple(rows), active=self._symbol))

    def _reload_watchlist(self) -> None:
        if self._repo is not None:
            self._persisted = self._repo.list_watchlist()

    def _watchlist_symbols(self) -> list:
        return [p.symbol for p in self._persisted]

    # -- alert helpers ------------------------------------------------------- #
    def _load_alerts(self) -> None:
        try:
            rows = self._repo.list_alerts() if self._repo is not None else []
            self._alerts = [self._spec_from_row(r) for r in rows]
        except Exception:
            log.exception("alert load failed; continuing with no alerts")
            self._alerts = []

    @staticmethod
    def _spec_from_row(row) -> AlertSpec:
        return AlertSpec(id=row.id, symbol=row.symbol, condition_type=row.condition_type,
                         params=dict(row.params), direction=row.direction,
                         armed=row.armed, fired_at=row.fired_at)

    def _set_alert_state(self, alert_id: int, armed: bool,
                         fired_at: Optional[float]) -> None:
        if self._repo is not None:
            try:
                self._repo.set_alert_state(alert_id, armed=armed, fired_at=fired_at)
            except Exception:
                log.exception("set_alert_state failed")
                return
        self._alerts = [replace(s, armed=armed, fired_at=fired_at) if s.id == alert_id
                        else s for s in self._alerts]
        self._emit_alerts()

    # -- simulated-trade portfolio (worker thread, single writer) #
    def _load_portfolio(self) -> None:
        try:
            pp = self._repo.load_or_create_portfolio(config.STARTING_CASH)  # type: ignore[union-attr] # repo seam guarded by the except boundary
            positions = self._repo.get_positions()  # type: ignore[union-attr] # repo seam guarded by the except boundary
            self._starting_cash = pp.starting_cash
            self._portfolio = PortfolioState(
                cash=pp.cash, realised_pnl=pp.realised_pnl,
                positions=tuple(EngPosition(p.symbol, p.quantity, p.avg_cost)
                                for p in positions))
            self._trades = list(self._repo.list_trades())  # type: ignore[union-attr] # repo seam guarded by the except boundary
        except Exception:
            log.exception("portfolio load failed; starting flat")
            self._starting_cash = Decimal(str(config.STARTING_CASH))
            self._portfolio = PortfolioState(cash=self._starting_cash,
                                             realised_pnl=Decimal("0"), positions=())
            self._trades = []

    def _poll_held(self) -> bool:
        # round-robins a few held marks per tick rather than all of them at once
        held = [p.symbol for p in self._portfolio.positions if p.symbol != self._symbol]
        if not held:
            return False
        changed = False
        crypto = [s for s in held if is_crypto_symbol(s)]
        batch_fn = None
        if crypto:
            src0 = self._get_source(crypto[0], held=True)
            batch_fn = getattr(src0, "fetch_mark_batch", None)
        if callable(batch_fn):
            # every held crypto mark in one batched call
            try:
                results = batch_fn(crypto)
            except Exception:                  # defensive (contract: values)
                log.exception("held crypto batch failed")
                results = {}
            ok_any = False
            for sym in crypto:
                res = results.get(sym)
                if res is not None and res.ok and res.quote is not None:
                    self._marks[sym] = res.quote
                    changed = True
                    ok_any = True
                else:
                    prior = self._marks.get(sym)
                    if prior is not None and not prior.stale:
                        self._marks[sym] = replace(prior, stale=True)
                        changed = True
            first_err = next((results[s].error for s in crypto
                              if s in results and results[s].error is not None),
                             None)
            self._note_provider("kraken",
                                None if ok_any else
                                (first_err or SourceError(SourceErrorKind.UNKNOWN,
                                                          "batch failed")))
            held = [s for s in held if not is_crypto_symbol(s)]
            if not held:
                return changed
        budget = min(config.HELD_POLL_BUDGET, len(held))
        for _ in range(budget):
            if self._stop or _interrupted():                # bail on shutdown
                break
            self._held_cursor %= len(held)
            sym = held[self._held_cursor]
            self._held_cursor += 1
            _prov = "kraken" if is_crypto_symbol(sym) else "finnhub"
            try:
                res = self._get_source(sym, held=True).fetch_mark(sym)
                if res.ok and res.quote is not None:
                    self._marks[sym] = res.quote
                    changed = True
                    self._note_provider(_prov, None)
                else:
                    self._note_provider(_prov, res.error)
                    prior = self._marks.get(sym)
                    if prior is not None and not prior.stale:
                        self._marks[sym] = replace(prior, stale=True)
                        changed = True
            except Exception:                       # defensive belt (contract: never raises)
                log.exception("held mark fetch failed (%s)", sym)
        return changed

    def _mark_decimal(self, symbol):
        q = self._marks.get(symbol)
        if q is None:
            return None, False
        return Decimal(str(q.mark)), bool(
            q.stale or config.is_stale(q.ts, poll_interval_s=self._poll_interval_s))

    def _build_portfolio_view(self) -> PortfolioView:
        marks: dict = {}
        has_marks = False
        any_stale = False
        rows = []
        for p in self._portfolio.positions:
            m, stale = self._mark_decimal(p.symbol)
            asset_class = "crypto" if "/" in p.symbol else "stock"
            if m is not None:
                marks[p.symbol] = m
                has_marks = True
                any_stale = any_stale or stale
                rows.append(PositionRow(p.symbol, asset_class, p.quantity, p.avg_cost,
                                        mark=m, unrealised=p.quantity * (m - p.avg_cost),
                                        value=p.quantity * m, stale=stale))
            else:
                any_stale = True                  # a missing mark is stale
                rows.append(PositionRow(p.symbol, asset_class, p.quantity, p.avg_cost))
        unreal = unrealised(self._portfolio, marks)  # three valuation views agree
        value = portfolio_value(self._portfolio, marks)
        trades = tuple(TradeRow(t.ts, t.symbol, t.side, t.quantity, t.fill_price,
                                t.avg_cost_at_fill, t.qty_before, t.qty_after, t.realised_pnl)
                       for t in self._trades)
        return PortfolioView(
            starting_cash=self._starting_cash, cash=self._portfolio.cash,
            realised_pnl=self._portfolio.realised_pnl, unrealised_pnl=unreal,
            total_value=value, total_pnl=self._portfolio.realised_pnl + unreal,
            positions=tuple(rows), trades=trades, has_marks=has_marks,
            any_marks_stale=any_stale,
            gbp_rate=(self._ctx_fx.rate if self._ctx_fx.available else None),
            gbp_as_of=(self._ctx_fx.as_of if self._ctx_fx.available else ""),
            gbp_note=(self._ctx_fx.note if self._ctx_fx.available else ""))

    # -- value-history sampling + risk (worker thread) ------- #
    def _value_now(self):
        cash = self._portfolio.cash
        positions_value = Decimal("0")
        stale = False
        for p in self._portfolio.positions:
            m, st = self._mark_decimal(p.symbol)
            if m is not None:
                positions_value += p.quantity * m
                stale = stale or st
            else:
                stale = True
        value = cash + positions_value
        return value, positions_value, cash, (stale if self._portfolio.positions else False)

    def _load_value_history(self):
        try:
            peak = self._repo.get_peak() if self._repo is not None else None
            self._peak_value = peak.peak_value if peak is not None else None
            self._peak_ts = peak.peak_ts if peak is not None else None
            samples = self._repo.list_value_history() if self._repo is not None else []
            self._value_history = deque(
                (ValueSample(ts=s.ts, value=float(s.portfolio_value), stale=bool(s.stale))
                 for s in samples), maxlen=config.VALUE_HISTORY_CAP)
        except Exception:
            log.exception("value-history load failed; starting empty")
            self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)
            self._peak_value = None
            self._peak_ts = None

    def _start_heartbeat(self):
        # one timer drives value sampling and the slow context/daily refreshes
        self._next_sample_due = (self._wallclock()
                                 + config.risk_timeframe_seconds(self._risk_timeframe))
        if self._heartbeat is None:
            self._heartbeat = QTimer(self)
            self._heartbeat.timeout.connect(self._on_heartbeat)
        self._heartbeat.setInterval(int(config.HEARTBEAT_INTERVAL_S * 1000))
        self._heartbeat.start()

    @Slot()
    def _on_heartbeat(self):
        if self._stop or _interrupted():
            return
        now = self._wallclock()
        due = self._next_sample_due
        if due is not None and now >= due:
            cadence = float(config.risk_timeframe_seconds(self._risk_timeframe))
            missed = int((now - due) // cadence)         # whole periods slept through
            self._next_sample_due = due + cadence * (missed + 1)   # the grid is kept
            self._sample_value_history()
        if not self._refresh_context_if_due(now):
            # at most one daily-coverage fetch per tick
            self._refresh_daily_if_due(now)
        if self._risk_dirty and not self._stop:
            # rebuild only when the daily data changed
            self._rebuild_risk_analytics()

    @Slot()
    def _sample_value_history(self):
        if self._stop or self._repo is None:
            return
        try:
            now = self._wallclock()
            value, positions_value, cash, stale = self._value_now()
            peak_changed = self._peak_value is None or value > self._peak_value
            if peak_changed:
                self._peak_value, self._peak_ts = value, now
            try:
                self._repo.append_value_history(
                    ts=now, portfolio_value=value, cash=cash,
                    positions_value=positions_value, stale=stale,
                    cap=config.VALUE_HISTORY_CAP,
                    peak_value=(self._peak_value if peak_changed else None),
                    peak_ts=(self._peak_ts if peak_changed else None))  # one commit
            except Exception:
                log.exception("value-history persist failed; keeping in-memory series")
            self._value_history.append(ValueSample(ts=now, value=float(value), stale=stale))
            self._refresh_analytics_view()  # fresh USD figures + dd
            self._emit_snapshot(None)
        except Exception:                                     # structural never-raise
            log.exception("value-history sample failed; skipping this tick")

    @Slot(str)
    def set_risk_timeframe(self, timeframe):
        # changing cadence re-bases the value-history; the old series can't be re-spaced
        if timeframe not in config.VALID_RISK_TIMEFRAMES:
            return
        if timeframe == self._risk_timeframe:
            self.settings_applied.emit("risk timeframe already " + timeframe)
            return
        self._risk_timeframe = timeframe
        now = self._wallclock()
        value, _, _, _ = self._value_now()
        try:
            if self._repo is not None:
                self._repo.rebase_value_history(ts=now, value=value,
                                                timeframe=timeframe)    # one commit
        except Exception:
            log.exception("risk timeframe rebase failed")
        self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)
        self._peak_value, self._peak_ts = value, now
        self._next_sample_due = now + config.risk_timeframe_seconds(timeframe)  # re-anchor
        self.settings_applied.emit("applied (next cycle)")
        self._emit_snapshot(None)

    def _build_risk_view(self):
        cash = self._portfolio.cash
        positions_value = Decimal("0")
        any_stale = False
        per_pos = []
        for p in self._portfolio.positions:
            m, st = self._mark_decimal(p.symbol)
            if m is not None:
                val = p.quantity * m
                positions_value += val
                per_pos.append((p.symbol, val))
                any_stale = any_stale or st
            else:
                any_stale = True
        port_value = cash + positions_value
        empty = (len(self._portfolio.positions) == 0 and len(self._trades) == 0)

        exp = _exposure(float(positions_value), float(port_value))
        exp_rows: tuple[ExposureRow, ...] = ()
        if exp.defined and float(port_value) > 0.0:
            denom = float(port_value)
            exp_rows = tuple(ExposureRow(sym, float(val) / denom) for sym, val in per_pos)
        exp_out = bool(exp.out_of_range and not any_stale)        # surfaced only when non-stale

        samples = list(self._value_history)
        returns, skipped = _simple_returns(samples)
        vol = _volatility(returns, self._risk_timeframe, window=config.VOLATILITY_WINDOW)
        # seed the running max with the persisted peak only when it predates the window
        peak_v: Optional[float] = None
        peak_ts: Optional[float] = None
        if (self._peak_value is not None and self._peak_ts is not None
                and samples and self._peak_ts <= samples[0].ts):
            peak_v = float(self._peak_value)               # explicit narrowing
            peak_ts = self._peak_ts
        dd = _max_drawdown(samples, peak_value=peak_v, peak_ts=peak_ts)

        spark = tuple(s.value for s in samples)
        trough_idx: Optional[int] = None
        if dd.trough_ts is not None:
            for i, s in enumerate(samples):
                if s.ts == dd.trough_ts:
                    trough_idx = i
                    break
        return RiskView(
            empty=empty, warming=(not vol.defined), any_stale=any_stale,
            returns_skipped_stale=skipped, timeframe=self._risk_timeframe,
            exp_defined=exp.defined,
            exp_abs=(positions_value if exp.defined else None),
            exp_pct=exp.pct, exp_out_of_range=exp_out, exp_rows=exp_rows,
            vol_defined=vol.defined, vol_period_pct=vol.per_period_pct,
            vol_annual_pct=vol.annualised_pct, vol_n=vol.n_returns,
            dd_defined=dd.defined, dd_pct=dd.max_dd_pct,
            dd_peak_ts=dd.peak_ts, dd_trough_ts=dd.trough_ts,
            spark=spark, spark_trough_idx=trough_idx,
            history=tuple((s.ts, s.value, s.stale) for s in samples))   # export rows

    def _emit_order_result(self, ok, fill_mark=None, summary="", reason="") -> None:
        self.order_result.emit({
            "ok": bool(ok),
            "fill_mark": (str(fill_mark) if fill_mark is not None else None),
            "summary": summary, "reason": reason})

    @Slot(object)
    def place_order(self, payload: object) -> None:
        # fills against the mark the UI froze at click; rejects a second concurrent submit
        from mahad.engine.portfolio import place_order as _place
        if not isinstance(payload, dict):
            return
        if self._stop:                                         # drop intents after shutdown
            return
        if self._order_in_flight:                              # authoritative no-double-submit
            self._emit_order_result(False, reason="order already in progress")
            return
        self._order_in_flight = True
        try:
            side = str(payload.get("side") or "")
            raw_qty = payload.get("qty")
            symbol = str(payload.get("symbol") or self._symbol or "")
            frozen_mark = payload.get("mark")
            frozen_ts = payload.get("ts")
            if not symbol:
                self._emit_order_result(False, reason="add a symbol first")
                return
            if frozen_mark is None:
                self._emit_order_result(False, reason="warming up - no quote yet")
                return
            try:                                              # hostile payload mark
                fill_mark = Decimal(str(frozen_mark))
            except (InvalidOperation, ValueError, TypeError):
                self._emit_order_result(False, reason="no usable mark")
                return
            if not fill_mark.is_finite():
                self._emit_order_result(False, reason="no usable mark")
                return
            if frozen_ts is None or config.is_stale(
                    frozen_ts, poll_interval_s=self._poll_interval_s):  # gate the fill mark
                self._emit_order_result(False, reason="stale price - waiting for a fresh quote")
                return
            result = _place(self._portfolio, side, symbol, raw_qty, fill_mark)
            if not result.ok:
                self._emit_order_result(False, reason=result.reason)
                return
            try:                                              # persist-before-adopt
                self._persist_fill(result.state, result.fill)
            except Exception:
                log.exception("persist fill failed; not adopting")
                self._emit_order_result(False, reason="could not save - please retry")
                return
            self._portfolio = result.state                    # adopt only after a clean commit
            self._refresh_analytics_view()  # weights changed
            self._emit_order_result(True, fill_mark=result.fill.fill_price,  # type: ignore[union-attr] # ok=True implies a fill (engine contract)
                                    summary=f"filled @ {result.fill.fill_price}")  # type: ignore[union-attr] # ok=True implies a fill (engine contract)
            self._emit_snapshot(None)
        except Exception:                                     # structural never-raise
            log.exception("place_order failed on a malformed intent")
            self._emit_order_result(False, reason="invalid order request")
        finally:
            self._order_in_flight = False

    def _persist_fill(self, state, fill) -> None:
        pos = state.position(fill.symbol)
        trade = PersistedTrade(
            ts=time.time(), symbol=fill.symbol, side=fill.side, quantity=fill.quantity,
            fill_price=fill.fill_price, avg_cost_at_fill=fill.avg_cost_at_fill,
            qty_before=fill.qty_before, qty_after=fill.qty_after,
            realised_pnl=fill.realised_pnl)
        self._repo.record_fill(  # type: ignore[union-attr] # repo seam guarded by the except boundary
            cash=state.cash, realised_pnl=state.realised_pnl, symbol=fill.symbol,
            new_quantity=(pos.quantity if pos is not None else None),
            new_avg_cost=(pos.avg_cost if pos is not None else None), trade=trade)
        self._trades.append(trade)

    @Slot(object)
    def reset_portfolio(self, payload: object) -> None:
        if self._repo is None or self._stop:
            return
        if self._reset_in_flight:
            return
        self._reset_in_flight = True
        try:
            also_clear = bool(isinstance(payload, dict) and payload.get("also_clear_log"))
            export_ok = bool(isinstance(payload, dict) and payload.get("export_succeeded"))
            try:
                pp = self._repo.reset_portfolio(config.STARTING_CASH)
                if also_clear and export_ok:
                    self._repo.clear_trades()
                    self._trades = []
            except Exception:
                log.exception("reset_portfolio failed")
                return
            self._portfolio = PortfolioState(cash=pp.cash, realised_pnl=pp.realised_pnl,
                                             positions=())
            self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)   # re-base
            try:
                peak = self._repo.get_peak()
                self._peak_value, self._peak_ts = peak.peak_value, peak.peak_ts
            except Exception:
                log.exception("post-reset peak load failed; seeding from cash")
                self._peak_value, self._peak_ts = self._portfolio.cash, time.time()
            self._emit_snapshot(None)
        finally:
            self._reset_in_flight = False

    @Slot(int)
    def clear_trade_log(self, expected_count: int = -1) -> None:
        # only clears if the log still matches what was exported, else a fresh trade is lost
        if self._repo is None or self._stop:
            return
        if expected_count >= 0 and len(self._trades) != expected_count:
            log.info("clear_trade_log skipped: log changed since export (%d != %d)",
                     len(self._trades), expected_count)
            self._emit_snapshot(None)
            return
        try:
            self._repo.clear_trades()
            self._trades = []
        except Exception:
            log.exception("clear_trade_log failed")
            return
        self._emit_snapshot(None)

    # -- the daily-series coverage for the risk suite --- #
    def _daily_coverage_symbols(self) -> list:
        # held positions, the active stock, plus the benchmark the risk maths needs
        out: list[str] = []
        for p in self._portfolio.positions:
            if p.symbol not in out:
                out.append(p.symbol)
        active = self._symbol
        if active and not is_crypto_symbol(active) and active not in out:
            out.append(active)
        if config.BENCHMARK_SYMBOL not in out:
            out.append(config.BENCHMARK_SYMBOL)
        return out

    def _refresh_daily_if_due(self, now) -> None:
        # at most one daily fetch per tick, to stay inside the free-tier rate limits
        if self._repo is None:
            return
        try:
            symbols = self._daily_coverage_symbols()
        except Exception:                              # defensive
            log.exception("daily coverage set failed")
            return
        stagger = config.DAILY_STAGGER_S
        for sym in symbols:
            if sym not in self._daily_due:
                try:
                    latest = self._repo.latest_daily_bar_ts(sym)
                except Exception:
                    latest = None
                # fresh waits for the nightly due; covered-but-stale tops up promptly
                fresh = (latest is not None
                         and (now - float(latest)) < config.DAILY_REFRESH_S * 2)
                self._daily_due[sym] = now + (config.DAILY_REFRESH_S if fresh
                                              else stagger)
                stagger += 2.0
        for sym in symbols:
            if now >= self._daily_due.get(sym, float("inf")):
                ok = self._refresh_daily_symbol(sym)
                self._daily_due[sym] = now + (config.DAILY_REFRESH_S if ok
                                              else config.DAILY_RETRY_S)
                if ok:
                    self._risk_dirty = True  # rebuild on new data
                return

    def _refresh_daily_symbol(self, symbol) -> bool:
        try:
            if is_crypto_symbol(symbol):
                return self._refresh_daily_crypto(symbol)
            return self._refresh_daily_stock(symbol)
        except Exception:                              # structural never-raise
            log.exception("daily refresh failed (%s)", symbol)
            return False

    def _refresh_daily_stock(self, symbol) -> bool:
        src = self._get_source(symbol)
        fetcher = getattr(src, "fetch_daily_history", None)
        if not callable(fetcher):
            return False
        if self._repo is not None:
            try:
                self._repo.ensure_symbol(symbol, "stock", "USD", "finnhub")
            except Exception:
                log.exception("ensure_symbol failed (%s)", symbol)
        latest = None
        try:
            latest = (self._repo.latest_daily_bar_ts(symbol)
                      if self._repo is not None else None)
        except Exception:
            log.exception("latest_daily_bar_ts failed (%s)", symbol)
        start_date = None
        if latest is not None:
            import datetime as _dt
            start_date = _dt.datetime.fromtimestamp(
                latest, _dt.timezone.utc).date().isoformat()
        res = fetcher(symbol, start_date)
        if not getattr(res, "ok", False):
            self._note_provider("tiingo", getattr(res, "error", None))
            return False
        self._note_provider("tiingo", None)
        bars = res.bars
        if latest is not None and needs_full_repull(bars):
            # adjusted history changed - re-download in full
            log.info("corporate action on %s - full daily re-pull", symbol)
            full = fetcher(symbol, None)
            if not getattr(full, "ok", False):
                self._note_provider("tiingo", getattr(full, "error", None))
                return False
            try:
                if self._repo is not None:
                    self._repo.clear_daily_bars(symbol)
            except Exception:
                log.exception("clear_daily_bars failed (%s)", symbol)
            bars = full.bars
        try:
            if self._repo is not None:
                self._repo.upsert_daily_bars(symbol, bars)
        except Exception:
            log.exception("daily-bar persist failed (%s)", symbol)
            return False
        self._daily_series.pop(symbol, None)       # rebuilt from the cache
        self._ensure_stock_history(symbol)
        return True

    def _refresh_daily_crypto(self, symbol) -> bool:
        src = self._get_source(symbol)
        fetch_ohlc = getattr(src, "fetch_ohlc", None)
        if not callable(fetch_ohlc):
            return False
        candles, err = fetch_ohlc(symbol, "1d")
        if err is not None or not candles:
            self._note_provider("kraken", err)
            return False
        self._note_provider("kraken", None)
        closed = [c for c in candles if c.is_closed]   # the forming row never persists
        if not closed:
            return False
        rows = [_CryptoDailyRow(ts=c.ts, open=c.open, high=c.high, low=c.low,
                                close=c.close, adj_close=c.close,
                                volume=c.volume, div_cash=0.0,
                                split_factor=1.0) for c in closed]
        try:
            if self._repo is not None:
                self._repo.ensure_symbol(symbol, "crypto", "USD", self._venue)
                self._repo.upsert_daily_bars(symbol, rows)
        except Exception:
            log.exception("crypto daily persist failed (%s)", symbol)
            return False
        return True

    # -- migration, official 1d history, provider health -- #
    def _run_data_migration(self) -> None:
        if self._repo is None:
            return
        try:
            self._repo.migrate_legacy_schema()
        except Exception:
            log.exception("data migration failed; continuing")

    def _chart_candles(self, symbol, timeframe, fetched):
        crypto = is_crypto_symbol(symbol)
        if not crypto and timeframe in ("1d", *RESAMPLE_TIMEFRAMES):
            self._ensure_stock_history(symbol)
            daily = self._daily_series.get(symbol) or ()
            if timeframe == "1d":
                return daily if daily else fetched
            return resample_daily_candles(daily, timeframe)
        if crypto and timeframe in RESAMPLE_TIMEFRAMES and timeframe != "1w":
            return resample_daily_candles(fetched, timeframe)
        return fetched

    def _ensure_stock_history(self, symbol: Optional[str]) -> None:
        # cache first, fall back to a Tiingo pull only when nothing is stored
        if not symbol or is_crypto_symbol(symbol) or symbol in self._daily_series:
            return
        rows: list = []
        try:
            rows = (self._repo.list_daily_bars(symbol, limit=config.HISTORY_CAP)
                    if self._repo is not None else [])
        except Exception:
            log.exception("daily-bar cache read failed (%s)", symbol)
        if not rows:
            fetcher = getattr(self._get_source(symbol), "fetch_daily_history", None)
            if callable(fetcher):
                try:
                    res = fetcher(symbol)
                except Exception:                  # defensive (contract: values)
                    log.exception("daily history fetch failed (%s)", symbol)
                    res = None
                if res is not None and getattr(res, "ok", False):
                    self._note_provider("tiingo", None)
                    try:
                        if self._repo is not None:
                            self._repo.upsert_daily_bars(symbol, res.bars)
                    except Exception:
                        log.exception("daily-bar persist failed (%s)", symbol)
                    rows = list(res.bars)
                elif res is not None:
                    self._note_provider("tiingo", res.error)
        if rows:
            self._daily_series[symbol] = tuple(
                Candle(symbol=symbol, timeframe="1d", ts=float(r.ts),
                       open=float(r.open), high=float(r.high), low=float(r.low),
                       close=float(r.close), volume=float(r.volume),
                       is_closed=True)
                for r in rows)

    def _note_provider(self, provider: str, error: Optional[object]) -> None:
        # feeds the health-chip tooltip; keeps the original since-ts across repeats
        if error is None:
            self._provider_errors[provider] = None
            return
        prior = self._provider_errors.get(provider)
        since = prior[2] if isinstance(prior, tuple) else self._wallclock()
        kind = getattr(getattr(error, "kind", None), "value", "unknown")
        self._provider_errors[provider] = (str(kind), str(error), since)

    def _provider_lines(self) -> tuple:
        # only providers actually hit this session show up
        out = []
        for name in ("finnhub", "tiingo", "kraken"):
            if name not in self._provider_errors:
                continue
            err = self._provider_errors[name]
            if err is None:
                out.append((name, "ok"))
            else:
                kind = err[0] if isinstance(err, tuple) else "unknown"
                if kind == "needs_key":
                    out.append((name, "needs a free key"))
                elif kind == "invalid_key":
                    out.append((name, "key rejected"))
                else:
                    out.append((name, f"retrying ({kind})"))
        return tuple(out)

    # -- the risk-analytics assembly ---------------------- #
    def _load_sectors(self) -> None:
        # local fallback map, overlaid with whatever profile2 lookups we've cached
        self._sectors = dict(config.DEFAULT_SECTOR_MAP)
        cached = self._get_setting(SECTORS_KEY)
        if isinstance(cached, dict):
            for k, v in cached.items():
                if isinstance(k, str) and isinstance(v, str) and v:
                    self._sectors[k] = v

    def _sector_for(self, symbol: str) -> str:
        if is_crypto_symbol(symbol):
            return "Crypto"
        return self._sectors.get(symbol, "Unclassified")

    def _fetch_sector_once(self, symbol: str) -> None:
        # a single profile2 call when a stock is added, then cached for good
        if is_crypto_symbol(symbol) or symbol in self._sectors:
            return
        src = self._get_source(symbol)
        fetcher = getattr(src, "fetch_profile_sector", None)
        if not callable(fetcher):
            return
        try:
            sector, err = fetcher(symbol)
        except Exception:                              # defensive
            log.exception("sector fetch failed (%s)", symbol)
            return
        if err is None and sector:
            self._sectors[symbol] = sector
            try:
                cached = self._get_setting(SECTORS_KEY)
                payload = dict(cached) if isinstance(cached, dict) else {}
                payload[symbol] = sector
                self._set_setting(SECTORS_KEY, payload)
            except Exception:
                log.exception("sector cache persist failed")

    def _rebuild_risk_analytics(self) -> None:
        try:
            self._build_asset_data()
            self._refresh_analytics_view()
            self._accrue_backtest()
            self._refresh_analytics_view()            # counts may have moved
            self._integrity = self._build_integrity_view()
            self._risk_dirty = False
            self._emit_snapshot(None)
        except Exception:                              # structural never-raise
            log.exception("risk analytics rebuild failed; keeping the prior view")
            self._risk_dirty = False

    def _build_asset_data(self) -> None:
        out_r: dict[str, list] = {}
        out_c: dict[str, list] = {}
        if self._repo is None:
            self._asset_returns, self._asset_closes = out_r, out_c
            return
        symbols = set(self._daily_coverage_symbols())
        for sym in symbols:
            try:
                rows = self._repo.list_daily_bars(sym, limit=config.HISTORY_CAP)
            except Exception:
                log.exception("daily-bar read failed (%s)", sym)
                continue
            if not rows:
                continue
            closes = eng_returns.align_daily_closes(
                (r.ts, r.adj_close) for r in rows)
            if not closes:
                continue
            out_c[sym] = closes
            rets = eng_returns.simple_returns_by_date(closes)
            if rets:
                out_r[sym] = rets
        self._asset_returns, self._asset_closes = out_r, out_c

    def _current_weights_and_value(self) -> tuple[dict, float]:
        positions = []
        for p in self._portfolio.positions:
            q = self._marks.get(p.symbol)
            if q is not None:
                positions.append((p.symbol, float(p.quantity), float(q.mark)))
        value_dec, _, cash, _ = self._value_now()
        return (eng_returns.current_weights(positions, float(cash)),
                float(value_dec))

    def _refresh_analytics_view(self) -> None:
        try:
            self._analytics = self._build_analytics_view()
        except Exception:
            log.exception("analytics view build failed; keeping the prior view")

    def _build_analytics_view(self) -> RiskAnalyticsView:
        weights, value = self._current_weights_and_value()
        if not weights:
            return RiskAnalyticsView(available=False, note="no positions",
                                     portfolio_value=value)
        pr = eng_returns.portfolio_returns(weights, self._asset_returns,
                                           config.RISK_WINDOW)
        stock_missing = [s for s in pr.excluded if not is_crypto_symbol(s)]
        if pr.n == 0:  # gate on n
            note = ("needs history - free Tiingo key (tiingo.com)"
                    if (stock_missing and any(
                        getattr(self._get_source(s), "history_needs_key", False)
                        for s in stock_missing))
                    else "warming - no overlapping daily history yet")
            return RiskAnalyticsView(available=False, note=note,
                                     excluded=pr.excluded,
                                     coverage_weight=pr.coverage_weight,
                                     portfolio_value=value)
        rets = list(pr.returns)
        var95 = eng_rm.historical_var(rets, 0.95)
        var95_usd = (var95.value * value if var95 else None)
        var99 = eng_rm.historical_var(rets, config.BACKTEST_CONFIDENCE)
        es975 = eng_rm.expected_shortfall(rets, config.ES_CONFIDENCE)
        # risk-free input: the Treasury 3M par yield
        rf_annual = self._ctx_yields.y3m if self._ctx_yields.available else None
        rf_daily = eng_returns.rf_daily_from_annual_pct(rf_annual)
        sharpe_res = (eng_rm.sharpe(rets, rf_daily)
                      if rf_daily is not None else None)
        sortino_res = eng_rm.sortino(rets)
        bench = self._asset_returns.get(config.BENCHMARK_SYMBOL)
        beta_val = None
        if bench:
            bench_map = dict(bench)
            paired_p, paired_b = [], []
            for d, r in zip(pr.dates, pr.returns, strict=False):
                rb = bench_map.get(d)
                if rb is not None:
                    paired_p.append(r)
                    paired_b.append(rb)
            beta_val = eng_rm.beta(paired_p, paired_b)
        held = {p.symbol for p in self._portfolio.positions}
        corr_in = {s: [r for _, r in self._asset_returns[s]]
                   for s in sorted(held) if s in self._asset_returns}
        corr_symbols: tuple = ()
        corr_matrix: tuple = ()
        if len(corr_in) >= 2:
            corr_symbols, corr_matrix = eng_rm.correlation_matrix(
                corr_in, config.CORRELATION_WINDOW)
        corr_sum = (eng_rm.correlation_summary(corr_symbols, corr_matrix)
                    if corr_matrix else None)
        position_values = {}
        for p in self._portfolio.positions:
            q = self._marks.get(p.symbol)
            if q is not None:
                position_values[p.symbol] = float(p.quantity) * float(q.mark)
        conc = None
        if position_values:
            conc = eng_rm.concentration(
                position_values,
                {s: self._sector_for(s) for s in position_values})
        dd = eng_rm.drawdown_duration([s.value for s in self._value_history])
        # component VaR / risk contributions on the same common grid
        comp = None
        if pr.n >= 2 and pr.included:
            # reuse the alignment portfolio_returns already built
            comp = eng_rm.component_var(
                {s: weights[s] for s in pr.included if s in weights},
                pr.aligned, config.COMPONENT_VAR_CONFIDENCE)
        contributions: tuple = ()
        comp_sigma = comp_var_pct = comp_var_usd = None
        if comp is not None:
            comp_sigma = comp.portfolio_sigma
            comp_var_pct = comp.portfolio_var
            comp_var_usd = comp.portfolio_var * value
            contributions = tuple(
                ContributionRow(symbol=rc.symbol, weight=rc.weight, pct=rc.pct,
                                comp_var_pct=rc.comp_var,
                                comp_var_usd=rc.comp_var * value)
                for rc in comp.contributions)
        x, t = (0, 0)
        if self._repo is not None:
            try:
                x, t = self._repo.backtest_counts(config.RISK_WINDOW)
            except Exception:
                log.exception("backtest counts read failed")
        mode = "ex-ante" if t >= config.RISK_WINDOW else "accruing"
        bx, bt = x, t
        if t < config.RISK_WINDOW:
            # roll the trailing window across the full cached series
            pr_full = eng_returns.portfolio_returns(weights,
                                                    self._asset_returns,
                                                    window=0)
            bc = eng_rm.backcast_exceptions(list(pr_full.returns),
                                            config.BACKTEST_CONFIDENCE,
                                            config.RISK_WINDOW)
            if bc is not None and bc.observations > 0:
                mode = "backcast"
                bx, bt = bc.exceptions, bc.observations
        kup = (eng_rm.kupiec_pof(bx, bt, 1.0 - config.BACKTEST_CONFIDENCE)
               if bt > 0 else None)
        # P&L-to-risk linkage: total P&L against the 1-day 95% VaR
        marks_dec = {}
        for p in self._portfolio.positions:
            md, _st = self._mark_decimal(p.symbol)
            if md is not None:
                marks_dec[p.symbol] = md
        unreal_pnl = float(unrealised(self._portfolio, marks_dec))
        realised_pnl = float(self._portfolio.realised_pnl)
        total_pnl = realised_pnl + unreal_pnl
        pnl_to_var = eng_rm.return_on_risk(total_pnl, var95_usd)
        unreal_to_var = eng_rm.return_on_risk(unreal_pnl, var95_usd)
        # rolling VaR history + trend
        var_hist = eng_rm.rolling_var(rets, 0.95, config.VAR_TREND_WINDOW,
                                      config.VAR_TREND_POINTS)
        var_trend = ""
        if len(var_hist) >= 2 and var_hist[0] > 0.0:
            delta = var_hist[-1] - var_hist[0]
            thr = 0.05 * var_hist[0]
            var_trend = ("rising" if delta > thr
                         else "falling" if delta < -thr else "flat")
        return RiskAnalyticsView(
            available=True, note="", n=pr.n, window=config.RISK_WINDOW,
            as_of=(pr.dates[-1].isoformat() if pr.dates else ""),
            excluded=pr.excluded, coverage_weight=pr.coverage_weight,
            portfolio_value=value,
            var95_pct=(var95.value if var95 else None),
            var99_pct=(var99.value if var99 else None),
            var95_usd=var95_usd,
            var99_usd=(var99.value * value if var99 else None),
            es975_pct=(es975.value if es975 else None),
            es975_usd=(es975.value * value if es975 else None),
            pvar95_pct=eng_rm.parametric_var(rets, 0.95),
            pvar99_pct=eng_rm.parametric_var(rets, 0.99),
            backtest_mode=mode, backtest_exceptions=bx,
            backtest_observations=bt,
            backtest_zone=(eng_rm.basel_zone(bx) if bt > 0 else ""),
            accruing_n=t,
            kupiec_lr=(kup.lr if kup else None),
            kupiec_p=(kup.p_value if kup else None),
            kupiec_reject=(kup.reject if kup else None),
            beta_spy=beta_val,
            sharpe_annual=(sharpe_res.annualised if sharpe_res else None),
            sortino_annual=(sortino_res.annualised if sortino_res else None),
            rf_annual_pct=rf_annual,
            rf_as_of=(self._ctx_yields.as_of if rf_annual is not None else ""),
            rf_source=("US Treasury 3M par yield" if rf_annual is not None
                       else ""),
            ewma_vol_pct=(lambda v: v * 100.0 if v is not None else None)(
                eng_rm.ewma_volatility(rets)),
            corr_symbols=corr_symbols, corr_matrix=corr_matrix,
            corr_window=config.CORRELATION_WINDOW,
            corr_avg=(corr_sum.avg if corr_sum else None),
            corr_max_pair=(corr_sum.max_pair if corr_sum else ()),
            corr_min_pair=(corr_sum.min_pair if corr_sum else ()),
            hhi=(conc.hhi if conc else None),
            effective_n=(conc.effective_n if conc else None),
            top_symbol=(conc.top_symbol if conc else ""),
            top_weight=(conc.top_weight if conc else None),
            sector_hhi=(conc.sector_hhi if conc else None),
            sector_weights=(conc.sector_weights if conc else ()),
            dd_depth_pct=(dd.depth_pct if dd else None),
            dd_duration_periods=(dd.duration_periods if dd else None),
            dd_ongoing_periods=(dd.ongoing_periods if dd else None),
            stress=self._stress_rows(weights, value),
            comp_confidence=config.COMPONENT_VAR_CONFIDENCE,
            comp_sigma_pct=comp_sigma, comp_var_pct=comp_var_pct,
            comp_var_usd=comp_var_usd, contributions=contributions,
            pnl_total_usd=total_pnl, pnl_unrealised_usd=unreal_pnl,
            pnl_realised_usd=realised_pnl, pnl_to_var95=pnl_to_var,
            unreal_to_var95=unreal_to_var,
            var_history=var_hist, var_trend=var_trend)

    def _stress_window_return(self, scenario: str, symbol: str, start: str,
                              end: str) -> Optional[tuple[float, str]]:
        # prefer the cached close-to-close return, fall back to a cited constant, else nothing
        import datetime as _dt
        closes = self._asset_closes.get(symbol)
        if closes:
            d0 = _dt.date.fromisoformat(start)
            d1 = _dt.date.fromisoformat(end)
            inside = [(d, c) for d, c in closes if d0 <= d <= d1]
            if (len(inside) >= 2
                    and (inside[0][0] - d0).days <= 5
                    and (d1 - inside[-1][0]).days <= 5):
                return (inside[-1][1] / inside[0][1] - 1.0, "cache")
        const = config.STRESS_CONSTANTS.get((scenario, symbol))
        return None if const is None else (const, "constant")

    def _stress_rows(self, weights: dict, value: float) -> tuple:
        rows = []
        for name, start, end in config.STRESS_SCENARIOS:
            window_returns: dict[str, tuple[float, str]] = {}
            for sym in weights:
                entry = self._stress_window_return(name, sym, start, end)
                if entry is not None:
                    window_returns[sym] = entry
            res = eng_rm.stress_replay(name, start, end, value, weights,
                                       window_returns)
            rows.append(StressRow(
                scenario=name, start=start, end=end, pl_usd=res.pl_usd,
                covered_weight=res.covered_weight,
                legs_no_data=tuple(leg.symbol for leg in res.legs
                                   if leg.window_return is None),
                constant_legs=tuple(leg.symbol for leg in res.legs
                                    if leg.source == "constant")))
        return tuple(rows)

    def _accrue_backtest(self) -> None:
        # settle yesterday's open forecasts against realised returns, then log today's
        if self._repo is None:
            return
        import datetime as _dt
        # resolution first, independent of the current book's grid
        day_maps: dict = {}
        for sym, rows in self._asset_returns.items():
            for d, r in rows:
                day_maps.setdefault(d, {})[sym] = r
        try:
            open_rows = self._repo.open_backtest_rows()
        except Exception:
            log.exception("open backtest rows read failed")
            open_rows = []
        union_dates = sorted(day_maps)
        for row in open_rows:
            f_date = _dt.datetime.fromtimestamp(
                row.forecast_ts, _dt.timezone.utc).date()
            # the forecast's own next trading day with usable returns
            resolved = False
            for nxt in union_dates:
                if nxt <= f_date:
                    continue
                realised = eng_returns.single_day_return(
                    row.weights, day_maps.get(nxt, {}))
                if not realised.included:
                    continue                        # none of the book traded
                try:
                    self._repo.resolve_backtest_row(
                        row.forecast_ts, realised.value,
                        exception=(realised.value < -row.var99_pct),
                        resolved_ts=self._wallclock())
                except Exception:
                    log.exception("backtest resolve failed")
                resolved = True
                break
            if not resolved:
                continue                            # stays open until data lands
        # then today's forecast on the current book's as-if series
        weights, _value = self._current_weights_and_value()
        if not weights:
            return
        pr = eng_returns.portfolio_returns(weights, self._asset_returns,
                                           config.RISK_WINDOW)
        if pr.n == 0:
            return
        var99 = eng_rm.historical_var(list(pr.returns),
                                      config.BACKTEST_CONFIDENCE)
        if var99 is None:
            return
        last = list(pr.dates)[-1]
        last_ts = _dt.datetime(last.year, last.month, last.day,
                               tzinfo=_dt.timezone.utc).timestamp()
        try:
            self._repo.upsert_backtest_forecast(last_ts, var99.value, weights)
        except Exception:
            log.exception("backtest forecast persist failed")

    # -- market context (worker thread, slow cadence) --- #
    def _load_context_cache(self):
        # restore cached tiles and stagger the first fetches so they don't all fire at once
        try:
            self._ctx_has_key = bool(read_env_key())
        except Exception:                              # loader never raises
            log.exception("env key check failed; treating as keyless")
            self._ctx_has_key = False
        cached = self._get_setting(CONTEXT_KEY)
        if isinstance(cached, dict):
            try:
                y = cached.get("yields")
                if isinstance(y, dict) and y.get("y10y") is not None:
                    self._ctx_yields = self._yields_tile(y, y.get("fetched_ts"))
                f = cached.get("sentiment")
                if isinstance(f, dict) and f.get("value") is not None:
                    self._ctx_sentiment = self._sentiment_tile(f, f.get("fetched_ts"))
                v = cached.get("vix")
                if (isinstance(v, dict) and v.get("value") is not None
                        and self._ctx_has_key):
                    self._ctx_vix = self._vix_tile(v, v.get("fetched_ts"))
            except Exception:
                log.exception("context cache restore failed; starting empty")
        if isinstance(cached, dict):
            try:
                u = cached.get("ukrates")
                if isinstance(u, dict) and (u.get("sonia") is not None
                                            or u.get("bank_rate") is not None):
                    self._ctx_ukrates = self._ukrates_tile(u, u.get("fetched_ts"))
                fxd = cached.get("fx")
                if isinstance(fxd, dict) and fxd.get("rate") is not None:
                    self._ctx_fx = self._fx_view(fxd, fxd.get("fetched_ts"))
            except Exception:
                log.exception("context cache restore failed; starting empty")
        if not self._ctx_has_key:
            self._ctx_vix = VixTile(needs_key=True, note="needs a free FRED key")
        now = self._wallclock()
        self._ctx_due = {"treasury": now + 4.0, "fng": now + 6.0, "vix": now + 8.0,
                         "boe": now + 10.0, "fx": now + 12.0}

    @staticmethod
    def _yields_tile(data, fetched_ts=None, note=""):
        def _f(key):
            val = data.get(key)
            try:
                return None if val is None else float(val)
            except (TypeError, ValueError):
                return None
        sp = spread_bp(_f("y2y"), _f("y10y"))
        return YieldCurveTile(available=True, as_of=str(data.get("as_of") or ""),
                              fetched_ts=fetched_ts, y3m=_f("y3m"), y2y=_f("y2y"),
                              y10y=_f("y10y"), y30y=_f("y30y"), spread_bp=sp,
                              reading=curve_reading(sp), note=note)

    @staticmethod
    def _sentiment_tile(data, fetched_ts=None, note=""):
        try:
            value = int(data.get("value"))  # type: ignore[arg-type] # guarded by caller
        except (TypeError, ValueError):
            value = None
        return SentimentTile(available=(value is not None),
                             as_of=str(data.get("as_of") or ""), fetched_ts=fetched_ts,
                             value=value,
                             classification=str(data.get("classification") or ""),
                             note=note)

    @staticmethod
    def _vix_tile(data, fetched_ts=None, note=""):
        try:
            value = float(data.get("value"))  # type: ignore[arg-type] # guarded by caller
        except (TypeError, ValueError):
            value = None
        change = data.get("change")
        try:
            change = None if change is None else float(change)
        except (TypeError, ValueError):
            change = None
        return VixTile(available=(value is not None), needs_key=False,
                       as_of=str(data.get("as_of") or ""), fetched_ts=fetched_ts,
                       value=value, change=change, band=vix_band(value), note=note)

    @staticmethod
    def _ukrates_tile(data, fetched_ts=None, note=""):
        def _f(key):
            val = data.get(key)
            try:
                return None if val is None else float(val)
            except (TypeError, ValueError):
                return None
        sonia, bank = _f("sonia"), _f("bank_rate")
        return UkRatesTile(available=(sonia is not None or bank is not None),
                           as_of=str(data.get("as_of") or ""),
                           fetched_ts=fetched_ts, sonia=sonia,
                           sonia_as_of=str(data.get("sonia_as_of") or ""),
                           bank_rate=bank,
                           bank_rate_as_of=str(data.get("bank_rate_as_of") or ""),
                           note=note)

    @staticmethod
    def _fx_view(data, fetched_ts=None, note=""):
        try:
            rate = float(data.get("rate"))         # type: ignore[arg-type]
        except (TypeError, ValueError):
            rate = None
        return FxRateView(available=(rate is not None), rate=rate,
                          as_of=str(data.get("as_of") or ""),
                          fetched_ts=fetched_ts, note=note)

    def _refresh_context_if_due(self, now):
        # one context refresh per tick at most; True when one ran
        for kind in ("treasury", "fng", "vix", "boe", "fx"):
            if now >= self._ctx_due.get(kind, float("inf")):
                self._refresh_context(kind, now)
                return True
        return False

    @staticmethod
    def _fail_note(tile):
        if getattr(tile, "available", False) and getattr(tile, "as_of", ""):
            return f"refresh failed - showing {tile.as_of}"
        return "unavailable - retrying"

    def _refresh_context(self, kind, now):
        ok = False
        try:
            if kind == "treasury":
                res = fetch_treasury_yields(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_yields = self._yields_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (treasury): %s", res.error)
                    self._ctx_yields = replace(self._ctx_yields,
                                               note=self._fail_note(self._ctx_yields))
            elif kind == "fng":
                res = fetch_fear_greed(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_sentiment = self._sentiment_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (fng): %s", res.error)
                    self._ctx_sentiment = replace(self._ctx_sentiment,
                                                  note=self._fail_note(self._ctx_sentiment))
            elif kind == "boe":  # keyless
                res = fetch_boe_rates(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_ukrates = self._ukrates_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (boe): %s", res.error)
                    self._ctx_ukrates = replace(self._ctx_ukrates,
                                                note=self._fail_note(self._ctx_ukrates))
            elif kind == "fx":  # keyless
                res = fetch_gbp_rate(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_fx = self._fx_view(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (fx): %s", res.error)
                    self._ctx_fx = replace(self._ctx_fx,
                                           note=self._fail_note(self._ctx_fx))
            elif kind == "vix":
                try:
                    key = read_env_key()
                except Exception:
                    key = None
                self._ctx_has_key = bool(key)
                if not key:                            # the designed keyless state
                    self._ctx_vix = VixTile(needs_key=True,
                                            note="needs a free FRED key")
                else:
                    res = fetch_vix(key, config.CONTEXT_TIMEOUT_S)
                    if res.ok:
                        self._ctx_vix = self._vix_tile(res.data, fetched_ts=now)
                        ok = True
                    else:
                        log.warning("context fetch failed (vix): %s", res.error)
                        note = (config.INVALID_KEY_VIX_MSG
                                if res.error is not None
                                and res.error.kind == SourceErrorKind.INVALID_KEY
                                else self._fail_note(self._ctx_vix))
                        self._ctx_vix = replace(self._ctx_vix, note=note)
        except Exception:                              # structural never-raise
            log.exception("context refresh failed (%s)", kind)
        self._ctx_due[kind] = now + (config.CONTEXT_REFRESH_S if ok
                                     else config.CONTEXT_RETRY_S)
        if ok:
            self._persist_context_cache()
        self._emit_snapshot(None)

    def _persist_context_cache(self):
        try:
            payload: dict = {}
            y = self._ctx_yields
            if y.available:
                payload["yields"] = {"as_of": y.as_of, "fetched_ts": y.fetched_ts,
                                     "y3m": y.y3m, "y2y": y.y2y,
                                     "y10y": y.y10y, "y30y": y.y30y}
            f = self._ctx_sentiment
            if f.available:
                payload["sentiment"] = {"as_of": f.as_of, "fetched_ts": f.fetched_ts,
                                        "value": f.value,
                                        "classification": f.classification}
            v = self._ctx_vix
            if v.available:
                payload["vix"] = {"as_of": v.as_of, "fetched_ts": v.fetched_ts,
                                  "value": v.value, "change": v.change}
            u = self._ctx_ukrates
            if u.available:
                payload["ukrates"] = {"as_of": u.as_of, "fetched_ts": u.fetched_ts,
                                      "sonia": u.sonia,
                                      "sonia_as_of": u.sonia_as_of,
                                      "bank_rate": u.bank_rate,
                                      "bank_rate_as_of": u.bank_rate_as_of}
            x = self._ctx_fx
            if x.available:
                payload["fx"] = {"rate": x.rate, "as_of": x.as_of,
                                 "fetched_ts": x.fetched_ts}
            self._set_setting(CONTEXT_KEY, payload)
        except Exception:
            log.exception("context cache persist failed; tiles stay in-memory")

    def _build_context_view(self):
        y, v, f = self._ctx_yields, self._ctx_vix, self._ctx_sentiment
        parts = []
        parts.append(f"10Y {y.y10y:.2f}" if (y.available and y.y10y is not None)
                     else "10Y -")
        if v.needs_key:
            parts.append("VIX needs key")
        else:
            parts.append(f"VIX {v.value:.1f}" if (v.available and v.value is not None)
                         else "VIX -")
        parts.append(f"F&G {f.value}" if (f.available and f.value is not None)
                     else "F&G -")
        return MarketContextView(yields=y, sentiment=f, vix=v,
                                 ukrates=self._ctx_ukrates,
                                 summary=" · ".join(parts))

    def _build_health_view(self):
        providers = self._provider_lines()
        if self._last_error is None:
            return HealthView(state="ok", reason="data ok", providers=providers)
        kind, msg, since = self._last_error
        state = classify_health(kind, msg)
        if kind == "invalid_key":
            reason = "key rejected - check it"
        elif state == "needs_key":
            reason = "needs a free key"
        elif state == "offline":
            reason = "offline - retrying"
        else:
            reason = f"retrying - {kind}"
        return HealthView(state=state, reason=reason, detail=str(msg),
                          since_ts=since, providers=providers)

    # -- the data-integrity view ---------------- #
    def _provider_integrity_rows(self) -> list[IntegrityRow]:
        rows = []
        for name, state in self._provider_lines():
            err = self._provider_errors.get(name)
            detail, since = "", None
            if isinstance(err, tuple):
                _kind, detail, since = err
            rows.append(IntegrityRow(provider=name, state=state,
                                     detail=str(detail), since_ts=since))
        return rows

    def _integrity_now(self) -> DataIntegrityView:
        # provider rows are recomputed each snapshot; gaps reuse the last rebuild
        providers = self._provider_integrity_rows()
        return DataIntegrityView(providers=tuple(providers),
                                 gaps=self._integrity.gaps,
                                 checked_ts=self._integrity.checked_ts)

    def _build_integrity_view(self) -> DataIntegrityView:
        # provider state plus a daily-history gap check against the NYSE calendar
        providers = self._provider_integrity_rows()
        gaps = []
        try:
            for sym in sorted(self._asset_closes):
                dates = [d for d, _ in self._asset_closes[sym]]
                present, missing, first, last = \
                    eng_returns.missing_trading_days(dates)
                gaps.append(GapRow(symbol=sym, cached_days=present,
                                   missing_days=missing,
                                   first=(first.isoformat() if first else ""),
                                   last=(last.isoformat() if last else "")))
        except Exception:
            log.exception("gap check failed")
        return DataIntegrityView(providers=tuple(providers), gaps=tuple(gaps),
                                 checked_ts=self._wallclock())

    # -- repository helpers (swallow DB errors -> degrade, never crash) ------ #
    def _open_repo(self) -> None:
        try:
            self._repo = open_repository(self._db_url)
        except Exception:
            log.exception("DB open failed; falling back to in-memory (ephemeral)")
            self._db_degraded = True                   # surfaced after start
            try:
                self._repo = MahadRepository("sqlite:///:memory:")
            except Exception:
                log.exception("in-memory DB also failed; persistence disabled")
                self._repo = None

    def _get_setting(self, key: str):
        if self._repo is None:
            return None
        try:
            return self._repo.get_setting(key)
        except Exception:
            log.exception("get_setting failed")
            return None

    def _set_setting(self, key: str, value) -> None:
        if self._repo is not None:
            self._repo.set_setting(key, value)


@dataclass(frozen=True)
class _CryptoDailyRow:
    # DailyBar-shaped so crypto can reuse the same daily-bar persistence path
    ts: float
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


def _provider(asset_class: str, venue: str) -> str:
    from mahad.data.symbols import provider_for
    return provider_for(asset_class, venue)
