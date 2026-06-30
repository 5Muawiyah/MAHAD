from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Optional


@dataclass(frozen=True, slots=True)
class PositionRow:
    symbol: str
    asset_class: str
    quantity: Decimal
    avg_cost: Decimal
    mark: Optional[Decimal] = None
    unrealised: Optional[Decimal] = None
    value: Optional[Decimal] = None
    stale: bool = False


@dataclass(frozen=True, slots=True)
class TradeRow:
    # self-contained so the CSV export needs no joins
    ts: float
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    avg_cost_at_fill: Decimal
    qty_before: Decimal
    qty_after: Decimal
    realised_pnl: Decimal


@dataclass(frozen=True, slots=True)
class PortfolioView:
    starting_cash: Decimal
    cash: Decimal
    realised_pnl: Decimal
    unrealised_pnl: Decimal
    total_value: Decimal
    total_pnl: Decimal
    positions: tuple[PositionRow, ...] = ()
    trades: tuple[TradeRow, ...] = ()
    has_marks: bool = False
    any_marks_stale: bool = False
    # display-only GBP conversion inputs
    gbp_rate: Optional[float] = None
    gbp_as_of: str = ""
    gbp_note: str = ""           # degraded copy when stale

    @property
    def is_empty(self) -> bool:
        return len(self.positions) == 0


@dataclass(frozen=True, slots=True)
class ExposureRow:
    symbol: str
    pct: float


@dataclass(frozen=True, slots=True)
class RiskView:
    empty: bool
    warming: bool
    any_stale: bool
    returns_skipped_stale: bool
    timeframe: str
    exp_defined: bool
    exp_abs: Optional[Decimal]
    exp_pct: Optional[float]
    exp_out_of_range: bool
    exp_rows: tuple[ExposureRow, ...] = ()
    vol_defined: bool = False
    vol_period_pct: Optional[float] = None
    vol_annual_pct: Optional[float] = None
    vol_n: int = 0
    dd_defined: bool = False
    dd_pct: float = 0.0
    dd_peak_ts: Optional[float] = None
    dd_trough_ts: Optional[float] = None
    spark: tuple[float, ...] = ()
    spark_trough_idx: Optional[int] = None
    history: tuple[tuple[float, float, bool], ...] = ()   # (ts, value, stale)


VALUE_HISTORY_CSV_HEADER = "ts_iso_utc,ts_epoch,portfolio_value,stale"


def build_value_history_csv(rows: tuple[tuple[float, float, bool], ...]) -> str:
    import datetime as _dt
    lines = [VALUE_HISTORY_CSV_HEADER]
    for ts, value, stale in rows:
        iso = _dt.datetime.fromtimestamp(float(ts), _dt.timezone.utc).isoformat()
        lines.append(f"{iso},{float(ts):.3f},{value!r},{str(bool(stale)).lower()}")
    return "\n".join(lines) + "\n"

@dataclass(frozen=True, slots=True)
class StressRow:
    scenario: str
    start: str
    end: str
    pl_usd: Optional[float] = None        # None = no leg had data
    covered_weight: float = 0.0
    legs_no_data: tuple[str, ...] = ()
    constant_legs: tuple[str, ...] = ()   # legs priced off a constant


@dataclass(frozen=True, slots=True)
class ContributionRow:
    # one position's Euler component VaR
    symbol: str
    weight: float                 # fraction of portfolio value
    pct: float                    # signed share of total risk (sum == 1)
    comp_var_pct: float           # signed component VaR as a loss fraction
    comp_var_usd: float           # signed component VaR in USD


