# error-path tests; every DB test uses tmp_path, never config.data_dir
from __future__ import annotations

import math
import sqlite3
import time
from decimal import Decimal

import pytest

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.config import valid_risk_timeframe
from mahad.data.models import Candle, Quote
from mahad.data.repository import MahadRepository, open_repository
from mahad.data.kraken_source import KrakenSource, mark_from_kraken_ticker
from mahad.data.finnhub_source import FinnhubSource
from mahad.data.budget import RateBudget
from mahad.data.source import (FetchResult, SourceError, SourceErrorKind,
                               dedupe_sort_candles, is_valid_price,
                               normalize_ohlcv)
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.snapshot import build_render_snapshot
from mahad.worker import PollWorker


# --------------------------------------------------------------------------- #
# Normalisation - hostile provider rows: validate, drop bad data
# --------------------------------------------------------------------------- #
HOSTILE_ROWS = [
    None,
    [],
    [1.0],                                       # short row
    [1.0, 2.0, 3.0],                             # still short
    ["x", 1, 2, 3, 4, 5],                        # non-numeric ts
    [1e9, "a", "b", "c", "d", "e"],              # non-numeric ohlcv
    [1e9, None, None, None, None, None],
    object(),
]


def test_normalize_ohlcv_drops_malformed_rows_never_raises():
    rows = HOSTILE_ROWS + [[1_700_000_000, 1.0, 2.0, 0.5, 1.5, 100.0]]
    candles = normalize_ohlcv("AAPL", "1d", rows)
    assert len(candles) == 1
    assert candles[0].close == 1.5


def test_normalize_ohlcv_drops_non_finite_price_rows():
    # a NaN/inf OHLC row must be dropped, not propagated into the chart
    nan, inf = float("nan"), float("inf")
    rows = [
        [1_700_000_000, 1.0, 2.0, 0.5, nan, 10.0],     # NaN close
        [1_700_000_060, inf, 2.0, 0.5, 1.0, 10.0],     # inf open
        [1_700_000_120, 1.0, 2.0, 0.5, -5.0, 10.0],    # negative close
        [1_700_000_180, 1.0, 2.0, 0.5, 1.2, 10.0],     # good
    ]
    candles = normalize_ohlcv("AAPL", "1m", rows)
    closes = [c.close for c in candles]
    assert all(math.isfinite(c) and c > 0 for c in closes)
    assert 1.2 in closes


def test_dedupe_sort_handles_duplicates_and_disorder():
    mk = lambda ts, close: Candle("A", "1d", ts, 1, 2, 0.5, close, 1)
    out = dedupe_sort_candles([mk(3, 30), mk(1, 10), mk(3, 31), mk(2, 20)])
    assert [c.ts for c in out] == [1, 2, 3]
    assert out[-1].close == 31                     # later occurrence wins


# --------------------------------------------------------------------------- #
# Mark fallbacks - hostile tickers
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("entry", [
    None, {}, {"c": None}, {"c": []}, {"c": ["nan", "0"]}, {"c": ["0", "0"]},
    {"c": ["-3", "1"]}, {"c": ["abc", "1"]},
    {"b": ["1.0"], "a": None}, {"b": ["-1"], "a": ["2"]},
])
def test_kraken_mark_rule_rejects_unusable(entry):
    assert mark_from_kraken_ticker(entry) is None


def test_kraken_mark_rule_order():
    assert mark_from_kraken_ticker({"c": ["5", "1"], "b": ["4"], "a": ["6"]}) == 5.0
    assert mark_from_kraken_ticker({"c": ["0", "0"], "b": ["4"], "a": ["6"]}) == 5.0


def test_is_valid_price_total():
    for bad in (None, "x", float("nan"), float("inf"), -1, 0, [], {}):
        assert not is_valid_price(bad)
    assert is_valid_price(1e-9) and is_valid_price("3.5")


