# daily-bar coverage, the official 1d series, provider health notes
from __future__ import annotations

import datetime as _dt
import logging
from dataclasses import dataclass
from typing import Optional


from mahad import config
from mahad.data.models import Candle
from mahad.data.source import (is_crypto_symbol)
from mahad.engine.returns import needs_full_repull
from mahad.engine.resample import RESAMPLE_TIMEFRAMES, resample_daily_candles

from mahad.worker.state import WorkerState

log = logging.getLogger("mahad.worker")



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


class DailyHistoryMixin(WorkerState):
    def _daily_coverage_symbols(self) -> list[str]:
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

    def _refresh_daily_if_due(self, now: float) -> None:
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

    def _refresh_daily_symbol(self, symbol: str) -> bool:
        try:
            if is_crypto_symbol(symbol):
                return self._refresh_daily_crypto(symbol)
            return self._refresh_daily_stock(symbol)
        except Exception:                              # structural never-raise
            log.exception("daily refresh failed (%s)", symbol)
            return False

    def _refresh_daily_stock(self, symbol: str) -> bool:
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
            start_date = _dt.datetime.fromtimestamp(
                latest, _dt.UTC).date().isoformat()
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

    def _refresh_daily_crypto(self, symbol: str) -> bool:
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

    def _run_data_migration(self) -> None:
        if self._repo is None:
            return
        try:
            self._repo.migrate_legacy_schema()
        except Exception:
            log.exception("data migration failed; continuing")

    def _chart_candles(self, symbol: str, timeframe: str,
                       fetched: tuple[Candle, ...]) -> tuple[Candle, ...]:
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

    def _provider_lines(self) -> tuple[tuple[str, str], ...]:
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
