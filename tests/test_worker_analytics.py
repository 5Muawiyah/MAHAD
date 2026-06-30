# Worker-assembly tests: how PollWorker builds the RiskAnalyticsView, the
# backtest accrual, and stress legs. Headless, tmp_path DBs, no network.
from __future__ import annotations

import datetime as dt
import time
from dataclasses import dataclass
from decimal import Decimal

import pytest

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.data.models import Quote
from mahad.engine.portfolio import PortfolioState, Position as EngPosition
from mahad.worker import PollWorker


@dataclass(frozen=True)
class _Bar:
    ts: float
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


def _trading_bars(start: dt.date, closes, adj_offset=0.0):
    # consecutive US trading days; a nonzero adj_offset proves which column the engine reads
    from mahad.engine.returns import is_us_trading_day
    out = []
    d = start
    i = 0
    while i < len(closes):
        if is_us_trading_day(d):
            ts = dt.datetime(d.year, d.month, d.day,
                             tzinfo=dt.timezone.utc).timestamp()
            c = closes[i]
            out.append(_Bar(ts=ts, open=c, high=c + 1, low=c - 1, close=c,
                            adj_close=c + adj_offset, volume=1e6,
                            div_cash=0.0, split_factor=1.0))
            i += 1
        d += dt.timedelta(days=1)
    return out


def _worker(tmp_path, name="a.db"):
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / name}")
    w._open_repo()
    w._load_portfolio()
    w._load_sectors()
    w._wallclock = lambda: 1000.0
    return w


def _hold(w, *symbol_qty_mark):
    positions = []
    for sym, qty, mark in symbol_qty_mark:
        positions.append(EngPosition(sym, Decimal(str(qty)), Decimal("1")))
        w._marks[sym] = Quote(sym, float(mark), time.time(), "test")
    w._portfolio = PortfolioState(cash=Decimal("1000"),
                                  realised_pnl=Decimal("0"),
                                  positions=tuple(positions))


# --------------------------------------------------------------------------- #
# View assembly: adjusted closes, gates, notes
# --------------------------------------------------------------------------- #
def test_asset_returns_consume_the_adjusted_close_column(tmp_path):
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    bars = _trading_bars(dt.date(2026, 5, 4), [100.0, 110.0], adj_offset=100.0)
    w._repo.upsert_daily_bars("AAPL", bars)
    _hold(w, ("AAPL", 1, 110.0))
    w._build_asset_data()
    (d1, r1), = w._asset_returns["AAPL"]
    assert r1 == pytest.approx(210.0 / 200.0 - 1.0)       # adjusted, NOT 10%
    assert w._asset_closes["AAPL"][0][1] == pytest.approx(200.0)


def test_view_gates_on_n_not_coverage(tmp_path):
    # disjoint histories: full included weight but n == 0, so still unavailable
    w = _worker(tmp_path)
    for sym in ("AAPL", "MSFT"):
        w._repo.add(sym, "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _trading_bars(dt.date(2026, 1, 5),
                                                    [100, 101, 102]))
    w._repo.upsert_daily_bars("MSFT", _trading_bars(dt.date(2026, 3, 2),
                                                    [50, 51, 52]))
    _hold(w, ("AAPL", 1, 102.0), ("MSFT", 1, 52.0))
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.available is False
    assert "warming" in view.note


def test_view_names_the_tiingo_key_when_stock_history_is_keyless(tmp_path):
    class _Keyless:
        history_needs_key = True
        needs_key = False
    w = _worker(tmp_path)
    w._adapters = {"stock:active": _Keyless(), "stock:held": _Keyless()}
    _hold(w, ("AAPL", 1, 100.0))
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.available is False
    assert "tiingo.com" in view.note


def test_no_positions_view_is_unavailable(tmp_path):
    w = _worker(tmp_path)
    view = w._build_analytics_view()
    assert view.available is False and view.note == "no positions"


