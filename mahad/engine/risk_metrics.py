from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

TRADING_DAYS_PER_YEAR = 252

# --------------------------------------------------------------------------- #
# A. Standard normal quantiles (bisection on Phi; no scipy)
# --------------------------------------------------------------------------- #
def phi_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def z_quantile(p: float, lo: float = -10.0, hi: float = 10.0) -> float:
    # standard normal quantile by bisection
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if phi_cdf(mid) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


CHI2_1_CRIT_95 = z_quantile(0.975) ** 2          # 3.8415


# --------------------------------------------------------------------------- #
# Historical-simulation VaR + Expected Shortfall
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class TailResult:
    value: float                 # the positive loss fraction
    m: int                       # the order-statistic index used
    n: int                       # observations in the window
    confidence: float


def historical_var(returns: Sequence[float], confidence: float) -> Optional[TailResult]:
    # VaR_c = -r(m), m = floor((1-c)T) + 1 on the ascending sort
    n = len(returns)
    if n == 0 or not 0.0 < confidence < 1.0:
        return None
    m = math.floor((1.0 - confidence) * n) + 1
    if m > n:
        return None
    srt = sorted(returns)
    return TailResult(value=-srt[m - 1], m=m, n=n, confidence=confidence)


def expected_shortfall(returns: Sequence[float], confidence: float
                       ) -> Optional[TailResult]:
    # mean of the m worst returns, tail inclusive so ES >= VaR
    var = historical_var(returns, confidence)
    if var is None:
        return None
    srt = sorted(returns)
    tail = srt[:var.m]
    return TailResult(value=-(sum(tail) / len(tail)), m=var.m, n=var.n,
                      confidence=confidence)


# --------------------------------------------------------------------------- #
# Parametric (variance-covariance) VaR
# --------------------------------------------------------------------------- #
def sample_sd(values: Sequence[float]) -> Optional[float]:
    # sample sd, ddof = 1
    n = len(values)
    if n < 2:
        return None
    mu = sum(values) / n
    return math.sqrt(sum((v - mu) ** 2 for v in values) / (n - 1))


def parametric_var_from_moments(mu: float, sigma: float, confidence: float
                                ) -> Optional[float]:
    if sigma < 0.0 or not 0.0 < confidence < 1.0:
        return None
    return -(float(mu) - z_quantile(confidence) * float(sigma))


def parametric_var(returns: Sequence[float], confidence: float
                   ) -> Optional[float]:
    # mu and sd (ddof = 1) from the window, then plug into the parametric form
    sd = sample_sd(returns)
    if sd is None:
        return None
    mu = sum(returns) / len(returns)
    return parametric_var_from_moments(mu, sd, confidence)


def normal_es_multiplier(confidence: float) -> float:
    # pdf(z_c) / (1 - c)
    z = z_quantile(confidence)
    pdf = math.exp(-z * z / 2.0) / math.sqrt(2.0 * math.pi)
    return pdf / (1.0 - confidence)


# --------------------------------------------------------------------------- #
# Kupiec POF + the Basel traffic light
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class KupiecResult:
    lr: float
    p_value: float
    reject: bool                 # at 5% (LR > 3.8415)
    exceptions: int
    observations: int


def kupiec_pof(exceptions: int, observations: int, p: float = 0.01
               ) -> Optional[KupiecResult]:
    # proportion-of-failures LR, chi-square(1) under correct coverage
    x, t = int(exceptions), int(observations)
    if t <= 0 or x < 0 or x > t or not 0.0 < p < 1.0:
        return None
    if x == 0:
        lr = -2.0 * ((t - x) * math.log(1.0 - p)) \
            + 2.0 * ((t - x) * math.log(1.0 - x / t))
    elif x == t:
        lr = -2.0 * (x * math.log(p)) + 2.0 * (x * math.log(x / t))
    else:
        a = (t - x) * math.log(1.0 - p) + x * math.log(p)
        b = (t - x) * math.log(1.0 - x / t) + x * math.log(x / t)
        lr = -2.0 * a + 2.0 * b
    p_value = math.erfc(math.sqrt(max(lr, 0.0) / 2.0))   # 1 - chi2_1.cdf(lr)
    return KupiecResult(lr=lr, p_value=p_value, reject=(lr > CHI2_1_CRIT_95),
                        exceptions=x, observations=t)


def basel_zone(exceptions: int) -> str:
    # bcbs22 traffic light at 99%/250 days: green 0-4, yellow 5-9, red 10+
    x = int(exceptions)
    if x <= 4:
        return "green"
    if x <= 9:
        return "yellow"
    return "red"


@dataclass(frozen=True, slots=True)
class BackcastResult:
    exceptions: int
    observations: int
    window: int
    confidence: float


