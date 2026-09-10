# python -m mahad.report: the book's risk figures from the app's database to a CSV, without Qt
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from mahad import config
from mahad.data.repository import (CONTEXT_KEY, RISK_TIMEFRAME_KEY, SECTORS_KEY,
                                   MahadRepository)
from mahad.data.source import is_crypto_symbol
from mahad.engine import returns as eng_returns
from mahad.engine import risk_metrics as eng_rm
from mahad.engine.risk import (ValueSample, exposure, max_drawdown, simple_returns,
                               volatility)

COLUMNS = ("metric", "value", "unit", "basis", "window", "as_of", "note")
DAILY_BASIS = "as-if daily portfolio returns; today's weights held; adjusted closes; cash earns zero"
MARK_BASIS = "last cached daily close"


class ReportError(Exception):
    # a plain message for the terminal, never a traceback
    pass


@dataclass(frozen=True, slots=True)
class Row:
    metric: str
    value: object
    unit: str
    basis: str
    window: str = ""
    as_of: str = ""
    note: str = ""


def read_only_url(path: Path) -> str:
    return f"sqlite:///file:{path.resolve().as_posix()}?mode=ro&uri=true"


def open_read_only(path: Path) -> MahadRepository:
    # mode=ro keeps the app the single writer; a missing file is an error, never created
    if not path.is_file():
        raise ReportError(f"no database at {path}")
    try:
        return MahadRepository(read_only_url(path))
    except Exception as exc:
        raise ReportError(f"could not open {path} read-only: {exc}") from None


def _window_return(closes: dict[str, list[tuple[_dt.date, float]]], scenario: str,
                   symbol: str, start: str, end: str) -> Optional[tuple[float, str]]:
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


def _sectors(repo: MahadRepository) -> dict[str, str]:
    sectors = dict(config.DEFAULT_SECTOR_MAP)
    cached = repo.get_setting(SECTORS_KEY)
    if isinstance(cached, dict):
        for k, v in cached.items():
            if isinstance(k, str) and isinstance(v, str) and v:
                sectors[k] = v
    return sectors


def _risk_free_annual_pct(repo: MahadRepository) -> Optional[float]:
    # the Treasury 3M par yield the app cached with its context tiles
    cached = repo.get_setting(CONTEXT_KEY)
    yields = cached.get("yields") if isinstance(cached, dict) else None
    y3m = yields.get("y3m") if isinstance(yields, dict) else None
    return float(y3m) if isinstance(y3m, (int, float)) else None