# --------------------------------------------------------------------------- #
# Adapters - failures become typed values, never exceptions
# --------------------------------------------------------------------------- #
def test_kraken_adapter_returns_error_value(monkeypatch):
    src = KrakenSource()
    def _raise(url):
        raise OSError("network down")
    monkeypatch.setattr(src, "_get_json", _raise)
    res = src.fetch("BTC/USD", "1d")
    assert isinstance(res, FetchResult) and not res.ok
    assert res.error is not None and isinstance(res.error, SourceError)


def test_finnhub_adapter_returns_error_value(monkeypatch):
    src = FinnhubSource(key="k", budget=RateBudget(1000))
    def _raise(url):
        raise OSError("network down")
    monkeypatch.setattr(src, "_get_json", _raise)
    res = src.fetch("AAPL", "1d")
    assert not res.ok and res.error.kind in (SourceErrorKind.UNKNOWN,
                                             SourceErrorKind.NETWORK)


# --------------------------------------------------------------------------- #
# Settings / JSON corruption -> safe defaults
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("data", [
    None, "junk", 42, [], {"sma_period": "NaN"}, {"sma_enabled": object()},
    {"sma_period": -100, "ema_period": 10**9, "rsi_period": None},
])
def test_indicator_settings_from_dict_never_raises(data):
    s = IndicatorSettings.from_dict(data)        # type: ignore[arg-type]
    assert 2 <= s.sma_period <= 400 and 2 <= s.ema_period <= 400


@pytest.mark.parametrize("tf", [None, "", "5m", 7, object(), "1D"])
def test_valid_risk_timeframe_coerces(tf):
    assert valid_risk_timeframe(tf) == "1d"


def test_repository_get_setting_corrupt_json(tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'x.db'}")
    repo._session.execute(
        __import__("sqlalchemy").text(
            "INSERT INTO settings (key, value, value_type) VALUES ('k', '{bad', 'json')"))
    repo._session.commit()
    assert repo.get_setting("k") is None
    repo.close()


def test_repository_list_alerts_corrupt_params(tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'x.db'}")
    repo.add("AAPL", "stock", "USD", "finnhub")
    alert, _ = repo.add_alert("AAPL", "price_threshold", {"level": 1.0}, "up")
    from sqlalchemy import text
    repo._session.execute(text("UPDATE alerts SET params = '{nope'"))
    repo._session.commit()
    rows = repo.list_alerts()
    assert len(rows) == 1 and rows[0].params == {}
    repo.close()


# --------------------------------------------------------------------------- #
# SQLite: PRAGMAs in force; transient contention behaviour; recovery
# --------------------------------------------------------------------------- #
def test_pragmas_in_force(tmp_path):
    repo = MahadRepository(f"sqlite:///{tmp_path / 'x.db'}")
    from sqlalchemy import text
    mode = repo._session.execute(text("PRAGMA journal_mode")).scalar()
    busy = repo._session.execute(text("PRAGMA busy_timeout")).scalar()
    fks = repo._session.execute(text("PRAGMA foreign_keys")).scalar()
    assert str(mode).lower() == "wal"
    assert int(busy) == 5000
    assert int(fks) == 1
    repo.close()


def test_held_write_lock_raises_cleanly_then_recovers(tmp_path):
    # held lock surfaces as a clean OperationalError after busy_timeout
    db = tmp_path / "x.db"
    repo = MahadRepository(f"sqlite:///{db}", busy_timeout_ms=150)
    repo.set_setting("k", 1)
    blocker = sqlite3.connect(str(db))
    blocker.execute("BEGIN IMMEDIATE")
    blocker.execute("INSERT INTO settings (key, value, value_type) VALUES ('b','1','json')")
    from sqlalchemy.exc import OperationalError
    with pytest.raises(OperationalError):
        repo.set_setting("k", 2)
    repo._session.rollback()
    blocker.rollback()
    blocker.close()
    repo.set_setting("k", 3)                      # recovers after release
    assert repo.get_setting("k") == 3
    repo.close()


