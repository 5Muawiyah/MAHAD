from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Optional

from mahad import config
from mahad.data.budget import RateBudget
from mahad.data.context_sources import read_env_key
from mahad.data.models import Quote
from mahad.data.source import (FetchResult, SourceError, SourceErrorKind,
                               is_valid_price)

_UA = "MAHAD/2.0 (personal, non-commercial desktop app; simulated)"
FINNHUB_QUOTE_URL = "https://finnhub.io/api/v1/quote?symbol={symbol}"
FINNHUB_PROFILE_URL = "https://finnhub.io/api/v1/stock/profile2?symbol={symbol}"

# shared, since the rate limit is per key not per instance
_SHARED_BUDGET = RateBudget(config.FINNHUB_BUDGET_PER_MIN)


def _error_for(exc: Exception, redact: str = "") -> SourceError:
    msg = str(exc) or exc.__class__.__name__
    if redact:
        msg = msg.replace(redact, "***")
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:  # key rejected
            return SourceError(SourceErrorKind.INVALID_KEY, config.INVALID_KEY_STOCK_MSG)
        return SourceError(SourceErrorKind.NETWORK, f"HTTP {exc.code}")
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return SourceError(SourceErrorKind.TIMEOUT, msg)
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return SourceError(SourceErrorKind.NETWORK, msg)
    return SourceError(SourceErrorKind.BAD_DATA, msg)


class FinnhubSource:
    source_name = "finnhub"

    def __init__(self, request_timeout_s: float = config.REQUEST_TIMEOUT_S,
                 key: Optional[str] = None,
                 budget: Optional[RateBudget] = None) -> None:
        self._timeout = request_timeout_s
        self._key = key if key is not None else (
            read_env_key(config.FINNHUB_KEY_ENV) or "")
        self._budget = budget if budget is not None else _SHARED_BUDGET
        self._last: dict[str, Quote] = {}      # served on a denied tick

    @property
    def needs_key(self) -> bool:
        return not self._key

    def _get_json(self, url: str) -> dict[str, object]:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "X-Finnhub-Token": self._key})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}

    def fetch_mark(self, symbol: str) -> FetchResult:
        # failures come back as FetchResult.error, never as a raise
        if not self._key:
            return FetchResult(symbol, "1d", error=SourceError(
                SourceErrorKind.NEEDS_KEY, config.NEEDS_KEY_STOCK_MSG))
        if not self._budget.try_acquire():
            prior = self._last.get(symbol)
            if prior is not None:
                return FetchResult(symbol, "1d", quote=prior)
            return FetchResult(symbol, "1d", error=SourceError(
                SourceErrorKind.TIMEOUT, "paced - rate budget; retrying next cycle"))
        try:
            payload = self._get_json(FINNHUB_QUOTE_URL.format(symbol=symbol))
        except Exception as exc:
            return FetchResult(symbol, "1d", error=_error_for(exc, self._key))
        c, t = payload.get("c"), payload.get("t")
        if not is_valid_price(c) or not t:
            # unknown symbol returns a zeroed payload
            return FetchResult(symbol, "1d", error=SourceError(
                SourceErrorKind.EMPTY, "no usable mark"))
        quote = Quote(symbol=symbol, mark=float(str(c)), ts=time.time(),
                      source=self.source_name, stale=False,
                      exchange_ts=float(str(t)))
        self._last[symbol] = quote
        return FetchResult(symbol, "1d", quote=quote)

    def fetch(self, symbol: str, timeframe: str) -> FetchResult:
        # here only to satisfy the MarketDataSource protocol
        res = self.fetch_mark(symbol)
        return FetchResult(symbol, timeframe, quote=res.quote, error=res.error)

    def fetch_profile_sector(self, symbol: str) -> tuple[str, Optional[SourceError]]:
        if not self._key:
            return "", SourceError(SourceErrorKind.NEEDS_KEY,
                                   config.NEEDS_KEY_STOCK_MSG)
        try:
            payload = self._get_json(FINNHUB_PROFILE_URL.format(symbol=symbol))
        except Exception as exc:
            return "", _error_for(exc, self._key)
        sector = str(payload.get("finnhubIndustry") or "").strip()
        if not sector:
            return "", SourceError(SourceErrorKind.EMPTY, "no sector field")
        return sector, None
