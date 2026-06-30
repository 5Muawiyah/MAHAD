from __future__ import annotations

import math
from dataclasses import dataclass, replace
from enum import Enum
from typing import Optional, Protocol, Sequence, runtime_checkable

from mahad.config import DEFAULT_CRYPTO_VENUE, HISTORY_CAP, REQUEST_TIMEOUT_S
from mahad.data.models import Candle, Quote


class SourceErrorKind(str, Enum):
    TIMEOUT = "timeout"
    NETWORK = "network"
    EMPTY = "empty"
    BAD_DATA = "bad_data"
    UNKNOWN = "unknown"
    # keyed provider, no key configured
    NEEDS_KEY = "needs_key"
    # key present but rejected (HTTP 401)
    INVALID_KEY = "invalid_key"


@dataclass(frozen=True, slots=True)
class SourceError:
    kind: SourceErrorKind
    message: str = ""

    def __str__(self) -> str:
        return f"{self.kind.value}: {self.message}" if self.message else self.kind.value


@dataclass(frozen=True, slots=True)
class FetchResult:
    symbol: str
    timeframe: str
    quote: Optional[Quote] = None
    candles: tuple[Candle, ...] = ()
    error: Optional[SourceError] = None

    @property
    def ok(self) -> bool:
        # only ok with no error and a quote actually present
        return self.error is None and self.quote is not None


@runtime_checkable
class MarketDataSource(Protocol):
    def fetch(self, symbol: str, timeframe: str) -> FetchResult: ...

    def fetch_mark(self, symbol: str) -> FetchResult: ...


def is_valid_price(x: object) -> bool:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
    return math.isfinite(v) and v > 0.0


def dedupe_sort_candles(candles: Sequence[Candle],
                        history_cap: int = HISTORY_CAP) -> tuple[Candle, ...]:
    by_key: dict[tuple[str, str, float], Candle] = {}
    for c in candles:
        by_key[(c.symbol, c.timeframe, c.ts)] = c          # later occurrence wins
    ordered = sorted(by_key.values(), key=lambda c: c.ts)
    if history_cap is not None and len(ordered) > history_cap:
        ordered = ordered[-history_cap:]
    return tuple(ordered)


def normalize_ohlcv(symbol: str, timeframe: str,
                    rows: Sequence[Sequence[float]],
                    history_cap: int = HISTORY_CAP,
                    last_is_forming: bool = True) -> tuple[Candle, ...]:
    # raw OHLCV rows in, malformed rows dropped
    built: list[Candle] = []
    for row in rows:
        try:
            ts_f = float(row[0])
            o_f, h_f = float(row[1]), float(row[2])
            l_f, c_f = float(row[3]), float(row[4])
            v_f = float(row[5])
        except (TypeError, ValueError, IndexError):
            continue
        # non-finite ts/price, or a price at or below zero, is a bad row
        if not all(math.isfinite(x) for x in (ts_f, o_f, h_f, l_f, c_f)):
            continue
        if min(o_f, h_f, l_f, c_f) <= 0.0:
            continue
        if not math.isfinite(v_f):
            v_f = 0.0
        built.append(Candle(symbol=symbol, timeframe=timeframe, ts=ts_f,
                            open=o_f, high=h_f, low=l_f,
                            close=c_f, volume=v_f, is_closed=True))
    ordered = list(dedupe_sort_candles(built, history_cap))
    if last_is_forming and ordered:
        ordered[-1] = replace(ordered[-1], is_closed=False)
    return tuple(ordered)


def is_crypto_symbol(symbol: str) -> bool:
    # crypto is BASE/QUOTE (BTC/USD); stocks are bare tickers
    return "/" in symbol


def source_for_symbol(symbol: str, *,
                      request_timeout_s: float = REQUEST_TIMEOUT_S,
                      venue: str = DEFAULT_CRYPTO_VENUE) -> MarketDataSource:
    # import the chosen provider lazily so neither pulls the other in
    if is_crypto_symbol(symbol):
        from mahad.data.kraken_source import KrakenSource
        return KrakenSource(request_timeout_s=request_timeout_s)
    from mahad.data.stock_source import StockSource
    return StockSource(request_timeout_s=request_timeout_s)