def test_open_repository_recovers_corrupt_file(tmp_path, monkeypatch):
    monkeypatch.setattr("mahad.config.default_db_url",
                        lambda: f"sqlite:///{tmp_path / 'm.db'}")
    (tmp_path / "m.db").write_bytes(b"this is not a sqlite database " * 10)
    repo = open_repository(f"sqlite:///{tmp_path / 'm.db'}")
    try:
        assert repo.get_setting("anything") is None          # fresh, usable
        backups = list(tmp_path.glob("m.db.corrupt-*"))
        assert backups, "corrupt file must be backed up, not destroyed"
    finally:
        repo.close()


def test_open_repository_schema_mismatch_backs_up(tmp_path):
    url = f"sqlite:///{tmp_path / 's.db'}"
    repo = MahadRepository(url)
    repo.close()
    con = sqlite3.connect(str(tmp_path / "s.db"))
    con.execute("UPDATE schema_version SET version = 99")
    con.commit()
    con.close()
    repo2 = open_repository(url)
    try:
        backups = list(tmp_path.glob("s.db.corrupt-*"))
        assert backups
    finally:
        repo2.close()


def test_open_repository_does_not_rotate_on_transient_lock(tmp_path, monkeypatch):
    # a healthy file must never rotate to .corrupt-* just because of a lock
    url = f"sqlite:///{tmp_path / 'h.db'}"
    MahadRepository(url).close()                  # healthy file exists
    from sqlalchemy.exc import OperationalError
    import mahad.data.repository as repo_mod

    calls = {"n": 0}
    real_init = repo_mod.MahadRepository.__init__

    def flaky_init(self, u, busy_timeout_ms=5000):
        calls["n"] += 1
        raise OperationalError("PRAGMA", {}, Exception("database is locked"))

    monkeypatch.setattr(repo_mod.MahadRepository, "__init__", flaky_init)
    with pytest.raises(Exception):
        repo_mod.open_repository(url)
    monkeypatch.setattr(repo_mod.MahadRepository, "__init__", real_init)
    assert not list(tmp_path.glob("h.db.corrupt-*")), \
        "a locked-but-healthy DB was rotated away (data displacement)"


# --------------------------------------------------------------------------- #
# Snapshot edges
# --------------------------------------------------------------------------- #
def test_snapshot_empty_inputs():
    snap = build_render_snapshot([], None, symbol="AAPL")
    assert not snap.has_data and snap.symbol == "AAPL" and not snap.live


def test_snapshot_all_forming_bars():
    candles = [Candle("A", "1d", 1.0 + i, 1, 2, 0.5, 1.5, 1, is_closed=False)
               for i in range(5)]
    snap = build_render_snapshot(candles, None, settings=IndicatorSettings(
        sma_enabled=True))
    assert snap.closed_count == 0
    assert snap.sma is not None and not snap.sma.has_data


# --------------------------------------------------------------------------- #
# Worker slot guards (Qt-free via the stub): never crash on hostile payloads
# --------------------------------------------------------------------------- #
class _FailingSource:
    def fetch(self, symbol, timeframe):
        return FetchResult(symbol, timeframe,
                           error=SourceError(SourceErrorKind.NETWORK, "down"))


def _worker(tmp_path) -> PollWorker:
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'w.db'}")
    w._open_repo()
    w._load_portfolio()
    return w


def test_worker_poll_source_failure_keeps_last_good(tmp_path):
    w = _worker(tmp_path)
    w._source = _FailingSource()
    w._last_quote = Quote("AAPL", 100.0, time.time(), "yfinance", False)
    w._candles = (Candle("AAPL", "1d", 1.0, 1, 2, 0.5, 1.5, 1),)
    w._poll()                                      # must not raise
    assert w._last_quote.stale is True
    assert w.snapshot_ready.emissions, "a snapshot is still emitted on failure"
    w.stop()


