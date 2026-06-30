from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Iterable, Mapping, Optional, Sequence

from mahad.engine.market_session import holidays_full

TRADING_DAYS_PER_YEAR = 252      # equities convention
DEFAULT_WINDOW = 250             # Basel one-year observation period


def is_us_trading_day(d: _dt.date) -> bool:
    return d.weekday() < 5 and d not in holidays_full(d.year)


def trading_date(ts: float) -> _dt.date:
    # daily bars are keyed by their UTC date
    return _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).date()


def align_daily_closes(rows: Iterable[tuple[float, float]]
                       ) -> list[tuple[_dt.date, float]]:
    by_date: dict[_dt.date, float] = {}
    for ts, close in sorted(rows, key=lambda r: r[0]):
        try:
            c = float(close)
        except (TypeError, ValueError):
            continue
        if c <= 0.0:
            continue
        d = trading_date(ts)
        if is_us_trading_day(d):
            by_date[d] = c
    return sorted(by_date.items())


def simple_returns_by_date(closes: Sequence[tuple[_dt.date, float]]
                           ) -> list[tuple[_dt.date, float]]:
    out: list[tuple[_dt.date, float]] = []
    for (_d0, c0), (d1, c1) in pairwise(closes):
        if c0 > 0.0 and c1 > 0.0:
            out.append((d1, c1 / c0 - 1.0))
    return out


def current_weights(positions: Sequence[tuple[str, float, float]],
                    cash: float) -> dict[str, float]:
    # weights are over cash + positions, so they need not sum to 1
    pv = sum(float(q) * float(m) for _s, q, m in positions)
    value = float(cash) + pv
    if value <= 0.0:
        return {}
    return {s: (float(q) * float(m)) / value for s, q, m in positions}


@dataclass(frozen=True, slots=True)
class DayReturn:
    value: float
    included: tuple[str, ...]
    excluded: tuple[str, ...]            # held but no return that day
    coverage_weight: float               # sum of included weights


def single_day_return(weights: Mapping[str, float],
                      day_returns: Mapping[str, float]) -> DayReturn:
    # an asset with no return today is reported, not counted as zero
    included, excluded = [], []
    total = 0.0
    cov = 0.0
    for sym, w in weights.items():
        r = day_returns.get(sym)
        if r is None:
            excluded.append(sym)
            continue
        included.append(sym)
        total += float(w) * float(r)
        cov += float(w)
    return DayReturn(value=total, included=tuple(sorted(included)),
                     excluded=tuple(sorted(excluded)), coverage_weight=cov)


@dataclass(frozen=True, slots=True)
class PortfolioReturns:
    dates: tuple[_dt.date, ...]
    returns: tuple[float, ...]
    included: tuple[str, ...]
    excluded: tuple[str, ...]
    coverage_weight: float
    # per-asset returns aligned to dates; internal, kept out of eq and repr
    aligned: dict[str, list[float]] = field(default_factory=dict, compare=False, repr=False)

    @property
    def n(self) -> int:
        return len(self.returns)


def portfolio_returns(weights: Mapping[str, float],
                      asset_returns: Mapping[str, Sequence[tuple[_dt.date, float]]],
                      window: int = DEFAULT_WINDOW) -> PortfolioReturns:
    # today's weights run over the included assets' common-date grid
    series: dict[str, dict[_dt.date, float]] = {}
    excluded: list[str] = []
    for sym in weights:
        rows = asset_returns.get(sym)
        if rows:
            series[sym] = dict(rows)
        else:
            excluded.append(sym)
    if not series:
        return PortfolioReturns((), (), (), tuple(sorted(excluded)), 0.0)
    common: set[_dt.date] = set.intersection(
        *(set(s) for s in series.values()))
    w = int(window)
    if common:
        dates = tuple(sorted(common)) if w <= 0 else tuple(sorted(common)[-w:])
    else:
        dates = ()
    # rp must keep the exact per-sym summation order
    aligned = {sym: [series[sym][d] for d in dates] for sym in series}
    rp = tuple(sum(float(weights[sym]) * aligned[sym][t] for sym in series)
               for t in range(len(dates)))
    cov = sum(float(weights[s]) for s in series)
    return PortfolioReturns(dates=dates, returns=rp,
                            included=tuple(sorted(series)),
                            excluded=tuple(sorted(excluded)),
                            coverage_weight=cov, aligned=aligned)


def rf_daily_from_annual_pct(annual_pct: Optional[float]) -> Optional[float]:
    # de-annualise as annual_pct/100/252
    if annual_pct is None:
        return None
    return float(annual_pct) / 100.0 / float(TRADING_DAYS_PER_YEAR)


def missing_trading_days(dates: Iterable[_dt.date]
                         ) -> tuple[int, int, Optional[_dt.date], Optional[_dt.date]]:
    have = set(dates)
    if not have:
        return (0, 0, None, None)
    first, last = min(have), max(have)
    present = 0
    missing = 0
    d = first
    while d <= last:
        if is_us_trading_day(d):
            if d in have:
                present += 1
            else:
                missing += 1
        d += _dt.timedelta(days=1)
    return (present, missing, first, last)


def needs_full_repull(rows: Iterable[object]) -> bool:
    # a dividend or split rewrites history, so re-download the lot
    for row in rows:
        try:
            if float(getattr(row, "div_cash", 0.0) or 0.0) > 0.0:
                return True
            if float(getattr(row, "split_factor", 1.0) or 1.0) != 1.0:
                return True
        except (TypeError, ValueError):
            continue
    return False