def backcast_exceptions(returns: Sequence[float], confidence: float = 0.99,
                        window: int = 250) -> Optional[BackcastResult]:
    # count days whose realised return breached the prior-window VaR
    n = len(returns)
    w = int(window)
    if w < 2 or n <= w:
        return None
    x = 0
    obs = 0
    for t in range(w, n):
        var = historical_var(returns[t - w:t], confidence)
        if var is None:
            continue
        obs += 1
        if returns[t] < -var.value:
            x += 1
    return BackcastResult(exceptions=x, observations=obs, window=w,
                          confidence=confidence)


# --------------------------------------------------------------------------- #
# Beta - ddof cancels when consistent
# --------------------------------------------------------------------------- #
def beta(portfolio: Sequence[float], benchmark: Sequence[float]
         ) -> Optional[float]:
    n = min(len(portfolio), len(benchmark))
    if n < 2:
        return None
    rp, rb = list(portfolio[-n:]), list(benchmark[-n:])
    mp = sum(rp) / n
    mb = sum(rb) / n
    cov = sum((a - mp) * (b - mb) for a, b in zip(rp, rb, strict=False))
    var_b = sum((b - mb) ** 2 for b in rb)
    if var_b == 0.0:
        return None
    return cov / var_b


# --------------------------------------------------------------------------- #
# Sharpe + Sortino
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RatioResult:
    daily: float
    annualised: float            # x sqrt(252) - the trading-day basis


def sharpe(returns: Sequence[float], rf_daily: float) -> Optional[RatioResult]:
    # excess-return mean over sd (ddof=1), annualised by sqrt(252)
    if not returns:
        return None
    excess = [r - rf_daily for r in returns]
    sd = sample_sd(excess)
    if sd is None or sd == 0.0:
        return None
    daily = (sum(excess) / len(excess)) / sd
    return RatioResult(daily=daily,
                       annualised=daily * math.sqrt(TRADING_DAYS_PER_YEAR))


def sortino(returns: Sequence[float], target: float = 0.0
            ) -> Optional[RatioResult]:
    # full-N downside deviation in the denominator, not the sample sd
    n = len(returns)
    if n == 0:
        return None
    downside = [min(r - target, 0.0) for r in returns]
    dd_dev = math.sqrt(sum(d * d for d in downside) / n)
    if dd_dev == 0.0:
        return None
    daily = (sum(returns) / n - target) / dd_dev
    return RatioResult(daily=daily,
                       annualised=daily * math.sqrt(TRADING_DAYS_PER_YEAR))


# --------------------------------------------------------------------------- #
# EWMA volatility (RiskMetrics lambda 0.94)
# --------------------------------------------------------------------------- #
def ewma_volatility(returns: Sequence[float], lam: float = 0.94,
                    seed_variance: Optional[float] = None) -> Optional[float]:
    # sigma_t^2 = lam sigma_(t-1)^2 + (1 - lam) r_(t-1)^2, lambda 0.94 daily
    if not returns or not 0.0 < lam < 1.0:
        return None
    if seed_variance is None:
        sd = sample_sd(returns)
        if sd is None:
            return None
        s2 = sd * sd
    else:
        s2 = float(seed_variance)
    for r in returns:
        s2 = lam * s2 + (1.0 - lam) * r * r
    return math.sqrt(s2)


# --------------------------------------------------------------------------- #
# Pearson correlation matrix
# --------------------------------------------------------------------------- #
def correlation(a: Sequence[float], b: Sequence[float]) -> Optional[float]:
    n = min(len(a), len(b))
    if n < 2:
        return None
    xa, xb = list(a[-n:]), list(b[-n:])
    ma = sum(xa) / n
    mb = sum(xb) / n
    da = [v - ma for v in xa]
    db = [v - mb for v in xb]
    den = math.sqrt(sum(v * v for v in da) * sum(v * v for v in db))
    if den == 0.0:
        return None
    return sum(x * y for x, y in zip(da, db, strict=False)) / den


def correlation_matrix(series: Mapping[str, Sequence[float]], window: int = 90
                       ) -> tuple[tuple[str, ...], tuple[tuple[Optional[float], ...], ...]]:
    symbols = tuple(sorted(series))
    rows = []
    for a in symbols:
        row: list[Optional[float]] = []
        for b in symbols:
            if a == b:
                row.append(1.0)
            else:
                row.append(correlation(list(series[a])[-window:],
                                       list(series[b])[-window:]))
        rows.append(tuple(row))
    return symbols, tuple(rows)


# --------------------------------------------------------------------------- #
# Concentration: HHI, effective N, largest weight
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class ConcentrationResult:
    hhi: float
    effective_n: float
    top_symbol: str
    top_weight: float
    sector_hhi: Optional[float] = None
    sector_weights: tuple[tuple[str, float], ...] = ()