def test_full_view_assembles_with_benchmark_and_sectors(tmp_path):
    w = _worker(tmp_path)
    for sym in ("AAPL", "SPY"):
        w._repo.add(sym, "stock", "USD", "finnhub") if sym == "AAPL" else \
            w._repo.ensure_symbol(sym, "stock", "USD", "finnhub")
    closes = [100.0, 101.0, 99.5, 102.0, 103.0, 101.5, 104.0, 105.0,
              103.5, 106.0]
    w._repo.upsert_daily_bars("AAPL", _trading_bars(dt.date(2026, 5, 4), closes))
    w._repo.upsert_daily_bars("SPY", _trading_bars(
        dt.date(2026, 5, 4), [c * 5 for c in closes]))
    _hold(w, ("AAPL", 10, 106.0))
    w._ctx_yields = w._yields_tile({"as_of": "2026-06-10", "y3m": 4.20,
                                    "y2y": 4.0, "y10y": 4.4, "y30y": 4.8},
                                   fetched_ts=999.0)
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.available and view.n == 9
    assert view.var95_pct is not None and view.var99_pct is not None
    assert view.es975_pct >= view.var95_pct               # tail dominance
    assert view.var95_usd == pytest.approx(view.var95_pct * view.portfolio_value)
    # AAPL and SPY move identically but cash (zero return) damps the portfolio
    # series, so beta lands exactly on the invested weight
    assert view.beta_spy == pytest.approx(view.coverage_weight, abs=1e-9)
    assert view.rf_annual_pct == pytest.approx(4.20)
    assert view.rf_source == "US Treasury 3M par yield"
    assert view.sharpe_annual is not None
    assert view.ewma_vol_pct is not None and view.ewma_vol_pct > 0
    assert view.hhi == pytest.approx(1.0)                 # single position
    assert view.top_symbol == "AAPL"
    assert view.sector_weights[0][0] == "Technology"
    assert view.as_of == "2026-05-15"                     # the 10th trading day


def test_keyless_rf_leaves_sharpe_absent_but_view_available(tmp_path):
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _trading_bars(
        dt.date(2026, 5, 4), [100.0, 101.0, 99.5, 102.0]))
    _hold(w, ("AAPL", 1, 102.0))
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.available
    assert view.sharpe_annual is None and view.rf_source == ""
    assert view.sortino_annual is not None                # rf-free metric


# --------------------------------------------------------------------------- #
# Backtest: persistence round-trip + ex-ante accrual
# --------------------------------------------------------------------------- #
def test_backtest_persistence_round_trip(tmp_path):
    w = _worker(tmp_path)
    repo = w._repo
    repo.upsert_backtest_forecast(1000.0, 0.025, {"AAPL": 0.6})
    repo.upsert_backtest_forecast(1000.0, 0.030, {"AAPL": 0.7})   # unresolved: updates
    rows = repo.open_backtest_rows()
    assert len(rows) == 1 and rows[0].var99_pct == 0.030
    assert rows[0].weights == {"AAPL": 0.7}
    assert repo.resolve_backtest_row(1000.0, -0.04, True, 2000.0) is True
    assert repo.resolve_backtest_row(1000.0, -0.01, False, 3000.0) is False  # immutable
    repo.upsert_backtest_forecast(1000.0, 0.999, {"X": 1.0})      # resolved: ignored
    assert repo.open_backtest_rows() == []
    assert repo.backtest_counts() == (1, 1)


def test_accrual_resolves_with_the_prior_days_weights(tmp_path):
    # var99 sits between the stored-weights loss and the current-weights loss,
    # so a current-weights mutant would flip the exception flag
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    closes = [100.0, 101.0, 99.5, 102.0, 100.0]        # last day: -1.96%
    w._repo.upsert_daily_bars("AAPL", _trading_bars(dt.date(2026, 5, 4), closes))
    _hold(w, ("AAPL", 1, 100.0))                       # current weight ~ 0.0909
    w._build_asset_data()
    grid = [d for d, _ in w._asset_returns["AAPL"]]
    last_r = w._asset_returns["AAPL"][-1][1]           # -0.019608
    prior_day = grid[-2]
    prior_ts = dt.datetime(prior_day.year, prior_day.month, prior_day.day,
                           tzinfo=dt.timezone.utc).timestamp()
    # stored weights 0.5 -> realised -0.98%; current ~0.09 -> -0.18%.
    # var99 = 0.5% sits between: only the stored-weights path excepts.
    w._repo.upsert_backtest_forecast(prior_ts, 0.005, {"AAPL": 0.5})
    w._accrue_backtest()
    x, t = w._repo.backtest_counts()
    assert (x, t) == (1, 1)                            # the stored-weights flag
    realised = w._repo.list_resolved_backtest_rows()[-1]
    assert realised.realised_pct == pytest.approx(0.5 * last_r, abs=1e-12)
    assert realised.exception is True
    # and today's forecast was recorded with today's weights
    open_rows = w._repo.open_backtest_rows()
    assert len(open_rows) == 1
    assert open_rows[0].weights["AAPL"] == pytest.approx(
        w._current_weights_and_value()[0]["AAPL"])


def test_accrual_is_idempotent_per_day(tmp_path):
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _trading_bars(
        dt.date(2026, 5, 4), [100.0, 101.0, 99.5, 102.0]))
    _hold(w, ("AAPL", 1, 102.0))
    w._build_asset_data()
    w._accrue_backtest()
    w._accrue_backtest()                                   # same day again
    assert len(w._repo.open_backtest_rows()) == 1          # one forecast row
    assert w._repo.backtest_counts() == (0, 0)             # nothing double-resolved


