# Headless worker tests; fetchers are monkeypatched at the worker's import site.
from __future__ import annotations

from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

import mahad.worker as worker_mod  # noqa: E402
from mahad import config  # noqa: E402
from mahad.data.context_sources import ContextResult  # noqa: E402
from mahad.data.models import Quote  # noqa: E402
from mahad.data.repository import CONTEXT_KEY  # noqa: E402
from mahad.data.source import SourceError, SourceErrorKind  # noqa: E402
from mahad.engine.portfolio import PortfolioState, Position as EngPosition  # noqa: E402
from mahad.engine.risk import ValueSample  # noqa: E402
from mahad.worker import PollWorker  # noqa: E402


class _FakeRepo:
    # settings round-trip in memory; the rest just records what the worker writes
    def __init__(self) -> None:
        self.settings: dict = {}
        self.appended: list = []
        self.rebased: list = []

    def get_setting(self, key):
        return self.settings.get(key)

    def set_setting(self, key, value):
        self.settings[key] = value

    def append_value_history(self, **kw):
        self.appended.append(kw)

    def rebase_value_history(self, **kw):
        self.rebased.append(kw)

    def get_peak(self):
        return None

    def close(self):
        pass


def _worker(now: float = 1_000_000.0) -> tuple[PollWorker, _FakeRepo, dict]:
    w = PollWorker(symbol="AAPL", timeframe="1d", db_url="sqlite:///:memory:")
    repo = _FakeRepo()
    w._repo = repo
    state = {"now": now}
    w._wallclock = lambda: state["now"]
    return w, repo, state


# the wall-clock due grid
def test_sleep_catchup_takes_one_sample_and_preserves_the_grid():
    w, repo, state = _worker()
    w._risk_timeframe = "1d"
    day = 86_400.0
    w._next_sample_due = state["now"] + day
    taken: list[float] = []
    w._sample_value_history = lambda: taken.append(state["now"])  # type: ignore[method-assign]
    w._refresh_context_if_due = lambda now: None  # type: ignore[method-assign]
    # sleeps through three grid points, wakes 2h after the third
    state["now"] += day * 3 + 7_200.0
    w._on_heartbeat()
    assert taken == [state["now"]]                       # one catch-up sample, no more
    assert w._next_sample_due == 1_000_000.0 + day * 4   # original grid kept
    w._on_heartbeat()
    assert len(taken) == 1                               # not due again yet


def test_heartbeat_no_sample_before_due():
    w, _repo, state = _worker()
    w._risk_timeframe = "1m"
    w._next_sample_due = state["now"] + 60.0
    taken: list[float] = []
    w._sample_value_history = lambda: taken.append(1.0)  # type: ignore[method-assign]
    w._refresh_context_if_due = lambda now: None  # type: ignore[method-assign]
    state["now"] += 59.9
    w._on_heartbeat()
    assert taken == []
    state["now"] += 0.2
    w._on_heartbeat()
    assert len(taken) == 1


def test_sample_value_history_stamps_the_injected_wallclock():
    w, repo, state = _worker(now=2_222_222.0)
    w._sample_value_history()
    assert len(w._value_history) == 1
    assert w._value_history[0].ts == 2_222_222.0  # injected wallclock, not time.time
    assert repo.appended and repo.appended[0]["ts"] == 2_222_222.0


def test_set_risk_timeframe_reanchors_the_grid():
    w, repo, state = _worker()
    w._risk_timeframe = "1d"
    w._next_sample_due = state["now"] + 86_400.0
    w.set_risk_timeframe("1m")
    assert w._risk_timeframe == "1m"
    assert w._next_sample_due == state["now"] + 60.0     # re-anchored to the 1m grid
    assert repo.rebased


# context scheduling, budget, caching, degradation
def _ok_treasury(*_a, **_k):
    return ContextResult("treasury", data={"as_of": "2026-06-09", "y3m": 4.18,
                                           "y2y": 4.05, "y10y": 4.40,
                                           "y30y": 4.85})


def _ok_fng(*_a, **_k):
    return ContextResult("fng", data={"value": 9, "as_of": "2026-06-10",
                                      "classification": "Extreme Fear"})


def _fail(source):
    def _f(*_a, **_k):
        return ContextResult(source, error=SourceError(SourceErrorKind.NETWORK,
                                                       "down"))
    return _f