def concentration(position_values: Mapping[str, float],
                  sectors: Optional[Mapping[str, str]] = None
                  ) -> Optional[ConcentrationResult]:
    # HHI on position weights, cash excluded; effective N = 1/HHI
    total = sum(v for v in position_values.values() if v > 0.0)
    if total <= 0.0:
        return None
    weights = {s: v / total for s, v in position_values.items() if v > 0.0}
    hhi = sum(w * w for w in weights.values())
    top_symbol, top_weight = max(weights.items(), key=lambda kv: kv[1])
    sector_hhi = None
    sector_rows: tuple[tuple[str, float], ...] = ()
    if sectors:
        by_sector: dict[str, float] = {}
        for sym, w in weights.items():
            sec = sectors.get(sym) or "Unclassified"
            by_sector[sec] = by_sector.get(sec, 0.0) + w
        sector_hhi = sum(w * w for w in by_sector.values())
        sector_rows = tuple(sorted(by_sector.items(),
                                   key=lambda kv: -kv[1]))
    return ConcentrationResult(hhi=hhi, effective_n=1.0 / hhi,
                               top_symbol=top_symbol, top_weight=top_weight,
                               sector_hhi=sector_hhi,
                               sector_weights=sector_rows)


# --------------------------------------------------------------------------- #
# Drawdown duration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class DrawdownDuration:
    depth_pct: float             # negative %
    peak_index: int
    trough_index: int
    recovery_index: Optional[int]    # None = not yet recovered
    duration_periods: Optional[int]  # peak -> recovery; None = ongoing
    ongoing_periods: Optional[int]   # peak -> last sample when unrecovered


def drawdown_duration(values: Sequence[float]) -> Optional[DrawdownDuration]:
    # worst peak-trough pair, recovery is the first sample back at or above the peak
    if len(values) < 2 or any(v <= 0.0 for v in values):
        return None
    peak = values[0]
    peak_i = 0
    worst = 0.0
    worst_peak_i = 0
    worst_trough_i: Optional[int] = None
    for i, v in enumerate(values):
        if v > peak:
            peak, peak_i = v, i
        dd = v / peak - 1.0
        if dd < worst:
            worst, worst_peak_i, worst_trough_i = dd, peak_i, i
    if worst_trough_i is None:
        return DrawdownDuration(depth_pct=0.0, peak_index=0, trough_index=0,
                                recovery_index=0, duration_periods=0,
                                ongoing_periods=None)
    rec_i = next((j for j in range(worst_trough_i, len(values))
                  if values[j] >= values[worst_peak_i]), None)
    return DrawdownDuration(
        depth_pct=worst * 100.0, peak_index=worst_peak_i,
        trough_index=worst_trough_i, recovery_index=rec_i,
        duration_periods=(rec_i - worst_peak_i) if rec_i is not None else None,
        ongoing_periods=(len(values) - 1 - worst_peak_i) if rec_i is None
        else None)


# --------------------------------------------------------------------------- #
# Historical stress replay - linear re-pricing
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class StressLeg:
    symbol: str
    weight: float
    window_return: Optional[float]   # None = no data for this window
    source: str = ""                 # "cache" | "constant" | ""


@dataclass(frozen=True, slots=True)
class StressResult:
    scenario: str
    start: str                       # ISO dates (the card shows them)
    end: str
    pl_usd: Optional[float]          # None when NO leg has data
    covered_weight: float            # weight with data (honesty label)
    legs: tuple[StressLeg, ...]


def stress_replay(scenario: str, start: str, end: str, portfolio_value: float,
                  weights: Mapping[str, float],
                  window_returns: Mapping[str, tuple[float, str]]
                  ) -> StressResult:
    # linear re-pricing: P&L = V x sum_i(w_i x R_i(window))
    legs = []
    total = 0.0
    covered = 0.0
    any_data = False
    for sym, w in sorted(weights.items()):
        entry = window_returns.get(sym)
        if entry is None:
            legs.append(StressLeg(symbol=sym, weight=float(w),
                                  window_return=None))
            continue
        r, source = entry
        legs.append(StressLeg(symbol=sym, weight=float(w),
                              window_return=float(r), source=source))
        total += float(w) * float(r)
        covered += float(w)
        any_data = True
    return StressResult(scenario=scenario, start=start, end=end,
                        pl_usd=(portfolio_value * total) if any_data else None,
                        covered_weight=covered, legs=tuple(legs))


# --------------------------------------------------------------------------- #
# Component VaR: additive parametric (Euler) risk contributions.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class RiskContribution:
    symbol: str
    weight: float                # w_i = value_i / portfolio value
    mctr: float                  # marginal contribution = (Sigma w)_i / sig_p
    cctr: float                  # component contribution = w_i * mctr
    comp_var: float              # z_c * cctr (signed loss fraction)
    pct: float                   # cctr / sig_p (signed share of total risk)


