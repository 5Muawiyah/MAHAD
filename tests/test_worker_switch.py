from __future__ import annotations

import time
from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Quote
from mahad.data.source import FetchResult, SourceError, SourceErrorKind, normalize_ohlcv
from mahad.engine.portfolio import PortfolioState, Position as EngPosition
from mahad.worker import PollWorker


def _series(symbol: str, timeframe: str, n: int = 30, base: float = 100.0):
    t0 = time.time() - n * 3600
    rows = [(t0 + i * 3600, base + i, base + i + 1, base + i - 1, base + i + 0.5, 10.0)
            for i in range(n)]
    return normalize_ohlcv(symbol, timeframe, rows, 500, last_is_forming=True)


class _GoodSource:
    def __init__(self):
        self.fetch_calls: list = []
        self.mark_calls: list = []

    def fetch(self, symbol, timeframe):
        self.fetch_calls.append((symbol, timeframe))
        candles = _series(symbol, timeframe)
        q = Quote(symbol=symbol, mark=float(candles[-1].close), ts=time.time(),
                  source="fake", stale=False)
        return FetchResult(symbol, timeframe, quote=q, candles=candles)

    def fetch_mark(self, symbol):
        self.mark_calls.append(symbol)
        return FetchResult(symbol, "1d",
                           quote=Quote(symbol=symbol, mark=42.0, ts=time.time(),
                                       source="fake", stale=False))


class _FailingSource:
    def fetch(self, symbol, timeframe):
        return FetchResult(symbol, timeframe,
                           error=SourceError(SourceErrorKind.NETWORK, "down"))

    def fetch_mark(self, symbol):
        return FetchResult(symbol, "1d",
                           error=SourceError(SourceErrorKind.NETWORK, "down"))


def _worker(tmp_path, src=None) -> PollWorker:
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'w.db'}")
    w._open_repo()
    w._load_portfolio()
    src = src or _GoodSource()
    w._source = src
    w._adapters = {"stock:active": src, "stock:held": src,
                   "crypto:kraken:active": src, "crypto:kraken:held": src}
    return w


# --------------------------------------------------------------------------- #
# Candle cache
# --------------------------------------------------------------------------- #
def test_switch_to_cached_symbol_renders_prior_series_instantly(tmp_path):
    w = _worker(tmp_path)
    w._poll()                                       # AAPL fetched + cached
    assert ("AAPL", "1d") in w._history
    w._switch_active("MSFT")                        # never fetched -> empty frame
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.symbol == "MSFT" and snap.closed_count == 0
    w._poll()                                       # MSFT fetched + cached
    w._switch_active("AAPL")                        # cached -> instant series
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.symbol == "AAPL"
    assert snap.closed_count > 0, "cached series must render before any fetch"


def test_cached_render_keeps_original_quote_ts_for_staleness(tmp_path):
    w = _worker(tmp_path)
    w._poll()
    old = w._marks["AAPL"]
    stale_ts = time.time() - 10_000
    w._marks["AAPL"] = Quote("AAPL", old.mark, stale_ts, old.source, False)
    w._switch_active("MSFT")
    w._switch_active("AAPL")                        # cached render
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.live is False, "an old cached quote must NOT render as live"


def test_cached_forming_bar_stays_open(tmp_path):
    w = _worker(tmp_path)
    w._poll()
    w._switch_active("MSFT")
    w._switch_active("AAPL")
    assert w._candles and w._candles[-1].is_closed is False


def test_switch_resets_crossover_baseline_no_replay_from_cache(tmp_path):
    w = _worker(tmp_path)
    w._poll()
    assert w._last_closed_ts is not None
    w._switch_active("MSFT")
    assert w._last_closed_ts is None, "baseline must reset on switch"


def test_remove_symbol_evicts_cache(tmp_path):
    w = _worker(tmp_path)
    w._poll()
    assert ("AAPL", "1d") in w._history
    w.remove_symbol("AAPL")
    assert all(k[0] != "AAPL" for k in w._history)


def test_timeframe_change_uses_cache_per_timeframe(tmp_path):
    w = _worker(tmp_path)
    w._poll()                                       # caches (AAPL, 1d)
    w.set_timeframe("1h")                           # no cache -> empty frame
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.closed_count == 0
    w._poll()                                       # caches (AAPL, 1h)
    w.set_timeframe("1d")                           # cached -> instant series
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.closed_count > 0
    w.stop()


# --------------------------------------------------------------------------- #
# Marks-only held fetch + emit-before-held ordering
# --------------------------------------------------------------------------- #
def _hold(w, *symbols):
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=tuple(EngPosition(s, Decimal("1"), Decimal("10")) for s in symbols))


def test_poll_held_uses_fetch_mark_not_full_fetch(tmp_path):
    src = _GoodSource()
    w = _worker(tmp_path, src)
    _hold(w, "ETH/USDT", "SOL/USDT")
    w._poll()
    assert "ETH/USDT" in src.mark_calls and "SOL/USDT" in src.mark_calls
    assert all(sym == "AAPL" for sym, _tf in src.fetch_calls), \
        "held symbols must never take the full-history fetch path"


