# Caps and big-but-bounded workloads. Budgets are loose upper bounds (CI-safe);
# the perf suite records the real numbers.
from __future__ import annotations

import time
import tracemalloc
from collections import deque
from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Candle, Quote
from mahad.data.repository import MahadRepository
from mahad.data.source import normalize_ohlcv
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.portfolio import (BUY, SELL, PortfolioState, build_trade_csv,
                                    place_order, reconstruct_cash,
                                    reconstruct_realised, record_from_fill)
from mahad.engine.risk import ValueSample, max_drawdown, simple_returns, volatility
from mahad.engine.signals import AlertSpec, evaluate_alert
from mahad.engine.snapshot import build_render_snapshot
from mahad.worker import PollWorker


def _candles(n: int, tf="1d") -> list[Candle]:
    step = 86400 if tf == "1d" else 60
    return [Candle("AAPL", tf, 1_700_000_000 + i * step, 1, 2, 0.5,
                   100 + (i % 37) * 0.5, 1e6, True) for i in range(n)]


def test_history_cap_enforced_on_hostile_input():
    rows = [(1_700_000_000 + i * 60, 1, 2, 0.5, 1.5, 10) for i in range(5000)]
    candles = normalize_ohlcv("A", "1m", rows, history_cap=config.HISTORY_CAP)
    assert len(candles) == config.HISTORY_CAP
    assert candles[0].ts == rows[-config.HISTORY_CAP][0]    # most-recent kept


def test_render_cap_bounds_snapshot():
    snap = build_render_snapshot(_candles(500), None, render_cap=config.RENDER_CAP)
    assert len(snap.points) <= config.RENDER_CAP


def test_value_history_cap_pruned_in_db(tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'vh.db'}")
    repo.load_or_create_portfolio("100000")
    cap = 50
    for i in range(cap + 25):
        repo.append_value_history(ts=1_700_000_000 + i, portfolio_value=100000 + i,
                                  cash=100000, positions_value=i, stale=False, cap=cap)
    assert repo.count_value_history() == cap
    samples = repo.list_value_history()
    assert samples[0].ts == 1_700_000_000 + 25              # oldest pruned
    repo.close()


def test_alert_cap_enforced(tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'al.db'}")
    repo.add("AAPL", "stock", "USD", "finnhub")
    for i in range(20):
        alert, reason = repo.add_alert("AAPL", "price_threshold",
                                       {"level": float(i + 1)}, "up")
        assert alert is not None, reason
    alert, reason = repo.add_alert("AAPL", "price_threshold", {"level": 999.0}, "up")
    assert alert is None and "capped at 20" in reason
    repo.close()


def test_watchlist_cap_via_worker(tmp_path):
    w = PollWorker(symbol=None, db_url=f"sqlite:///{tmp_path / 'wl.db'}")
    w._open_repo()
    w._probe_symbol = lambda sym: (True, "")   # cap is the subject; the
    # existence probe is exercised in test_validate_add_probe.py (no network here)
    for i in range(25):                                     # 5 beyond the cap
        w.add_symbol(f"SYM{i}")
        w._reload_watchlist()
    assert len(w._watchlist_symbols()) == config.WATCHLIST_CAP
    rejected = [e for e in w.add_rejected.emissions if "full" in e[1]]
    assert rejected, "the 21st add must be rejected with the cap message"
    w.stop()


# --------------------------------------------------------------------------- #
# Many trades: ledger exactness + CSV at scale + snapshot cost
# --------------------------------------------------------------------------- #
def test_thousand_trades_ledger_exact(tmp_path):
    state = PortfolioState(cash=Decimal("1000000"), realised_pnl=Decimal("0"))
    records = []
    mark = Decimal("10")
    for i in range(500):
        r = place_order(state, BUY, "AAPL", "3", mark)
        assert r.ok
        state = r.state
        records.append(record_from_fill(r.fill, 1_700_000_000 + i))
        r = place_order(state, SELL, "AAPL", "2", mark + Decimal("0.37"))
        assert r.ok
        state = r.state
        records.append(record_from_fill(r.fill, 1_700_000_000 + i + 0.5))
    assert state.cash == reconstruct_cash(records, "1000000")
    assert state.realised_pnl == reconstruct_realised(records)
    assert state.cash >= 0
    csv_text = build_trade_csv(records, "1000000")
    assert csv_text.count("\n") == 1002                     # preamble + header + 1000 rows


