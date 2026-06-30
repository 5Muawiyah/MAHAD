from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from mahad.data.models import Candle

_TF_SECONDS = {"1m": 60.0, "1h": 3600.0, "1d": 86400.0}


@dataclass(frozen=True, slots=True)
class MarkBucket:
    symbol: str
    timeframe: str
    start_ts: float            # bucket open boundary, UTC epoch
    open: float
    high: float
    low: float
    close: float


def timeframe_seconds(timeframe: str) -> float:
    return _TF_SECONDS.get(timeframe, 86400.0)


def bucket_start(ts: float, timeframe: str) -> float:
    period = timeframe_seconds(timeframe)
    return float(int(ts // period) * period)


def update(bucket: Optional[MarkBucket], symbol: str, timeframe: str,
           mark: float, exchange_ts: float
           ) -> tuple[Optional[Candle], Optional[MarkBucket]]:
    # one mark in -> (closed_candle, new_bucket)
    if not isinstance(mark, (int, float)) or not isinstance(exchange_ts, (int, float)):
        return None, bucket
    if mark <= 0.0 or exchange_ts <= 0.0:
        return None, bucket
    start = bucket_start(float(exchange_ts), timeframe)
    if bucket is None or bucket.symbol != symbol or bucket.timeframe != timeframe:
        return None, MarkBucket(symbol=symbol, timeframe=timeframe,
                                start_ts=start, open=float(mark),
                                high=float(mark), low=float(mark),
                                close=float(mark))
    if start < bucket.start_ts:
        return None, bucket                          # out-of-order
    if start == bucket.start_ts:
        return None, MarkBucket(symbol=symbol, timeframe=timeframe,
                                start_ts=bucket.start_ts, open=bucket.open,
                                high=max(bucket.high, float(mark)),
                                low=min(bucket.low, float(mark)),
                                close=float(mark))
    closed = Candle(symbol=symbol, timeframe=timeframe, ts=bucket.start_ts,
                    open=bucket.open, high=bucket.high, low=bucket.low,
                    close=bucket.close, volume=0.0, is_closed=True)
    fresh = MarkBucket(symbol=symbol, timeframe=timeframe, start_ts=start,
                       open=float(mark), high=float(mark), low=float(mark),
                       close=float(mark))
    return closed, fresh