def build_rows(repo: MahadRepository, *, confidence: float = 0.95,
               window: int = config.RISK_WINDOW) -> list[Row]:
    portfolio = repo.get_portfolio()
    if portfolio is None:
        raise ReportError("the database holds no portfolio yet; run the app once first")
    positions = repo.get_positions()
    if not positions:
        raise ReportError("the book holds no positions, so there is nothing to measure")
    cash = float(portfolio.cash)

    symbols = [p.symbol for p in positions]
    if config.BENCHMARK_SYMBOL not in symbols:
        symbols.append(config.BENCHMARK_SYMBOL)
    closes: dict[str, list[tuple[_dt.date, float]]] = {}
    asset_returns: dict[str, list[tuple[_dt.date, float]]] = {}
    last_close: dict[str, tuple[float, _dt.date]] = {}
    for sym in symbols:
        bars = repo.list_daily_bars(sym, limit=config.HISTORY_CAP)
        if not bars:
            continue
        last_close[sym] = (float(bars[-1].close), eng_returns.trading_date(bars[-1].ts))
        aligned = eng_returns.align_daily_closes((b.ts, b.adj_close) for b in bars)
        if aligned:
            closes[sym] = aligned
            daily_rets = eng_returns.simple_returns_by_date(aligned)
            if daily_rets:
                asset_returns[sym] = daily_rets

    marked = [(p.symbol, float(p.quantity), last_close[p.symbol][0])
              for p in positions if p.symbol in last_close]
    unmarked = [p.symbol for p in positions if p.symbol not in last_close]
    weights = eng_returns.current_weights(marked, cash)
    positions_value = sum(q * m for _s, q, m in marked)
    value = cash + positions_value
    as_of = (max(last_close[s][1] for s, _q, _m in marked).isoformat() if marked else "")
    unmarked_note = ("no cached daily close for " + ", ".join(unmarked)) if unmarked else ""

    rows = [
        Row("portfolio_value", value, "USD", f"cash plus positions at the {MARK_BASIS}",
            as_of=as_of, note=unmarked_note),
        Row("cash", cash, "USD", "ledger cash"),
        Row("positions_value", positions_value, "USD", f"quantity x {MARK_BASIS}",
            as_of=as_of, note=unmarked_note),
    ]
    unrealised = 0.0
    for p in positions:
        if p.symbol in last_close:
            mark, mark_date = last_close[p.symbol]
            unrealised += float(p.quantity) * (mark - float(p.avg_cost))
            rows.append(Row(f"mark_{p.symbol}", mark, "USD", MARK_BASIS, as_of=mark_date.isoformat(),
                            note=f"quantity {p.quantity}; average cost {p.avg_cost}"))
        else:
            rows.append(Row(f"mark_{p.symbol}", None, "USD", MARK_BASIS,
                            note=f"quantity {p.quantity}; no cached daily history"))
    exp = exposure(positions_value, value)
    rows.append(Row("exposure_pct", exp.pct, "fraction", "positions value / portfolio value",
                    as_of=as_of))
    realised = float(portfolio.realised_pnl)
    rows.append(Row("pnl_realised_usd", realised, "USD", "sum of the closed trades' realised P&L"))
    rows.append(Row("pnl_unrealised_usd", unrealised, "USD",
                    f"quantity x ({MARK_BASIS} - average cost)", as_of=as_of, note=unmarked_note))
    rows.append(Row("pnl_total_usd", realised + unrealised, "USD", "realised plus unrealised",
                    as_of=as_of))

    # -- the trading-day analytics, the same functions and defaults as the panel -- #
    pr = eng_returns.portfolio_returns(weights, asset_returns, window)
    win = str(window)
    day_as_of = pr.dates[-1].isoformat() if pr.dates else ""
    excluded_note = ("no daily history for " + ", ".join(pr.excluded)) if pr.excluded else ""
    rows.append(Row("observations", pr.n, "days", "common trading days across the held assets",
                    win, day_as_of, excluded_note))
    rows.append(Row("coverage_weight", pr.coverage_weight, "fraction",
                    "weight of the book with usable daily history", win, day_as_of))
    rets = list(pr.returns)
    needs_history = "needs overlapping daily history for the held assets"

    def daily(metric: str, val: object, unit: str, basis: str, note: str = "") -> None:
        rows.append(Row(metric, val, unit, basis, win, day_as_of,
                        note if val is not None else (note or needs_history)))

    var = eng_rm.historical_var(rets, confidence)
    var99 = eng_rm.historical_var(rets, config.BACKTEST_CONFIDENCE)
    es = eng_rm.expected_shortfall(rets, config.ES_CONFIDENCE)
    pvar = eng_rm.parametric_var(rets, confidence)
    pct = f"{confidence:.1%}"
    daily("var_hist", var.value if var else None, "fraction",
          f"historical one-day VaR at {pct}: order statistic m = floor((1 - c)T) + 1; {DAILY_BASIS}")
    daily("var_hist_usd", var.value * value if var else None, "USD", "var_hist x portfolio value")
    daily("var99_hist", var99.value if var99 else None, "fraction",
          f"historical one-day VaR at 99%; {DAILY_BASIS}")
    daily("es975_hist", es.value if es else None, "fraction",
          f"expected shortfall at 97.5%: mean of the m worst returns, tail inclusive; {DAILY_BASIS}")
    daily("es975_hist_usd", es.value * value if es else None, "USD", "es975_hist x portfolio value")
    daily("var_parametric", pvar, "fraction",
          f"-(mu - z_c sigma) at {pct}, sample sd ddof 1; normality assumed")
    ewma = eng_rm.ewma_volatility(rets)
    daily("ewma_vol_daily", ewma * 100.0 if ewma is not None else None, "percent",
          "RiskMetrics lambda 0.94, seeded with the window variance")
    rf_annual = _risk_free_annual_pct(repo)
    rf_daily = eng_returns.rf_daily_from_annual_pct(rf_annual)
    sharpe = eng_rm.sharpe(rets, rf_daily) if rf_daily is not None else None
    daily("sharpe_annual", sharpe.annualised if sharpe else None, "ratio",
          f"mean excess / sd excess (ddof 1) x sqrt(252); rf {rf_annual}% Treasury 3M par yield",
          "" if rf_daily is not None else "needs the Treasury 3M yield the app caches after its first fetch")
    sortino = eng_rm.sortino(rets)
    daily("sortino_annual", sortino.annualised if sortino else None, "ratio",
          "full-N downside deviation, target 0, x sqrt(252)")
    bench = asset_returns.get(config.BENCHMARK_SYMBOL)
    beta = None
    if bench:
        bench_map = dict(bench)
        paired = [(r, bench_map[d]) for d, r in zip(pr.dates, pr.returns, strict=False)
                  if d in bench_map]
        beta = eng_rm.beta([p for p, _b in paired], [b for _p, b in paired])
    daily(f"beta_{config.BENCHMARK_SYMBOL.lower()}", beta, "ratio",
          f"Cov(r_p, r_b) / Var(r_b) against {config.BENCHMARK_SYMBOL} on the common dates",
          "" if bench else f"needs cached {config.BENCHMARK_SYMBOL} daily history")

    held = [s for s, _q, _m in marked]
    corr_in = {s: [r for _d, r in asset_returns[s]] for s in sorted(held) if s in asset_returns}
    summary = None
    if len(corr_in) >= 2:
        corr_symbols, corr_matrix = eng_rm.correlation_matrix(corr_in, config.CORRELATION_WINDOW)
        summary = eng_rm.correlation_summary(corr_symbols, corr_matrix)
    corr_win = str(config.CORRELATION_WINDOW)
    corr_note = "" if summary else "needs daily history for at least two held assets"
    rows.append(Row("corr_avg", summary.avg if summary else None, "rho",
                    "mean off-diagonal Pearson correlation of the held assets", corr_win, day_as_of, corr_note))
    for name, pair in (("corr_max_pair", summary.max_pair if summary else None),
                       ("corr_min_pair", summary.min_pair if summary else None)):
        rows.append(Row(name, pair[2] if pair else None, "rho",
                        f"{pair[0]} and {pair[1]}" if pair else "the most or least correlated pair",
                        corr_win, day_as_of, corr_note))

    sectors = _sectors(repo)
    position_values = {s: q * m for s, q, m in marked}
    conc = eng_rm.concentration(
        position_values,
        {s: ("Crypto" if is_crypto_symbol(s) else sectors.get(s, "Unclassified"))
         for s in position_values}) if position_values else None
    rows.append(Row("hhi", conc.hhi if conc else None, "index",
                    "sum of squared position weights, cash excluded", as_of=as_of))
    rows.append(Row("effective_n", conc.effective_n if conc else None, "count", "1 / HHI", as_of=as_of))
    rows.append(Row("top_weight", conc.top_weight if conc else None, "fraction",
                    f"largest position weight ({conc.top_symbol})" if conc else "largest position weight",
                    as_of=as_of))
    rows.append(Row("sector_hhi", conc.sector_hhi if conc else None, "index",
                    "HHI on sector weights (cached Finnhub sectors, crypto as one sector)", as_of=as_of))

    comp = None
    if pr.n >= 2 and pr.included:
        comp = eng_rm.component_var({s: weights[s] for s in pr.included if s in weights},
                                    pr.aligned, confidence)
    daily("component_var", comp.portfolio_var if comp else None, "fraction",
          f"parametric Euler component VaR at {pct}, zero-mean normal; components sum to z x sigma_p")
    daily("component_var_usd", comp.portfolio_var * value if comp else None, "USD",
          "component_var x portfolio value")
    daily("portfolio_sigma", comp.portfolio_sigma if comp else None, "fraction",
          "sqrt(w^T Sigma w) on the aligned daily returns, sample covariance ddof 1")
    for rc in (comp.contributions if comp else ()):
        daily(f"contrib_{rc.symbol}", rc.pct, "fraction",
              "share of portfolio risk (signed; a hedge is negative)",
              f"component VaR {rc.comp_var * value:,.0f} USD; weight {rc.weight:.4f}")

    # -- the backtest at the Basel window, as the panel runs it -- #
    x, t = repo.backtest_counts(config.RISK_WINDOW)
    mode = "ex-ante" if t >= config.RISK_WINDOW else "accruing"
    bx, bt = x, t
    if t < config.RISK_WINDOW:
        full = eng_returns.portfolio_returns(weights, asset_returns, window=0)
        bc = eng_rm.backcast_exceptions(list(full.returns), config.BACKTEST_CONFIDENCE,
                                        config.RISK_WINDOW)
        if bc is not None and bc.observations > 0:
            mode, bx, bt = "backcast", bc.exceptions, bc.observations
    basel = str(config.RISK_WINDOW)
    bt_basis = f"{mode}: 99% one-day VaR against realised returns"
    bt_note = ("" if bt > 0 else "no observations yet: the app logs one forecast per day, "
               "or backcasts once the cached history exceeds the window")
    rows.append(Row("backtest_exceptions", bx, "count", bt_basis, basel, day_as_of, bt_note))
    rows.append(Row("backtest_observations", bt, "days", bt_basis, basel, day_as_of, bt_note))
    rows.append(Row("backtest_zone", eng_rm.basel_zone(bx) if bt > 0 else None, "zone",
                    "Basel traffic light: green 0-4, yellow 5-9, red 10+ exceptions", basel, day_as_of, bt_note))
    kup = eng_rm.kupiec_pof(bx, bt, 1.0 - config.BACKTEST_CONFIDENCE) if bt > 0 else None
    rows.append(Row("kupiec_lr", kup.lr if kup else None, "statistic",
                    "proportion-of-failures likelihood ratio, chi-square(1)", basel, day_as_of, bt_note))
    rows.append(Row("kupiec_p", kup.p_value if kup else None, "p-value",
                    "reject coverage at 5% when LR > 3.8415", basel, day_as_of, bt_note))
    rows.append(Row("kupiec_reject", kup.reject if kup else None, "flag",
                    "true when the Kupiec test rejects", basel, day_as_of, bt_note))

    for name, start, end in config.STRESS_SCENARIOS:
        window_returns: dict[str, tuple[float, str]] = {}
        for sym in weights:
            entry = _window_return(closes, name, sym, start, end)
            if entry is not None:
                window_returns[sym] = entry
        res = eng_rm.stress_replay(name, start, end, value, weights, window_returns)
        no_data = [leg.symbol for leg in res.legs if leg.window_return is None]
        constant = [leg.symbol for leg in res.legs if leg.source == "constant"]
        note = "; ".join(part for part in (
            ("constant legs: " + ", ".join(constant)) if constant else "",
            ("no data for " + ", ".join(no_data)) if no_data else "") if part)
        rows.append(Row(f"stress_{name.replace(' ', '_')}", res.pl_usd, "USD",
                        f"linear replay {start} to {end}; covered weight {res.covered_weight:.2f}",
                        as_of=as_of, note=note))

    rows.append(Row("pnl_to_var", eng_rm.return_on_risk(realised + unrealised,
                                                        var.value * value if var else None),
                    "ratio", "total P&L / one-day VaR in USD", win, day_as_of,
                    "" if var else needs_history))

    # -- the value-history metrics, wall-clock basis -- #
    samples = [ValueSample(ts=v.ts, value=float(v.portfolio_value), stale=bool(v.stale))
               for v in repo.list_value_history()]
    timeframe = config.valid_risk_timeframe(repo.get_setting(RISK_TIMEFRAME_KEY))
    vh_returns, _skipped = simple_returns(samples)
    vol = volatility(vh_returns, timeframe, window=config.VOLATILITY_WINDOW)
    peak = repo.get_peak()
    peak_v: Optional[float] = None
    peak_ts: Optional[float] = None
    if (peak.peak_value is not None and peak.peak_ts is not None
            and samples and peak.peak_ts <= samples[0].ts):
        peak_v, peak_ts = float(peak.peak_value), peak.peak_ts
    dd = max_drawdown(samples, peak_value=peak_v, peak_ts=peak_ts)
    vh_as_of = (_dt.datetime.fromtimestamp(samples[-1].ts, _dt.UTC).date().isoformat()
                if samples else "")
    vh_note = "" if vol.defined else "needs at least two value-history samples"
    rows.append(Row("value_samples", len(samples), "count",
                    f"portfolio value sampled every {timeframe} while the app runs", as_of=vh_as_of))
    rows.append(Row("volatility_period_pct", vol.per_period_pct, "percent",
                    f"sample sd (ddof 1) of the {timeframe} value-history returns",
                    str(config.VOLATILITY_WINDOW), vh_as_of, vh_note))
    rows.append(Row("volatility_annual_pct", vol.annualised_pct, "percent",
                    "wall-clock annualisation: sigma x sqrt(periods per calendar year)",
                    str(config.VOLATILITY_WINDOW), vh_as_of, vh_note))
    rows.append(Row("max_drawdown_pct", dd.max_dd_pct if dd.defined else None, "percent",
                    "min(value / running max - 1) on the value history, running max seeded at the persisted peak",
                    as_of=vh_as_of, note="" if dd.defined else "needs value-history samples"))
    duration = eng_rm.drawdown_duration([s.value for s in samples])
    rows.append(Row("drawdown_duration_periods", duration.duration_periods if duration else None,
                    "periods", "peak to recovery on the value history", as_of=vh_as_of,
                    note=("ongoing" if duration and duration.duration_periods is None
                          else "" if duration else "needs value-history samples")))
    return rows