def test_one_context_fetch_per_heartbeat_tick(monkeypatch):
    w, _repo, state = _worker()
    calls: list[str] = []
    monkeypatch.setattr(worker_mod, "fetch_treasury_yields",
                        lambda *a, **k: (calls.append("treasury"), _ok_treasury())[1])
    monkeypatch.setattr(worker_mod, "fetch_fear_greed",
                        lambda *a, **k: (calls.append("fng"), _ok_fng())[1])
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: None)
    now = state["now"]
    w._ctx_due = {"treasury": now - 1, "fng": now - 1, "vix": now - 1}
    w._next_sample_due = None
    w._on_heartbeat()
    assert calls == ["treasury"]                          # one fetch per tick
    assert w._ctx_due["treasury"] == now + config.CONTEXT_REFRESH_S
    w._on_heartbeat()
    assert calls == ["treasury", "fng"]                   # next due source on the next tick


def test_context_success_builds_tiles_and_persists_the_cache(monkeypatch):
    w, repo, state = _worker()
    monkeypatch.setattr(worker_mod, "fetch_treasury_yields", _ok_treasury)
    w._refresh_context("treasury", state["now"])
    tile = w._ctx_yields
    assert tile.available and tile.y10y == 4.40 and tile.spread_bp == 35.0
    assert tile.reading == "normal" and tile.as_of == "2026-06-09"
    cached = repo.settings[CONTEXT_KEY]
    assert cached["yields"]["y10y"] == 4.40
    snaps = w.snapshot_ready.emissions
    assert snaps and snaps[-1][0].context.yields.y10y == 4.40
    assert snaps[-1][0].context.summary.startswith("10Y 4.40")


def test_context_failure_keeps_cached_values_with_an_honest_note(monkeypatch):
    w, _repo, state = _worker()
    monkeypatch.setattr(worker_mod, "fetch_treasury_yields", _ok_treasury)
    w._refresh_context("treasury", state["now"])
    monkeypatch.setattr(worker_mod, "fetch_treasury_yields", _fail("treasury"))
    w._refresh_context("treasury", state["now"] + 10)
    tile = w._ctx_yields
    assert tile.available and tile.y10y == 4.40           # cached data survives the failed refresh
    assert tile.note == "refresh failed - showing 2026-06-09"
    assert w._ctx_due["treasury"] == state["now"] + 10 + config.CONTEXT_RETRY_S


def test_context_failure_with_no_data_reads_unavailable(monkeypatch):
    w, _repo, state = _worker()
    monkeypatch.setattr(worker_mod, "fetch_fear_greed", _fail("fng"))
    w._refresh_context("fng", state["now"])
    assert not w._ctx_sentiment.available
    assert w._ctx_sentiment.note == "unavailable - retrying"


def test_vix_without_a_key_is_the_designed_keyless_state(monkeypatch):
    w, _repo, state = _worker()
    called: list = []
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: None)
    monkeypatch.setattr(worker_mod, "fetch_vix",
                        lambda *a, **k: called.append(1))
    w._refresh_context("vix", state["now"])
    assert called == []                                   # keyless: no network attempt
    assert w._ctx_vix.needs_key and w._ctx_vix.note == "needs a free FRED key"
    assert w._ctx_due["vix"] == state["now"] + config.CONTEXT_RETRY_S
    view = w._build_context_view()
    assert "VIX needs key" in view.summary


def test_vix_with_a_key_fetches_and_bands(monkeypatch):
    w, _repo, state = _worker()
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: "k123")
    monkeypatch.setattr(worker_mod, "fetch_vix",
                        lambda key, timeout: ContextResult(
                            "vix", data={"value": 15.40, "as_of": "2026-06-04",
                                         "change": -0.66}))
    w._refresh_context("vix", state["now"])
    assert w._ctx_vix.available and w._ctx_vix.band == "normal"
    assert not w._ctx_vix.needs_key


def test_load_context_cache_restores_tiles_offline(monkeypatch):
    w, repo, _state = _worker()
    repo.settings[CONTEXT_KEY] = {
        "yields": {"as_of": "2026-06-09", "fetched_ts": 1.0, "y3m": 4.18,
                   "y2y": 4.05, "y10y": 4.40, "y30y": 4.85},
        "sentiment": {"as_of": "2026-06-10", "fetched_ts": 1.0, "value": 9,
                      "classification": "Extreme Fear"},
        "vix": {"as_of": "2026-06-04", "fetched_ts": 1.0, "value": 15.40,
                "change": -0.66}}
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: "k")
    w._load_context_cache()
    assert w._ctx_yields.available and w._ctx_yields.spread_bp == 35.0
    assert w._ctx_sentiment.value == 9
    assert w._ctx_vix.available and w._ctx_vix.band == "normal"
    # adds the keyless boe + fx tiers to the same due grid
    assert set(w._ctx_due) == {"treasury", "fng", "vix", "boe", "fx"}