def test_active_snapshot_emitted_before_held_fetches(tmp_path):
    order: list = []

    class _OrderSource(_GoodSource):
        def fetch_mark(self, symbol):
            order.append(("held", symbol))
            return super().fetch_mark(symbol)

    src = _OrderSource()
    w = _worker(tmp_path, src)
    _hold(w, "ETH/USDT")
    base = len(w.snapshot_ready.emissions)

    real_emit = w._emit_snapshot

    def tracking_emit(reason=None):
        order.append(("snapshot", reason))
        real_emit(reason)

    w._emit_snapshot = tracking_emit
    w._poll()
    first_snapshot = order.index(("snapshot", None))
    first_held = order.index(("held", "ETH/USDT"))
    assert first_snapshot < first_held, \
        "the active frame must not wait for the held round-robin"
    assert len(w.snapshot_ready.emissions) >= base + 2, \
        "a second frame carries the refreshed held marks"


def test_post_held_reemit_carries_same_error_reason(tmp_path):
    # a failed active fetch must not flicker error -> empty
    class _FailActiveGoodHeld(_GoodSource):
        def fetch(self, symbol, timeframe):
            return FetchResult(symbol, timeframe,
                               error=SourceError(SourceErrorKind.NETWORK, "down"))

    w = _worker(tmp_path, _FailActiveGoodHeld())
    _hold(w, "ETH/USDT")
    w._poll()
    last = w.snapshot_ready.emissions[-1][0]
    assert last.error, "the re-emit must carry the cycle's error reason"
    w.stop()


# --------------------------------------------------------------------------- #
# Capped backoff + jitter
# --------------------------------------------------------------------------- #
def _clocked(w, start=1000.0):
    state = {"now": start}
    w._monotonic = lambda: state["now"]
    w._jitter = lambda a, b: 1.0                    # deterministic
    return state


def test_backoff_skips_timer_polls_until_window_expires(tmp_path):
    src = _FailingSource()
    w = _worker(tmp_path, src)
    clock = _clocked(w)
    w._poll()                                       # failure -> streak 1, window 10s
    assert w._fail_streak == 1
    n = len(w.snapshot_ready.emissions)
    clock["now"] += 5.0
    w._poll()                                       # inside the window -> skipped
    assert len(w.snapshot_ready.emissions) == n, "backed-off poll must not emit"
    clock["now"] += 6.0                             # window expired
    w._poll()
    assert w._fail_streak == 2, "the next failure extends the streak"
    w.stop()


def test_backoff_caps_at_config_ceiling(tmp_path):
    w = _worker(tmp_path, _FailingSource())
    clock = _clocked(w)
    for _ in range(10):
        w._poll()
        clock["now"] = w._backoff_until + 0.001     # expire each window
    assert (w._backoff_until - clock["now"]) <= config.BACKOFF_CAP_S


def test_backoff_resets_on_success_and_user_intent_bypasses(tmp_path):
    good = _GoodSource()
    w = _worker(tmp_path, _FailingSource())
    clock = _clocked(w)
    w._poll()                                       # arm the window
    assert w._backoff_until > clock["now"]
    w.request_poll()                                # user intent clears the window
    assert w._backoff_until == 0.0
    w._source = good
    w._adapters = {"stock:active": good, "stock:held": good}
    w._poll()                                       # success resets the streak
    assert w._fail_streak == 0
    w.stop()


# --------------------------------------------------------------------------- #
# The drawdown seed applies only when the persisted peak predates the
# sampled window (engine contract; the locked risk maths stays untouched).
# --------------------------------------------------------------------------- #
def test_drawdown_seed_not_applied_when_peak_postdates_window(tmp_path):
    # 100 -> 90 -> 120: true max drawdown is -10%; the pre-fix worker seeded the
    # current all-time peak (120 at t3) and reported -25% with peak after trough
    from decimal import Decimal as D
    from mahad.engine.risk import ValueSample
    w = _worker(tmp_path)
    w._value_history.extend([
        ValueSample(ts=1.0, value=100.0, stale=False),
        ValueSample(ts=2.0, value=90.0, stale=False),
        ValueSample(ts=3.0, value=120.0, stale=False),
    ])
    w._peak_value, w._peak_ts = D("120"), 3.0          # current all-time peak
    view = w._build_risk_view()
    assert view.dd_defined
    assert abs(view.dd_pct - (-10.0)) < 1e-9, f"got {view.dd_pct}"
    assert view.dd_peak_ts is not None and view.dd_trough_ts is not None
    assert view.dd_peak_ts <= view.dd_trough_ts, "a peak can never postdate its trough"
    w.stop()


def test_drawdown_seed_applies_for_rolled_off_peak(tmp_path):
    # the seed's real job: a peak that rolled off the window (peak_ts before the
    # first sample) still counts
    from decimal import Decimal as D
    from mahad.engine.risk import ValueSample
    w = _worker(tmp_path)
    w._value_history.extend([
        ValueSample(ts=10.0, value=90.0, stale=False),
        ValueSample(ts=11.0, value=95.0, stale=False),
    ])
    w._peak_value, w._peak_ts = D("100"), 1.0          # predates the window
    view = w._build_risk_view()
    assert view.dd_defined
    assert abs(view.dd_pct - (-10.0)) < 1e-9, "the rolled-off peak 100 must count"
    w.stop()
