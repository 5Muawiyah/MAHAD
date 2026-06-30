from __future__ import annotations

import datetime as _dt
from typing import Sequence

from mahad.data.models import Candle

RESAMPLE_TIMEFRAMES = ("3d", "1w", "1mo")


def _bucket_key(d: _dt.date, timeframe: str, index: int) -> tuple[int, ...]:
    if timeframe == "1mo":
        return (d.year, d.month)
    if timeframe == "1w":
        iso = d.isocalendar()
        return (iso[0], iso[1])
    return (index // 3,)            # 3d buckets group 3 consecutive trading days


def resample_daily_candles(daily: Sequence[Candle], timeframe: str) -> tuple[Candle, ...]:
    if timeframe not in RESAMPLE_TIMEFRAMES:
        return tuple(daily)
    if not daily:
        return ()
    sym = daily[0].symbol
    groups: list[tuple[tuple[int, ...], list[Candle]]] = []
    for i, cd in enumerate(daily):
        d = _dt.datetime.fromtimestamp(cd.ts, _dt.timezone.utc).date()
        key = _bucket_key(d, timeframe, i)
        if groups and groups[-1][0] == key:
            groups[-1][1].append(cd)
        else:
            groups.append((key, [cd]))
    n = len(groups)
    out: list[Candle] = []
    for gi, (_key, members) in enumerate(groups):
        first, last = members[0], members[-1]
        out.append(Candle(
            symbol=sym, timeframe=timeframe, ts=first.ts,
            open=first.open,
            high=max(m.high for m in members),
            low=min(m.low for m in members),
            close=last.close,
            volume=sum(m.volume for m in members),
            is_closed=(gi < n - 1),          # last group is still forming
        ))
    return tuple(out)
