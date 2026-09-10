# PollWorker, the one QObject: the poll loop, intents, switching, the heartbeat, repository helpers
from __future__ import annotations

import datetime as _dt
import logging
import random
import time
from collections import deque
from dataclasses import replace
from decimal import Decimal
from typing import Optional

from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot

from mahad import config
from mahad.data.context_view import (DataIntegrityView, FxRateView, SentimentTile, UkRatesTile,
                                     VixTile, YieldCurveTile)
from mahad.data.models import Candle, Quote
from mahad.data.portfolio_view import RiskAnalyticsView
from mahad.data.repository import (INDICATORS_KEY, RISK_TIMEFRAME_KEY, MahadRepository,
                                   PersistedSymbol, PersistedTrade, open_repository)
from mahad.data.source import (MarketDataSource, SourceError, SourceErrorKind, is_crypto_symbol,
                               source_for_symbol)
from mahad.data.symbols import WatchlistRow, WatchlistState, provider_for, validate_add
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.market_session import session_line
from mahad.engine.portfolio import PortfolioState
from mahad.engine.risk import ValueSample
from mahad.engine.signals import AlertRule
from mahad.engine.snapshot import build_render_snapshot
from mahad.worker.alerts import AlertsMixin
from mahad.worker.analytics import AnalyticsMixin
from mahad.worker.context import ContextMixin
from mahad.worker.daily import DailyHistoryMixin
from mahad.worker.portfolio import PortfolioMixin

log = logging.getLogger("mahad.worker")


def _interrupted() -> bool:
    try:
        t = QThread.currentThread()
        return bool(t is not None and t.isInterruptionRequested())
    except Exception:
        return False


class PollWorker(AlertsMixin, PortfolioMixin, DailyHistoryMixin, AnalyticsMixin,
                 ContextMixin, QObject):
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
        self._candles: tuple[Candle, ...] = ()
        self._last_quote: Optional[Quote] = None
        self._marks: dict[str, Quote] = {}  # in-memory last-known marks
        self._persisted: list[PersistedSymbol] = []  # the cached watchlist rows
        self._settings = IndicatorSettings()
        # -- alert state (worker-thread only) -- #
        self._alerts: list[AlertRule] = []
        self._last_closed_ts: Optional[float] = None   # crossover no-replay baseline
        self._alerts_paused: bool = False
        # -- simulated-trade state (worker-thread only, single writer) -- #
        self._portfolio = PortfolioState(cash=Decimal(str(config.STARTING_CASH)),
                                         realised_pnl=Decimal("0"), positions=())
        self._starting_cash = Decimal(str(config.STARTING_CASH))
        self._trades: list[PersistedTrade] = []
        self._order_in_flight = False
        self._reset_in_flight = False               # single-flight reset
        self._held_cursor = 0
        # -- risk state (worker-thread only) -- #
        self._risk_timeframe = config.RISK_TIMEFRAME
        self._value_history: deque[ValueSample] = deque(maxlen=config.VALUE_HISTORY_CAP)
        self._peak_value: Optional[Decimal] = None
        self._peak_ts: Optional[float] = None
        # -- perf state (worker-confined) -- #
        self._adapters: dict[str, MarketDataSource] = {}   # cached provider adapters
        self._history: dict[tuple[str, str], tuple[Candle, ...]] = {}   # candle cache (symbol, timeframe)
        self._fail_streak = 0                              # consecutive active-fetch failures
        self._backoff_until = 0.0                          # capped backoff window
        self._monotonic = time.monotonic                   # injectable clock seam (tests)
        self._jitter = random.uniform                      # injectable jitter seam (tests)
        # -- state (worker-confined) -- #
        self._wallclock = time.time                # injectable wall-clock seam (tests)
        self._heartbeat: Optional[QTimer] = None   # the 5 s due-grid driver
        self._next_sample_due: Optional[float] = None   # the fixed wall-clock sample grid
        self._db_degraded = False                  # visible degraded persistence
        self._last_error: Optional[tuple[str, str, float]] = None   # (kind, message, since_ts) -> health chip
        self._ctx_yields = YieldCurveTile()        # context tiles (last-known, worker-confined)
        self._ctx_sentiment = SentimentTile()
        self._ctx_vix = VixTile()
        self._ctx_ukrates = UkRatesTile()
        self._ctx_fx = FxRateView()  # display-only
        self._integrity = DataIntegrityView()
        self._ctx_due: dict[str, float] = {}       # per-source wall-clock refresh dues
        self._ctx_has_key = False                  # presence only - the value is never logged
        # -- daily-series state (worker-confined) -- #
        self._daily_series: dict[str, tuple[Candle, ...]] = {}  # official stock 1d candles (DailyBar/Tiingo)
        self._provider_errors: dict[str, Optional[tuple[str, str, float]]] = {}   # None when healthy
        self._daily_due: dict[str, float] = {}  # per-symbol daily-coverage dues
        # -- state (the risk-analytics suite; worker-confined) -- #
        self._risk_dirty = True                     # daily data changed -> rebuild
        self._asset_returns: dict[str, list[tuple[_dt.date, float]]] = {}   # from adjusted closes
        self._asset_closes: dict[str, list[tuple[_dt.date, float]]] = {}    # adjusted closes (stress)
        self._analytics: Optional[RiskAnalyticsView] = None
        self._sectors: dict[str, str] = {}          # profile2 cache + the local fallback

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
        # cooperative; the running poll checks self._stop between steps
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
        thread = QThread.currentThread()
        if thread is self.thread():                   # a queued stop ends the loop after it, not before
            thread.quit()

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
        if self._stop:                                             # stop between steps
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
            asset_cls = "crypto" if is_crypto_symbol(self._symbol) else "stock"
            sess_state, sess_summary = session_line(asset_cls, self._wallclock())
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
                               provider_for(outcome.asset_class, self._venue))
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

    def _probe_symbol(self, symbol: str) -> tuple[bool, str]:
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
        # adapters are cached per (asset, tier); held marks get the shorter timeout
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

    def _watchlist_symbols(self) -> list[str]:
        return [p.symbol for p in self._persisted]

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

    def _start_heartbeat(self) -> None:
        # one timer drives value sampling and the slow context/daily refreshes
        self._next_sample_due = (self._wallclock()
                                 + config.risk_timeframe_seconds(self._risk_timeframe))
        if self._heartbeat is None:
            self._heartbeat = QTimer(self)
            self._heartbeat.timeout.connect(self._on_heartbeat)
        self._heartbeat.setInterval(int(config.HEARTBEAT_INTERVAL_S * 1000))
        self._heartbeat.start()

    @Slot()
    def _on_heartbeat(self) -> None:
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

    def _get_setting(self, key: str) -> object:
        if self._repo is None:
            return None
        try:
            return self._repo.get_setting(key)
        except Exception:
            log.exception("get_setting failed")
            return None

    def _set_setting(self, key: str, value: object) -> None:
        if self._repo is not None:
            self._repo.set_setting(key, value)