def test_cached_vix_is_not_shown_when_the_key_is_gone(monkeypatch):
    w, repo, _state = _worker()
    repo.settings[CONTEXT_KEY] = {"vix": {"as_of": "2026-06-04",
                                          "fetched_ts": 1.0, "value": 15.40}}
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: None)
    w._load_context_cache()
    assert w._ctx_vix.needs_key and not w._ctx_vix.available


# stale-flag unification; history rows; health
def _hold_position(w: PollWorker, symbol: str = "MSFT") -> None:
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition(symbol, Decimal("2"), Decimal("100")),))


def test_missing_mark_flags_all_three_valuation_views_stale():
    w, _repo, _state = _worker()
    _hold_position(w)                                    # MSFT has no mark
    pv = w._build_portfolio_view()
    rv = w._build_risk_view()
    _value, _pos, _cash, sampler_stale = w._value_now()
    # all three valuation views must agree on stale
    assert pv.any_marks_stale is True
    assert rv.any_stale is True
    assert sampler_stale is True


def test_fresh_mark_keeps_all_three_views_non_stale():
    w, _repo, state = _worker()
    _hold_position(w)
    import time as _t
    w._marks["MSFT"] = Quote(symbol="MSFT", mark=110.0, ts=_t.time(),
                             source="fake", stale=False)
    assert w._build_portfolio_view().any_marks_stale is False
    assert w._build_risk_view().any_stale is False
    assert w._value_now()[3] is False


def test_riskview_carries_the_exportable_history_rows():
    w, _repo, _state = _worker()
    w._value_history.append(ValueSample(ts=1.0, value=100.0, stale=False))
    w._value_history.append(ValueSample(ts=2.0, value=101.0, stale=True))
    rv = w._build_risk_view()
    assert rv.history == ((1.0, 100.0, False), (2.0, 101.0, True))


def test_health_rides_the_snapshot_and_maps_states():
    w, _repo, _state = _worker()
    w._emit_snapshot(None)
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.health.state == "ok" and snap.timeframe == "1d"
    w._last_error = ("network", "Tunnel connection failed: 403", 50.0)
    w._emit_snapshot(None)
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.health.state == "offline" and snap.health.since_ts == 50.0
    w._last_error = ("timeout", "timed out", 60.0)
    assert w._build_health_view().state == "retrying"
    assert "timeout" in w._build_health_view().reason


def test_poll_failure_records_and_success_clears_the_health_error():
    w, _repo, _state = _worker()

    class _Bad:
        def fetch(self, s, tf):
            from mahad.data.source import FetchResult
            return FetchResult(s, tf, error=SourceError(SourceErrorKind.TIMEOUT,
                                                        "timed out"))

        def fetch_mark(self, s):
            return self.fetch(s, "1d")

    w._source = _Bad()
    w._poll()
    assert w._last_error is not None and w._last_error[0] == "timeout"
    since = w._last_error[2]
    w._backoff_until = 0.0                               # as a user intent would
    w._poll()
    assert w._last_error[2] == since                     # since-anchor holds across repeats
    w._backoff_until = 0.0

    class _Good:
        def fetch(self, s, tf):
            from mahad.data.source import FetchResult
            import time as _t
            return FetchResult(s, tf, quote=Quote(symbol=s, mark=1.0,
                                                  ts=_t.time(), source="f",
                                                  stale=False))

        def fetch_mark(self, s):
            return self.fetch(s, "1d")

    w._source = _Good()
    w._poll()
    assert w._last_error is None
    assert w._build_health_view().state == "ok"


# the degraded-persistence flag
def test_db_open_failure_sets_the_degraded_flag(monkeypatch):
    monkeypatch.setattr(worker_mod, "open_repository",
                        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("locked")))
    w = PollWorker(symbol="AAPL", timeframe="1d", db_url="sqlite:///:memory:")
    w._open_repo()
    assert w._db_degraded is True
    assert w._repo is not None                            # in-memory fallback opened


def test_clean_db_open_does_not_flag():
    w = PollWorker(symbol="AAPL", timeframe="1d", db_url="sqlite:///:memory:")
    w._open_repo()
    assert w._db_degraded is False
    w._repo.close()