@dataclass(frozen=True, slots=True)
class ComponentVarResult:
    confidence: float
    portfolio_sigma: float       # sig_p (daily fraction)
    portfolio_var: float         # z_c * sig_p (positive loss fraction, zero-mean)
    contributions: tuple[RiskContribution, ...]   # sorted by cctr, descending
    n: int                       # aligned observations on the common grid


def covariance_matrix(vectors: Sequence[Sequence[float]]
                      ) -> Optional[list[list[float]]]:
    # sample covariance, ddof = 1, equal-length vectors
    k = len(vectors)
    if k == 0:
        return None
    n = len(vectors[0])
    if n < 2 or any(len(v) != n for v in vectors):
        return None
    means = [sum(v) / n for v in vectors]
    # centre each vector once; summation order unchanged so values are identical.
    centered = [[v[t] - m for t in range(n)] for v, m in zip(vectors, means, strict=True)]
    cov = [[0.0] * k for _ in range(k)]
    for i in range(k):
        ci = centered[i]
        for j in range(i, k):
            cj = centered[j]
            s = sum(ci[t] * cj[t] for t in range(n))
            cov[i][j] = cov[j][i] = s / (n - 1)
    return cov


def component_var(weights: Mapping[str, float],
                  aligned_returns: Mapping[str, Sequence[float]],
                  confidence: float) -> Optional[ComponentVarResult]:
    # parametric Euler decomposition over aligned return vectors
    syms = [s for s in sorted(aligned_returns) if s in weights]
    if not syms or not 0.0 < confidence < 1.0:
        return None
    vecs = [list(aligned_returns[s]) for s in syms]
    cov = covariance_matrix(vecs)
    if cov is None:
        return None
    n = len(vecs[0])
    k = len(syms)
    w = [float(weights[s]) for s in syms]
    sw = [sum(cov[i][j] * w[j] for j in range(k)) for i in range(k)]   # Sigma w
    var_p = sum(w[i] * sw[i] for i in range(k))                        # w^T Sigma w
    if var_p <= 0.0:
        return None
    sig_p = math.sqrt(var_p)
    z = z_quantile(confidence)
    contribs = []
    for i, s in enumerate(syms):
        mctr = sw[i] / sig_p
        cctr = w[i] * mctr
        contribs.append(RiskContribution(symbol=s, weight=w[i], mctr=mctr,
                                         cctr=cctr, comp_var=z * cctr,
                                         pct=cctr / sig_p))
    contribs.sort(key=lambda rc: rc.cctr, reverse=True)
    return ComponentVarResult(confidence=confidence, portfolio_sigma=sig_p,
                              portfolio_var=z * sig_p,
                              contributions=tuple(contribs), n=n)


# --------------------------------------------------------------------------- #
# Correlation summary: a pure reduction of the correlation matrix.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class CorrelationSummary:
    avg: float                            # mean defined off-diagonal rho
    max_pair: tuple[str, str, float]      # most correlated distinct pair
    min_pair: tuple[str, str, float]      # least correlated distinct pair
    n_pairs: int


def correlation_summary(symbols: Sequence[str],
                        matrix: Sequence[Sequence[Optional[float]]]
                        ) -> Optional[CorrelationSummary]:
    syms = list(symbols)
    n = len(syms)
    if n < 2:
        return None
    pairs: list[tuple[str, str, float]] = []
    for i in range(n):
        for j in range(i + 1, n):
            r = matrix[i][j]
            if r is None:
                continue
            pairs.append((syms[i], syms[j], float(r)))
    if not pairs:
        return None
    avg = sum(p[2] for p in pairs) / len(pairs)
    return CorrelationSummary(avg=avg,
                              max_pair=max(pairs, key=lambda p: p[2]),
                              min_pair=min(pairs, key=lambda p: p[2]),
                              n_pairs=len(pairs))


# --------------------------------------------------------------------------- #
# Return on VaR: the P&L-to-risk linkage ratio.
# --------------------------------------------------------------------------- #
def return_on_risk(pnl: Optional[float], var_usd: Optional[float]
                   ) -> Optional[float]:
    if pnl is None or var_usd is None or var_usd <= 0.0:
        return None
    return float(pnl) / float(var_usd)


# --------------------------------------------------------------------------- #
# Rolling VaR history: historical_var over a trailing window.
# --------------------------------------------------------------------------- #
def rolling_var(returns: Sequence[float], confidence: float, window: int,
                max_points: int = 40) -> tuple[float, ...]:
    n = len(returns)
    w = int(window)
    if w < 2 or n <= w or max_points < 1:
        return ()
    start = max(w, n - int(max_points) + 1)
    out: list[float] = []
    for t in range(start, n + 1):
        vr = historical_var(returns[t - w:t], confidence)
        if vr is not None:
            out.append(vr.value)
    return tuple(out)