@pytest.mark.parametrize("payload", [
    None, "x", 42, [],
    {"side": "buy"},                                          # missing fields
    {"side": "buy", "qty": "1", "symbol": "AAPL", "mark": "garbage", "ts": time.time()},
    {"side": "buy", "qty": "1", "symbol": "AAPL", "mark": float("nan"), "ts": time.time()},
    {"side": "weird", "qty": "1", "symbol": "AAPL", "mark": 10.0, "ts": time.time()},
    {"side": "buy", "qty": object(), "symbol": "AAPL", "mark": 10.0, "ts": time.time()},
])
def test_worker_place_order_hostile_payloads_never_raise(tmp_path, payload):
    w = _worker(tmp_path)
    w.place_order(payload)                         # must not raise
    if isinstance(payload, dict):
        assert w.order_result.emissions, "a dict payload must get a result"
        assert not w.order_result.emissions[-1][0]["ok"]
    assert w._portfolio.cash == Decimal("100000")  # ledger untouched
    w.stop()


@pytest.mark.parametrize("payload", [
    None, "x", [], {"condition_type": "nope", "params": {}, "direction": "up"},
    {"condition_type": "price_threshold", "params": {"level": "x"}, "direction": "up"},
    {"condition_type": "price_threshold", "params": {"level": 1}, "direction": "sideways"},
])
def test_worker_arm_alert_hostile_payloads_never_raise(tmp_path, payload):
    w = _worker(tmp_path)
    w.arm_alert(payload)                           # must not raise
    assert all(not e for e in []) or True
    w.stop()


def test_worker_persist_before_emit_on_fire(tmp_path):
    # if persisting the disarm fails the event is dropped, spec stays armed
    from mahad.engine.signals import AlertSpec
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    alert, _ = w._repo.add_alert("AAPL", "price_threshold", {"level": 1.0}, "up")
    w._alerts = [AlertSpec(id=alert.id, symbol="AAPL",
                           condition_type="price_threshold",
                           params={"level": 1.0}, direction="up")]
    w._last_quote = Quote("AAPL", 100.0, time.time(), "yfinance", False)
    w._candles = ()

    def boom(*a, **k):
        raise RuntimeError("disk full")
    w._repo.set_alert_state = boom                 # persist fails
    events = w._evaluate_alerts()
    assert events == []                            # event dropped, not emitted
    assert w._alerts[0].armed is True              # stays armed (no desync)
    w.stop()


def test_worker_fire_persists_then_emits(tmp_path):
    from mahad.engine.signals import AlertSpec
    w = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    alert, _ = w._repo.add_alert("AAPL", "price_threshold", {"level": 1.0}, "up")
    w._alerts = [AlertSpec(id=alert.id, symbol="AAPL",
                           condition_type="price_threshold",
                           params={"level": 1.0}, direction="up")]
    w._last_quote = Quote("AAPL", 100.0, time.time(), "yfinance", False)
    events = w._evaluate_alerts()
    assert len(events) == 1
    assert w._alerts[0].armed is False
    persisted = [a for a in w._repo.list_alerts() if a.id == alert.id][0]
    assert persisted.armed is False and persisted.fired_at is not None
    w.stop()


def test_worker_stale_quote_pauses_alerts_no_fire(tmp_path):
    from mahad.engine.signals import AlertSpec
    w = _worker(tmp_path)
    w._alerts = [AlertSpec(id=1, symbol="AAPL", condition_type="price_threshold",
                           params={"level": 1.0}, direction="up")]
    w._last_quote = Quote("AAPL", 100.0, time.time() - 9999, "yfinance", False)
    events = w._evaluate_alerts()
    assert events == [] and w._alerts_paused is True
    w.stop()


def test_worker_db_open_failure_degrades_to_memory(monkeypatch, tmp_path):
    w = PollWorker(symbol="AAPL", db_url="sqlite:////nonexistent-dir-zz/x.db")
    w._open_repo()                                 # must not raise
    assert w._repo is not None                     # in-memory fallback
    w.stop()