@dataclass(frozen=True, slots=True)
class RiskAnalyticsView:
    available: bool = False
    note: str = ""
    n: int = 0
    window: int = 250
    as_of: str = ""
    excluded: tuple[str, ...] = ()
    coverage_weight: float = 0.0
    portfolio_value: float = 0.0
    var95_pct: Optional[float] = None
    var99_pct: Optional[float] = None
    var95_usd: Optional[float] = None
    var99_usd: Optional[float] = None
    es975_pct: Optional[float] = None
    es975_usd: Optional[float] = None
    pvar95_pct: Optional[float] = None
    pvar99_pct: Optional[float] = None
    backtest_mode: str = ""
    backtest_exceptions: int = 0
    backtest_observations: int = 0
    backtest_zone: str = ""
    accruing_n: int = 0
    kupiec_lr: Optional[float] = None
    kupiec_p: Optional[float] = None
    kupiec_reject: Optional[bool] = None
    beta_spy: Optional[float] = None
    sharpe_annual: Optional[float] = None
    sortino_annual: Optional[float] = None
    rf_annual_pct: Optional[float] = None
    rf_as_of: str = ""
    rf_source: str = ""
    ewma_vol_pct: Optional[float] = None
    corr_symbols: tuple[str, ...] = ()
    corr_matrix: tuple[tuple[Optional[float], ...], ...] = ()
    corr_window: int = 90
    # summary stats for the diversification drill-down
    corr_avg: Optional[float] = None
    corr_max_pair: tuple[str, str, float] | tuple[()] = ()   # (sym_a, sym_b, rho)
    corr_min_pair: tuple[str, str, float] | tuple[()] = ()
    hhi: Optional[float] = None
    effective_n: Optional[float] = None
    top_symbol: str = ""
    top_weight: Optional[float] = None
    sector_hhi: Optional[float] = None
    sector_weights: tuple[tuple[str, float], ...] = ()
    # measured on the value-history series, not on returns
    dd_depth_pct: Optional[float] = None
    dd_duration_periods: Optional[int] = None
    dd_ongoing_periods: Optional[int] = None
    stress: tuple[StressRow, ...] = ()
    comp_confidence: float = 0.95
    comp_sigma_pct: Optional[float] = None    # portfolio sigma_p (fraction)
    comp_var_pct: Optional[float] = None      # z*sigma_p (positive loss fraction)
    comp_var_usd: Optional[float] = None      # z*sigma_p * portfolio value
    contributions: tuple[ContributionRow, ...] = ()
    pnl_total_usd: Optional[float] = None
    pnl_unrealised_usd: Optional[float] = None
    pnl_realised_usd: Optional[float] = None
    pnl_to_var95: Optional[float] = None       # total P&L / 1-day 95% VaR (USD)
    unreal_to_var95: Optional[float] = None    # open P&L / 1-day 95% VaR (USD)
    var_history: tuple[float, ...] = ()
    var_trend: str = ""                        # "rising" | "falling" | "flat"

def analytics_summary(view: RiskAnalyticsView) -> str:
    if view is None or not view.available:
        note = getattr(view, "note", "") if view is not None else ""
        return note or "warming"
    parts = []
    if view.var95_pct is not None:
        parts.append(f"VaR95 {view.var95_pct * 100.0:.1f}%")
    if view.backtest_zone:
        parts.append(f"backtest {view.backtest_zone.upper()}")
    if view.es975_pct is not None:
        parts.append(f"ES {view.es975_pct * 100.0:.1f}%")
    return " · ".join(parts) if parts else "warming"


def backtest_chip_text(view: RiskAnalyticsView) -> str:
    if not view.backtest_zone:
        return "no observations yet"
    head = (f"{view.backtest_zone.upper()} · "
            f"{view.backtest_exceptions} exc / "
            f"{view.backtest_observations}d")
    if view.backtest_mode == "backcast":
        return f"{head} · backcast"
    if view.backtest_mode == "accruing":
        return f"{head} · accruing ({view.accruing_n}/{view.window})"
    return f"{head} · ex-ante"

