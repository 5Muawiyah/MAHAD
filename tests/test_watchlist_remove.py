from __future__ import annotations

import time
from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.data.models import Quote
from mahad.data.source import FetchResult, normalize_ohlcv
from mahad.engine.portfolio import PortfolioState, Position as EngPosition
from mahad.worker import PollWorker


class _Src:
    def fetch(self, symbol, timeframe):
        t0 = time.time() - 10 * 3600
        rows = [(t0 + i * 3600, 10, 11, 9, 10.5, 1.0) for i in range(10)]
        c = normalize_ohlcv(symbol, timeframe, rows, 500)
        return FetchResult(symbol, timeframe, quote=Quote(symbol, 10.5, time.time(),
                           "fake", False), candles=c)

    def fetch_mark(self, symbol):
        return FetchResult(symbol, "1d", quote=Quote(symbol, 42.0, time.time(),
                           "fake", False))


def _worker(tmp_path) -> PollWorker:
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'w.db'}")
    w._open_repo()
    w._repo.seed_if_empty(("AAPL", "BTC/USDT"), "kraken")
    w._reload_watchlist()
    w._load_portfolio()
    src = _Src()
    w._source = src
    w._adapters = dict.fromkeys(("stock:active", "stock:held", "crypto:kraken:active", "crypto:kraken:held"), src)
    return w


def test_remove_held_symbol_blocked_with_inline_reason(tmp_path):
    w = _worker(tmp_path)
    w._portfolio = PortfolioState(cash=Decimal("1000"), realised_pnl=Decimal("0"),
                                  positions=(EngPosition("BTC/USDT", Decimal("1"),
                                                         Decimal("10")),))
    before = [p.symbol for p in w._persisted]
    w.remove_symbol("BTC/USDT")
    assert [p.symbol for p in w._persisted] == before, "held symbol must stay"
    assert w.remove_rejected.emissions, "inline feedback must be emitted"
    sym, reason = w.remove_rejected.emissions[-1]
    assert sym == "BTC/USDT" and reason == "Close the position first."
    w.stop()


def test_remove_active_symbol_falls_back_to_next(tmp_path):
    w = _worker(tmp_path)
    w.remove_symbol("AAPL")
    assert w._symbol == "BTC/USDT"
    assert [p.symbol for p in w._persisted] == ["BTC/USDT"]
    w.stop()


def test_remove_last_symbol_clears_to_empty_state(tmp_path):
    w = _worker(tmp_path)
    w.remove_symbol("BTC/USDT")
    w.remove_symbol("AAPL")
    assert w._symbol is None and w._candles == () and w._source is None
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.closed_count == 0
    w.stop()


def test_remove_non_held_non_active_just_removes(tmp_path):
    w = _worker(tmp_path)
    w.remove_symbol("BTC/USDT")
    assert [p.symbol for p in w._persisted] == ["AAPL"]
    assert w._symbol == "AAPL"
    assert not w.remove_rejected.emissions
    w.stop()


def test_menu_remove_path_uses_the_same_worker_slot(tmp_path):
    # menu 'Remove' reuses worker.remove_symbol, already covered above; just pin
    # the slot for a non-held non-active symbol
    w = _worker(tmp_path)
    w.remove_symbol("BTC/USDT")
    assert [p.symbol for p in w._persisted] == ["AAPL"]
    assert not w.remove_rejected.emissions
    w.stop()


def test_menu_set_active_path_switches_active(tmp_path):
    # menu 'Set as active' routes through worker.select_symbol
    w = _worker(tmp_path)
    assert w._symbol == "AAPL"
    w.select_symbol("BTC/USDT")
    assert w._symbol == "BTC/USDT"
    w.stop()


def test_effective_active_prefers_live_pending():
    from mahad.data.symbols import effective_active
    rows = ("AAPL", "BTC/USDT")
    assert effective_active("BTC/USDT", "AAPL", rows) == "BTC/USDT"
    assert effective_active(None, "AAPL", rows) == "AAPL"
    assert effective_active("GONE", "AAPL", rows) == "AAPL"   # pending dropped from rows, state wins
    assert effective_active(None, None, rows) is None
