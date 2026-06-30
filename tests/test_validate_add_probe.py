# validate-then-add probe, exercised through a fake adapter and the injectable probe seam
from __future__ import annotations

import time

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.data.models import Quote
from mahad.data.source import FetchResult, SourceError, SourceErrorKind
from mahad.worker import PollWorker


class _MarkSource:
    # fetch_mark outcome per symbol: 'ok' | 'empty' | 'timeout' | 'network'
    def __init__(self, outcomes):
        self.outcomes = outcomes
        self.calls: list = []

    def fetch(self, symbol, timeframe):
        return FetchResult(symbol, timeframe,
                           error=SourceError(SourceErrorKind.NETWORK, "down"))

    def fetch_mark(self, symbol):
        self.calls.append(symbol)
        kind = self.outcomes.get(symbol, "ok")
        if kind == "ok":
            return FetchResult(symbol, "1d",
                               quote=Quote(symbol, 10.0, time.time(), "fake", False))
        err = {"empty": SourceErrorKind.EMPTY,
               "timeout": SourceErrorKind.TIMEOUT,
               "network": SourceErrorKind.NETWORK}[kind]
        return FetchResult(symbol, "1d", error=SourceError(err, kind))


def _worker(tmp_path, outcomes=None) -> tuple:
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'w.db'}")
    w._open_repo()
    w._repo.seed_if_empty(("AAPL",), "kraken")
    w._reload_watchlist()
    w._load_portfolio()
    src = _MarkSource(outcomes or {})
    w._adapters = dict.fromkeys(
        ("stock:active", "stock:held", "crypto:kraken:active", "crypto:kraken:held"), src)
    w._source = src
    return w, src


def test_unresolvable_symbol_rejected_inline_not_added(tmp_path):
    w, src = _worker(tmp_path, {"YTREYHETRY": "empty"})
    w.add_symbol("ytreyhetry")
    assert "YTREYHETRY" not in [p.symbol for p in w._persisted], \
        "Flow 2: no optimistic add"
    text, reason = w.add_rejected.emissions[-1]
    assert text == "ytreyhetry", "typed text preserved"
    assert reason == "YTREYHETRY not found - check the ticker."
    w.stop()


def test_probe_timeout_rejects_with_could_not_verify(tmp_path):
    w, _ = _worker(tmp_path, {"MSFT": "timeout"})
    w.add_symbol("MSFT")
    assert "MSFT" not in [p.symbol for p in w._persisted]
    _, reason = w.add_rejected.emissions[-1]
    assert reason == "Could not verify MSFT - check your connection and retry."
    w.stop()


def test_probe_network_failure_rejects_with_could_not_verify(tmp_path):
    w, _ = _worker(tmp_path, {"BTC/USD": "network"})
    w.add_symbol("BTC/USD")
    assert "BTC/USD" not in [p.symbol for p in w._persisted]
    _, reason = w.add_rejected.emissions[-1]
    assert "Could not verify BTC/USD" in reason
    w.stop()


def test_resolving_symbol_is_added(tmp_path):
    w, src = _worker(tmp_path, {"MSFT": "ok"})
    w.add_symbol("msft")
    assert "MSFT" in [p.symbol for p in w._persisted]
    assert src.calls == ["MSFT"], "exactly one probe"
    w.stop()


def test_non_usd_rejected_before_any_probe(tmp_path):
    w, src = _worker(tmp_path)
    w.add_symbol("ETH/EUR")
    assert src.calls == [], "non-USD must reject pre-probe"
    _, reason = w.add_rejected.emissions[-1]
    assert reason == "Base currency is USD - no FX in v1."
    w.stop()


def test_charset_garbage_rejected_before_any_probe(tmp_path):
    w, src = _worker(tmp_path)
    w.add_symbol("<img src=x>")
    assert src.calls == []
    assert w.add_rejected.emissions
    w.stop()


def test_duplicate_add_never_probes(tmp_path):
    w, src = _worker(tmp_path)
    w.add_symbol("AAPL")                          # already in the watchlist
    assert src.calls == [], "duplicates are silently ignored, never probed"
    assert [p.symbol for p in w._persisted] == ["AAPL"]
    w.stop()


def test_cap_rejection_never_probes(tmp_path):
    w, src = _worker(tmp_path, {"ZZZ": "ok"})
    import mahad.config as config
    syms = [f"S{i}" for i in range(config.WATCHLIST_CAP - 1)]
    for s in syms:
        w._repo.add(s, "stock", "USD", "finnhub")
    w._reload_watchlist()
    w.add_symbol("ZZZ")
    assert src.calls == [], "a cap rejection must not probe"
    _, reason = w.add_rejected.emissions[-1]
    assert "full" in reason
    w.stop()


def test_probe_seam_is_injectable(tmp_path):
    w, src = _worker(tmp_path)
    w._probe_symbol = lambda sym: (False, "nope")
    w.add_symbol("MSFT")
    assert w.add_rejected.emissions[-1][1] == "nope"
    assert src.calls == []
    w.stop()
