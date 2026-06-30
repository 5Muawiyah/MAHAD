from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

import numpy as np

# wall-clock periods per year, keyed by risk_timeframe
PERIODS_PER_YEAR = {"1m": 525_600, "1h": 8_760, "1d": 365}
VOL_WINDOW = 30                       # rolling returns window N

# rendered verbatim by the UI
VOL_CAVEAT = (
    "Annualised on a calendar wall-clock basis (365), so treat it as indicative; "
    "the per-period figure is the headline."
)


def periods_per_year(timeframe: str) -> int:
    return PERIODS_PER_YEAR.get(timeframe, PERIODS_PER_YEAR["1d"])


@dataclass(frozen=True, slots=True)
class ValueSample:
    ts: float
    value: float
    stale: bool = False


# --------------------------------------------------------------------------- #
# Exposure - lookback: now
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ExposureResult:
    defined: bool
    abs_value: Optional[float]        # Sum(qty x mark), USD
    pct: Optional[float]  # exposure as a fraction
    out_of_range: bool               # pct outside [0,1]


def exposure(positions_value: float, portfolio_value: float) -> ExposureResult:
    pv = float(portfolio_value)
    if pv <= 0.0:
        return ExposureResult(defined=False, abs_value=None, pct=None, out_of_range=False)
    av = float(positions_value)
    frac = av / pv
    return ExposureResult(defined=True, abs_value=av, pct=frac,
                          out_of_range=(frac < 0.0 or frac > 1.0))


# --------------------------------------------------------------------------- #
# Returns + volatility - lookback: last <= N returns
# --------------------------------------------------------------------------- #
def simple_returns(samples: Sequence[ValueSample]) -> tuple[list[float], bool]:
    # only between consecutive non-stale, strictly-positive samples; skipped flags a dropped pair
    returns: list[float] = []
    skipped = False
    for prev, cur in zip(samples, samples[1:], strict=False):  # noqa: RUF007 - zip form kept verbatim
        prev_ok = (not prev.stale) and prev.value > 0.0
        cur_ok = (not cur.stale) and cur.value > 0.0
        if prev_ok and cur_ok:
            returns.append(cur.value / prev.value - 1.0)
        else:
            skipped = True
    return returns, skipped


@dataclass(frozen=True, slots=True)
class VolatilityResult:
    defined: bool
    per_period_pct: Optional[float]   # sigma x 100
    annualised_pct: Optional[float]   # sigma x sqrt(periods_per_year) x 100
    n_returns: int                    # returns used


def volatility(returns: Sequence[float], timeframe: str,
               window: int = VOL_WINDOW) -> VolatilityResult:
    # sample std-dev, ddof=1, over the last window returns
    r = list(returns)
    used = r[-window:] if (window and len(r) > window) else r
    if len(used) < 2:
        return VolatilityResult(defined=False, per_period_pct=None,
                                annualised_pct=None, n_returns=len(used))
    sigma = float(np.std(np.asarray(used, dtype=float), ddof=1))
    per_period = sigma * 100.0
    annualised = sigma * (periods_per_year(timeframe) ** 0.5) * 100.0
    return VolatilityResult(defined=True, per_period_pct=per_period,
                            annualised_pct=annualised, n_returns=len(used))


# --------------------------------------------------------------------------- #
# Maximum drawdown - lookback: since inception
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DrawdownResult:
    defined: bool
    max_dd_pct: float                 # negative %, 0.0 when flat/rising
    peak_ts: Optional[float]          # running-max ts at the worst trough
    trough_ts: Optional[float]        # sample ts of the worst trough


def max_drawdown(samples: Sequence[ValueSample],
                 peak_value: Optional[float] = None,
                 peak_ts: Optional[float] = None) -> DrawdownResult:
    # running max is seeded from the persisted all-time peak, and stale samples count here
    if not samples:
        return DrawdownResult(defined=False, max_dd_pct=0.0, peak_ts=peak_ts, trough_ts=None)
    if peak_value is not None and float(peak_value) > 0.0:
        run_max = float(peak_value)
        run_max_ts = peak_ts
    else:
        run_max = float(samples[0].value)
        run_max_ts = samples[0].ts
    worst = 0.0
    worst_peak_ts = run_max_ts
    worst_trough_ts: Optional[float] = None
    for s in samples:
        v = float(s.value)
        if v > run_max:
            run_max = v
            run_max_ts = s.ts
        if run_max > 0.0:
            dd = v / run_max - 1.0
            if dd < worst:
                worst = dd
                worst_peak_ts = run_max_ts
                worst_trough_ts = s.ts
    return DrawdownResult(defined=True, max_dd_pct=worst * 100.0,
                          peak_ts=worst_peak_ts, trough_ts=worst_trough_ts)
