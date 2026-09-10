# the assembly steps the risk panel and the headless report share
from __future__ import annotations

import datetime as _dt
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

from mahad import config
from mahad.data.portfolio_view import StressRow
from mahad.engine import returns as eng_returns
from mahad.engine import risk_metrics as eng_rm
from mahad.engine.risk_metrics import KupiecResult

DatedSeries = Mapping[str, Sequence[tuple[_dt.date, float]]]


def sector_map(cached: object) -> dict[str, str]:
    # the local fallback map overlaid with the cached Finnhub sectors
    sectors = dict(config.DEFAULT_SECTOR_MAP)
    if isinstance(cached, dict):
        for k, v in cached.items():
            if isinstance(k, str) and isinstance(v, str) and v:
                sectors[k] = v
    return sectors


def window_return(closes: DatedSeries, scenario: str, symbol: str,
                  start: str, end: str) -> Optional[tuple[float, str]]:
    # the cached close-to-close return over the window, else the cited constant, else nothing
    series = closes.get(symbol)
    if series:
        d0, d1 = _dt.date.fromisoformat(start), _dt.date.fromisoformat(end)
        inside = [(d, c) for d, c in series if d0 <= d <= d1]
        if (len(inside) >= 2 and (inside[0][0] - d0).days <= 5
                and (d1 - inside[-1][0]).days <= 5):
            return inside[-1][1] / inside[0][1] - 1.0, "cache"
    const = config.STRESS_CONSTANTS.get((scenario, symbol))
    return None if const is None else (const, "constant")


def stress_rows(weights: Mapping[str, float], value: float,
                closes: DatedSeries) -> tuple[StressRow, ...]:
    rows = []
    for name, start, end in config.STRESS_SCENARIOS:
        window_returns: dict[str, tuple[float, str]] = {}
        for sym in weights:
            entry = window_return(closes, name, sym, start, end)
            if entry is not None:
                window_returns[sym] = entry
        res = eng_rm.stress_replay(name, start, end, value, weights, window_returns)
        rows.append(StressRow(
            scenario=name, start=start, end=end, pl_usd=res.pl_usd,
            covered_weight=res.covered_weight,
            legs_no_data=tuple(leg.symbol for leg in res.legs if leg.window_return is None),
            constant_legs=tuple(leg.symbol for leg in res.legs if leg.source == "constant")))
    return tuple(rows)


@dataclass(frozen=True, slots=True)
class BacktestSummary:
    mode: str                    # ex-ante, accruing or backcast
    exceptions: int
    observations: int
    kupiec: Optional[KupiecResult]


def backtest_summary(exceptions: int, observations: int, weights: Mapping[str, float],
                     asset_returns: DatedSeries) -> BacktestSummary:
    # the resolved rows lead; until the window fills, the trailing VaR is backcast over the cache
    mode = "ex-ante" if observations >= config.RISK_WINDOW else "accruing"
    bx, bt = exceptions, observations
    if observations < config.RISK_WINDOW:
        full = eng_returns.portfolio_returns(weights, asset_returns, window=0)
        bc = eng_rm.backcast_exceptions(list(full.returns), config.BACKTEST_CONFIDENCE,
                                        config.RISK_WINDOW)
        if bc is not None and bc.observations > 0:
            mode, bx, bt = "backcast", bc.exceptions, bc.observations
    kup = eng_rm.kupiec_pof(bx, bt, 1.0 - config.BACKTEST_CONFIDENCE) if bt > 0 else None
    return BacktestSummary(mode, bx, bt, kup)