def test_backtest_mode_labels(tmp_path):
    # few resolved rows + a long series -> backcast label
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    import random
    rng = random.Random(7)
    closes = [100.0]
    for _ in range(300):
        closes.append(max(1.0, closes[-1] * (1.0 + rng.uniform(-0.02, 0.02))))
    w._repo.upsert_daily_bars("AAPL", _trading_bars(dt.date(2025, 1, 6), closes))
    _hold(w, ("AAPL", 1, closes[-1]))
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.backtest_mode == "backcast"
    assert view.backtest_observations > 0
    assert view.backtest_zone in ("green", "yellow", "red")
    assert view.accruing_n == 0


def test_accrual_resolves_on_the_forecasts_own_next_day(tmp_path):
    # a late-joining position must not drag an old forecast onto a later day
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.add("MSFT", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _trading_bars(
        dt.date(2026, 5, 4), [100.0, 101.0, 99.5, 102.0, 103.0, 101.0]))
    # MSFT history starts LATE - the intersection grid narrows
    w._repo.upsert_daily_bars("MSFT", _trading_bars(
        dt.date(2026, 5, 11), [50.0, 51.0]))
    _hold(w, ("AAPL", 1, 101.0), ("MSFT", 1, 51.0))
    w._build_asset_data()
    aapl = dict(w._asset_returns["AAPL"])
    f_day = dt.date(2026, 5, 5)                        # an early AAPL-book forecast
    f_ts = dt.datetime(2026, 5, 5, tzinfo=dt.timezone.utc).timestamp()
    w._repo.upsert_backtest_forecast(f_ts, 0.001, {"AAPL": 1.0})
    w._accrue_backtest()
    resolved = w._repo.list_resolved_backtest_rows()
    assert len(resolved) == 1
    true_next = min(d for d in aapl if d > f_day)      # 2026-05-06
    assert resolved[0].realised_pct == pytest.approx(aapl[true_next], abs=1e-12)


def test_reset_clears_the_backtest_series(tmp_path):
    w = _worker(tmp_path)
    repo = w._repo
    repo.upsert_backtest_forecast(1000.0, 0.02, {"AAPL": 0.5})
    repo.resolve_backtest_row(1000.0, -0.05, True, 2000.0)
    repo.upsert_backtest_forecast(3000.0, 0.02, {"AAPL": 0.5})   # open
    assert repo.backtest_counts() == (1, 1)
    repo.reset_portfolio("100000")
    assert repo.backtest_counts() == (0, 0)
    assert repo.open_backtest_rows() == []


def test_ex_ante_label_takes_over_at_the_window(tmp_path):
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _trading_bars(
        dt.date(2026, 5, 4), [100.0, 101.0, 99.5, 102.0]))
    _hold(w, ("AAPL", 1, 102.0))
    # plant >= RISK_WINDOW resolved rows
    from mahad import config as _cfg
    for i in range(_cfg.RISK_WINDOW):
        ts = 1000.0 + i
        w._repo.upsert_backtest_forecast(ts, 0.02, {"AAPL": 0.5})
        w._repo.resolve_backtest_row(ts, -0.001, False, ts + 1.0)
    w._build_asset_data()
    view = w._build_analytics_view()
    assert view.backtest_mode == "ex-ante"
    assert view.accruing_n >= _cfg.RISK_WINDOW


# --------------------------------------------------------------------------- #
# Stress: cache vs constant vs no-data
# --------------------------------------------------------------------------- #
def test_stress_leg_resolution_priority(tmp_path):
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    # cache covering the FTX window exactly
    w._asset_closes = {"AAPL": [
        (dt.date(2022, 11, 4), 138.38), (dt.date(2022, 11, 7), 138.92),
        (dt.date(2022, 11, 14), 148.28)]}
    _hold(w, ("AAPL", 1, 148.0), ("BTC/USD", 1, 70000.0), ("ZZZ", 1, 5.0))
    weights, value = w._current_weights_and_value()
    rows = {r.scenario: r for r in w._stress_rows(weights, value)}
    ftx = rows["FTX week"]
    assert "AAPL" not in ftx.constant_legs                 # cache won
    assert "BTC/USD" in ftx.constant_legs                  # the cited constant
    assert "ZZZ" in ftx.legs_no_data                       # honest no-data
    assert ftx.pl_usd is not None
    covid = rows["COVID crash"]
    assert "AAPL" in covid.constant_legs                   # cache does not reach 2020