def build_risk_snapshot_csv(analytics: RiskAnalyticsView,
                            locked: Optional[RiskView] = None,
                            now_iso: str = "") -> str:
    lines = ["metric,value,units,convention,as_of"]

    def row(metric: str, value: object, units: str, convention: str,
            as_of: str = "") -> None:
        if value is None:
            val = ""
        elif isinstance(value, float):
            val = f"{value:.6f}"
        else:
            val = str(value)
        conv = convention.replace('"', "'")
        lines.append(f'{metric},{val},{units},"{conv}",{as_of or now_iso}')

    a = analytics
    if a is not None and a.available:
        base = (f"as-if portfolio returns; {a.n}/{a.window} trading days; "
                "today's weights; adjusted closes; cash earns zero")
        row("var95_hist", a.var95_pct, "fraction",
            "historical order statistic m=floor((1-c)T)+1; " + base, a.as_of)
        row("var99_hist", a.var99_pct, "fraction",
            "historical order statistic; " + base, a.as_of)
        row("es975_hist", a.es975_pct, "fraction",
            "mean of the m worst, tail inclusive (FRTB 97.5); " + base, a.as_of)
        row("var95_parametric", a.pvar95_pct, "fraction",
            "-(mu - z_c sigma), sample sd ddof 1; normality assumed", a.as_of)
        row("var99_parametric", a.pvar99_pct, "fraction",
            "-(mu - z_c sigma), sample sd ddof 1; normality assumed", a.as_of)
        row("backtest_zone", a.backtest_zone or "", "zone",
            f"Basel 99%/250d traffic light; mode {a.backtest_mode}; "
            f"{a.backtest_exceptions} exceptions / {a.backtest_observations} days",
            a.as_of)
        row("kupiec_p", a.kupiec_p, "p-value",
            "POF LR ~ chi-square(1); reject at 5% when LR > 3.8415", a.as_of)
        row("beta_spy", a.beta_spy, "ratio",
            "Cov(r_p, r_b)/Var(r_b) vs SPY; cash damps the portfolio series",
            a.as_of)
        row("sharpe_annual", a.sharpe_annual, "ratio",
            f"mean excess / sd excess (ddof 1) x sqrt(252); rf "
            f"{a.rf_annual_pct if a.rf_annual_pct is not None else 'n/a'}% "
            f"3M par yield as of {a.rf_as_of or 'n/a'}", a.as_of)
        row("sortino_annual", a.sortino_annual, "ratio",
            "FULL-N downside deviation, target 0, x sqrt(252)", a.as_of)
        row("ewma_vol_daily", a.ewma_vol_pct, "percent",
            "RiskMetrics lambda 0.94, seeded with the window variance", a.as_of)
        row("hhi", a.hhi, "index",
            "sum w_i^2 on position weights, cash excluded", a.as_of)
        row("effective_n", a.effective_n, "count", "1/HHI", a.as_of)
        row("dd_depth", a.dd_depth_pct, "percent",
            "worst peak-trough on the value-history series", a.as_of)
        row("component_var95", a.comp_var_pct, "fraction",
            f"parametric Euler component VaR {a.comp_confidence:.0%}, "
            "zero-mean normal; components sum to z*sigma_p", a.as_of)
        for c in a.contributions:
            row(f"contrib_{c.symbol.replace(' ', '_').replace('/', '_')}",
                c.pct, "fraction",
                "share of portfolio risk (signed; a hedge is negative); "
                f"component VaR {c.comp_var_usd:,.0f} USD", a.as_of)
        for s in a.stress:
            row(f"stress_{s.scenario.replace(' ', '_')}", s.pl_usd, "USD",
                f"linear replay {s.start} to {s.end}; covered weight "
                f"{s.covered_weight:.2f}"
                + ("; constant legs: " + " ".join(s.constant_legs)
                   if s.constant_legs else ""), a.as_of)
    if locked is not None and not locked.empty:
        row("exposure_pct", locked.exp_pct, "fraction",
            "positions value / portfolio value; lookback now")
        row("volatility_period", locked.vol_period_pct, "percent",
            f"sample sd over the last <= {locked.vol_n} wall-clock returns; "
            "365-basis annualisation is the labelled wall-clock convention")
        row("max_drawdown", locked.dd_pct, "percent",
            "min(value/running max - 1) since inception")
    return "\r\n".join(lines) + "\r\n"

