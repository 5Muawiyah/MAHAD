"""Performance benchmarks - pytest-benchmark.

Compute-side timing of the latency targets. Asserted budgets are loose
(CI-safe); the harness records the real medians from --benchmark-json. Run via:
    python -m pytest tests/test_perf.py --benchmark-only
Excluded from the coverage step. Headless, Qt-free, tmp DBs.
"""
from __future__ import annotations

import time
from decimal import Decimal

import pytest

pytest.importorskip("pytest_benchmark")

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Candle, Quote
from mahad.data.repository import MahadRepository, PersistedTrade
from mahad.engine.indicators import IndicatorSettings, ema, sma, wilder_rsi
from mahad.engine.risk import ValueSample, max_drawdown, simple_returns, volatility
from mahad.engine.signals import AlertSpec, evaluate_alert
from mahad.engine.snapshot import build_render_snapshot
from mahad.worker import PollWorker

N = config.HISTORY_CAP                            # 500 bars
CANDLES = [Candle("AAPL", "1d", 1_700_000_000 + i * 86400, 1, 2, 0.5,
                  100 + (i % 37) * 0.5, 1e6, True) for i in range(N)]
CLOSES = [c.close for c in CANDLES]
TS = [c.ts for c in CANDLES]
QUOTE = Quote("AAPL", 105.0, time.time(), "finnhub", False)
SETTINGS = IndicatorSettings(sma_enabled=True, sma_period=20,
                             ema_enabled=True, ema_period=12,
                             rsi_enabled=True, rsi_period=14)
SAMPLES = [ValueSample(ts=float(i), value=100000.0 + (i % 211), stale=(i % 97 == 0))
           for i in range(config.VALUE_HISTORY_CAP)]


def test_sma_500(benchmark):
    out = benchmark(lambda: sma(CLOSES, 20))
    assert len(out) == N
    assert benchmark.stats.stats.median < 0.05            # 50 ms loose bound


def test_ema_500(benchmark):
    benchmark(lambda: ema(CLOSES, 12))
    assert benchmark.stats.stats.median < 0.05


def test_rsi_500(benchmark):
    benchmark(lambda: wilder_rsi(CLOSES, 14))
    assert benchmark.stats.stats.median < 0.05


def test_snapshot_build_500_three_indicators(benchmark):
    snap = benchmark(lambda: build_render_snapshot(CANDLES, QUOTE, settings=SETTINGS))
    assert snap.has_data
    assert benchmark.stats.stats.median < 0.25            # compute side of the render budget


def test_signals_twenty_alerts(benchmark):
    specs = [AlertSpec(id=i, symbol="AAPL",
                       condition_type="sma_ema_cross" if i % 2 else "rsi_threshold",
                       params=({"sma_period": 20, "ema_period": 12} if i % 2
                               else {"level": 50.0, "rsi_period": 14}),
                       direction="up") for i in range(20)]

    def run():
        for s in specs:
            evaluate_alert(s, closed_closes=CLOSES, closed_ts=TS, mark=105.0,
                           timeframe="1d", new_indices=[N - 1], now=0.0)
    benchmark(run)
    assert benchmark.stats.stats.median < 0.25


def test_risk_compute_1000_samples(benchmark):
    def run():
        returns, _ = simple_returns(SAMPLES)
        volatility(returns, "1m", window=30)
        max_drawdown(SAMPLES, peak_value=100211.0, peak_ts=0.0)
    benchmark(run)
    assert benchmark.stats.stats.median < 0.05


def test_portfolio_view_1000_trades(benchmark, tmp_path):
    """The portfolio-view rebuild path - must be measurable."""
    w = PollWorker(symbol="AAPL", db_url=f"sqlite:///{tmp_path / 'b.db'}")
    w._open_repo()
    w._load_portfolio()
    one = Decimal("1")
    w._trades = [PersistedTrade(ts=float(i), symbol="AAPL", side="buy", quantity=one,
                                fill_price=Decimal("10"), avg_cost_at_fill=Decimal("10"),
                                qty_before=Decimal(i), qty_after=Decimal(i + 1),
                                realised_pnl=Decimal("0")) for i in range(1000)]
    view = benchmark(w._build_portfolio_view)
    assert len(view.trades) == 1000
    assert benchmark.stats.stats.median < 0.25
    w.stop()


def test_record_fill_sqlite(benchmark, tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'f.db'}")
    repo.load_or_create_portfolio("100000")
    repo.add("AAPL", "stock", "USD", "finnhub")
    one = Decimal("1")
    i = [0]

    def run():
        i[0] += 1
        repo.record_fill(
            cash=Decimal("90000"), realised_pnl=Decimal("0"), symbol="AAPL",
            new_quantity=Decimal(i[0]), new_avg_cost=Decimal("10"),
            trade=PersistedTrade(ts=float(i[0]), symbol="AAPL", side="buy",
                                 quantity=one, fill_price=Decimal("10"),
                                 avg_cost_at_fill=Decimal("10"),
                                 qty_before=Decimal(i[0] - 1), qty_after=Decimal(i[0]),
                                 realised_pnl=Decimal("0")))
    benchmark(run)
    assert benchmark.stats.stats.median < 0.5             # one WAL commit
    repo.close()


def test_append_value_history_at_cap(benchmark, tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'v.db'}")
    repo.load_or_create_portfolio("100000")
    cap = 1000
    for i in range(cap):                                   # pre-fill to the cap
        repo.append_value_history(ts=float(i), portfolio_value=100000, cash=100000,
                                  positions_value=0, stale=False, cap=cap)
    i = [cap]

    def run():
        i[0] += 1
        repo.append_value_history(ts=float(i[0]), portfolio_value=100000,
                                  cash=100000, positions_value=0, stale=False,
                                  cap=cap)
    benchmark(run)
    assert benchmark.stats.stats.median < 0.5             # append + prune commit
    repo.close()