def _cell(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float):
        return f"{value:.6f}"
    return str(value)


def write_csv(rows: Sequence[Row], path: Path) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for r in rows:
            writer.writerow((r.metric, _cell(r.value), r.unit, r.basis, r.window, r.as_of, r.note))


def _summary(rows: Sequence[Row], out: Path) -> str:
    by = {r.metric: r for r in rows}

    def show(metric: str, fmt: str) -> str:
        row = by[metric]
        return format(row.value, fmt) if row.value is not None else f"n/a ({row.note})"

    return "\n".join((
        f"MAHAD risk report, book as of {by['portfolio_value'].as_of or 'n/a'}",
        f"portfolio value {show('portfolio_value', ',.2f')} USD, cash {show('cash', ',.2f')} USD",
        f"one-day VaR {show('var_hist', '.4%')} ({show('var_hist_usd', ',.0f')} USD), "
        f"ES 97.5% {show('es975_hist', '.4%')}, {by['observations'].value}/{by['observations'].window} days",
        f"backtest {show('backtest_zone', '')} ({by['backtest_exceptions'].value} exceptions "
        f"in {by['backtest_observations'].value} days)",
        f"value-history volatility {show('volatility_period_pct', '.3f')}% per period, "
        f"max drawdown {show('max_drawdown_pct', '.2f')}%",
        f"{len(rows)} rows written to {out}",
    ))


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m mahad.report",
        description="Write the simulated book's risk figures to a CSV, read from the app's "
                    "own database in read-only mode. The app may be running or closed.")
    parser.add_argument("--db", type=Path, default=config.data_dir() / config.DB_FILENAME,
                        help="the SQLite database to read (default: the app's own, %(default)s)")
    parser.add_argument("--out", type=Path, default=None,
                        help="the CSV to write (default: mahad-risk-report-<date>.csv here)")
    parser.add_argument("--confidence", type=float, default=0.95,
                        help="VaR confidence as a fraction (default %(default)s); the 99%% "
                             "backtest and the 97.5%% expected shortfall stay fixed")
    parser.add_argument("--window", type=int, default=config.RISK_WINDOW,
                        help="trading days in the analytics window (default %(default)s)")
    args = parser.parse_args(argv)
    if not 0.0 < args.confidence < 1.0:
        parser.error("--confidence must lie strictly between 0 and 1")
    if args.window < 2:
        parser.error("--window must be at least 2 trading days")
    out = args.out or Path(f"mahad-risk-report-{_dt.date.today().isoformat()}.csv")
    try:
        repo = open_read_only(args.db)
        try:
            rows = build_rows(repo, confidence=args.confidence, window=args.window)
        finally:
            repo.close()
        write_csv(rows, out)
    except ReportError as exc:
        print(f"report not written: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"report not written: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(_summary(rows, out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