def test_snapshot_with_thousand_trades_portfolio_view(tmp_path):
    # worker attaches the full trade list to every snapshot; at 1000 trades the
    # build must stay inside the compute budget
    w = PollWorker(symbol="AAPL", db_url=f"sqlite:///{tmp_path / 'pv.db'}")
    w._open_repo()
    w._load_portfolio()
    from mahad.data.repository import PersistedTrade
    one = Decimal("1")
    w._trades = [PersistedTrade(ts=float(i), symbol="AAPL", side="buy", quantity=one,
                                fill_price=Decimal("10"), avg_cost_at_fill=Decimal("10"),
                                qty_before=Decimal(i), qty_after=Decimal(i + 1),
                                realised_pnl=Decimal("0")) for i in range(1000)]
    t0 = time.perf_counter()
    for _ in range(10):
        view = w._build_portfolio_view()
    dt = (time.perf_counter() - t0) / 10
    assert len(view.trades) == 1000
    assert dt < 0.25, f"portfolio view at 1000 trades took {dt*1000:.1f} ms"
    w.stop()


# --------------------------------------------------------------------------- #
# Fast cadence / rapid polls: bounded memory and steady cost
# --------------------------------------------------------------------------- #
def test_ten_k_value_samples_bounded_deque_and_risk():
    dq: deque = deque(maxlen=config.VALUE_HISTORY_CAP)
    t0 = time.perf_counter()
    for i in range(10_000):
        dq.append(ValueSample(ts=float(i), value=100000.0 + (i % 211), stale=(i % 97 == 0)))
        if i % 100 == 0:
            returns, _ = simple_returns(list(dq))
            volatility(returns, "1m", window=config.VOLATILITY_WINDOW)
            max_drawdown(list(dq), peak_value=100211.0, peak_ts=0.0)
    dt = time.perf_counter() - t0
    assert len(dq) == config.VALUE_HISTORY_CAP
    assert dt < 30.0, f"10k-sample risk loop took {dt:.1f}s"


def test_thousand_snapshot_cycles_no_growth():
    candles = _candles(config.HISTORY_CAP)
    quote = Quote("AAPL", 105.0, time.time(), "finnhub", False)
    settings = IndicatorSettings(sma_enabled=True, sma_period=20,
                                 ema_enabled=True, ema_period=12,
                                 rsi_enabled=True, rsi_period=14)
    spec = AlertSpec(id=1, symbol="AAPL", condition_type="price_threshold",
                     params={"level": 1e9}, direction="up")
    closes = [c.close for c in candles]
    ts = [c.ts for c in candles]

    def cycle():
        build_render_snapshot(candles, quote, settings=settings)
        evaluate_alert(spec, closed_closes=closes, closed_ts=ts, mark=105.0,
                       timeframe="1d", new_indices=[len(closes) - 1], now=time.time())

    for _ in range(50):
        cycle()                                             # warm-up
    tracemalloc.start()
    first = tracemalloc.take_snapshot()
    for _ in range(1000):
        cycle()
    second = tracemalloc.take_snapshot()
    tracemalloc.stop()
    growth = sum(s.size_diff for s in second.compare_to(first, "filename"))
    assert growth < 8 * 1024 * 1024, f"snapshot loop grew {growth/1048576:.1f} MiB"


def test_twenty_armed_alerts_evaluate_quickly():
    candles = _candles(config.HISTORY_CAP)
    closes = [c.close for c in candles]
    ts = [c.ts for c in candles]
    specs = [AlertSpec(id=i, symbol="AAPL",
                       condition_type="sma_ema_cross" if i % 2 else "price_sma_cross",
                       params={"sma_period": 20, "ema_period": 12} if i % 2
                       else {"sma_period": 20},
                       direction="up" if i % 3 else "down")
             for i in range(20)]
    t0 = time.perf_counter()
    for spec in specs:
        evaluate_alert(spec, closed_closes=closes, closed_ts=ts, mark=105.0,
                       timeframe="1d", new_indices=[len(closes) - 1], now=0.0)
    dt = time.perf_counter() - t0
    assert dt < 2.0, f"20 alerts on 500 bars took {dt*1000:.0f} ms"
