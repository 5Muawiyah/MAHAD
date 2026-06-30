from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Quote:
    symbol: str
    mark: float
    ts: float                 # epoch seconds, UTC
    source: str               # provider name
    stale: bool = False
    # venue price time when supplied; display only
    exchange_ts: float | None = None


@dataclass(frozen=True, slots=True)
class Candle:
    # forming bar carries is_closed=False
    symbol: str
    timeframe: str
    ts: float                 # epoch seconds, UTC; bar open
    open: float
    high: float
    low: float
    close: float
    volume: float
    is_closed: bool = True
