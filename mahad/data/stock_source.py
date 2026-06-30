# Finnhub marks plus sampled bars, with Tiingo history bolted on
from __future__ import annotations

from typing import Optional

from mahad import config
from mahad.data import sampled_bars
from mahad.data.finnhub_source import FinnhubSource
from mahad.data.models import Candle
from mahad.data.source import (FetchResult, SourceError,
                               dedupe_sort_candles)
from mahad.data.tiingo_source import DailyHistoryResult, TiingoSource


class StockSource:
    source_name = "finnhub"

    def __init__(self, request_timeout_s: float = config.REQUEST_TIMEOUT_S,
                 history_cap: int = config.HISTORY_CAP,
                 finnhub: Optional[FinnhubSource] = None,
                 tiingo: Optional[TiingoSource] = None) -> None:
        self._finnhub = finnhub or FinnhubSource(request_timeout_s)
        self._tiingo = tiingo or TiingoSource(request_timeout_s,
                                              history_cap=history_cap)
        self._history_cap = history_cap
        self._buckets: dict[tuple[str, str], Optional[sampled_bars.MarkBucket]] = {}
        self._series: dict[tuple[str, str], tuple[Candle, ...]] = {}
        self._backfill_tried: set[tuple[str, str]] = set()

    # -- key states -- #
    @property
    def needs_key(self) -> bool:
        return self._finnhub.needs_key

    @property
    def history_needs_key(self) -> bool:
        return self._tiingo.needs_key

    # -- protocol -- #
    def fetch_mark(self, symbol: str) -> FetchResult:
        return self._finnhub.fetch_mark(symbol)

    def fetch(self, symbol: str, timeframe: str) -> FetchResult:
        mark_res = self._finnhub.fetch_mark(symbol)
        if not mark_res.ok or mark_res.quote is None:
            return FetchResult(symbol, timeframe, error=mark_res.error)
        quote = mark_res.quote
        key = (symbol, timeframe)
        if key not in self._backfill_tried and timeframe in ("1m", "1h"):
            self._backfill_tried.add(key)
            backfill, err = self._tiingo.fetch_intraday(symbol, timeframe)
            if err is None and backfill:
                merged = dedupe_sort_candles(
                    (*self._series.get(key, ()), *backfill), self._history_cap)
                self._series[key] = merged
        closed, bucket = sampled_bars.update(
            self._buckets.get(key), symbol, timeframe, quote.mark,
            quote.exchange_ts if quote.exchange_ts else quote.ts)
        self._buckets[key] = bucket
        if closed is not None:
            self._series[key] = dedupe_sort_candles(
                (*self._series.get(key, ()), closed), self._history_cap)
        return FetchResult(symbol, timeframe, quote=quote,
                           candles=self._series.get(key, ()))

    # -- worker extensions -- #
    def fetch_daily_history(self, symbol: str,
                            start_date: Optional[str] = None) -> DailyHistoryResult:
        # worker persists this; it's the official EOD series
        return self._tiingo.fetch_daily(symbol, start_date)

    def fetch_profile_sector(self, symbol: str
                             ) -> tuple[str, Optional[SourceError]]:
        # sector feeds the concentration analytics
        return self._finnhub.fetch_profile_sector(symbol)
