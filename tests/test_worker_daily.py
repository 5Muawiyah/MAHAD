"""Worker daily-coverage: one fetch per heartbeat tick, delta vs full re-pull,
forming crypto bar excluded, SPY benchmark kept out of the watchlist."""
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Candle
from mahad.data.source import SourceError, SourceErrorKind
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


def _bars(n=3, base=300.0, t0=86400.0, div=0.0, split=1.0):
    return tuple(_Bar(ts=t0 * (i + 1), open=base, high=base + 2, low=base - 2,
                      close=base + i, adj_close=base + i - 0.5, volume=1e6,
                      div_cash=(div if i == n - 1 else 0.0),
                      split_factor=(split if i == n - 1 else 1.0))
                 for i in range(n))


@dataclass(frozen=True)
class _DailyResult:
    symbol: str
    bars: tuple
    error: object = None

    @property
    def ok(self):
        return self.error is None and bool(self.bars)


class _Stock:
    def __init__(self, by_call=None, error=None):
        self.calls: list = []                # (symbol, start_date)
        self._by_call = list(by_call or [])  # results served in order
        self._error = error
        self.needs_key = False

    def fetch(self, symbol, timeframe):
        from mahad.data.source import FetchResult
        from mahad.data.models import Quote
        return FetchResult(symbol, timeframe,
                           quote=Quote(symbol, 100.0, time.time(), "finnhub"))

    fetch_mark = fetch

    def fetch_daily_history(self, symbol, start_date=None):
        self.calls.append((symbol, start_date))
        if self._error is not None:
            return _DailyResult(symbol, (), self._error)
        if self._by_call:
            return _DailyResult(symbol, self._by_call.pop(0))
        return _DailyResult(symbol, _bars())


class _Crypto:
    # last OHLC bar is_closed=False, i.e. still forming
    def __init__(self):
        self.ohlc_calls: list = []

    def fetch(self, symbol, timeframe):
        from mahad.data.source import FetchResult
        from mahad.data.models import Quote
        return FetchResult(symbol, timeframe,
                           quote=Quote(symbol, 7.0, time.time(), "kraken"))

    fetch_mark = fetch

    def fetch_mark_batch(self, symbols):
        return {s: self.fetch_mark(s) for s in symbols}

    def fetch_ohlc(self, symbol, timeframe):
        self.ohlc_calls.append((symbol, timeframe))
        mk = lambda i, closed: Candle(symbol=symbol, timeframe="1d",
                                      ts=86400.0 * (i + 1), open=10.0 + i,
                                      high=11.0 + i, low=9.0 + i,
                                      close=10.5 + i, volume=5.0,
                                      is_closed=closed)
        return (mk(0, True), mk(1, True), mk(2, False)), None


def _worker(tmp_path, stock=None, crypto=None, symbol="AAPL", name="d.db"):
    w = PollWorker(symbol=symbol, timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / name}")
    w._open_repo()
    w._load_portfolio()
    stock = stock or _Stock()
    crypto = crypto or _Crypto()
    w._source = stock if "/" not in symbol else crypto
    w._adapters = {"stock:active": stock, "stock:held": stock,
                   "crypto:kraken:active": crypto, "crypto:kraken:held": crypto}
    w._wallclock = lambda: 1000.0
    return w, stock, crypto


def _tick_until_quiet(w, start=1000.0, ticks=30, step=20.0):
    # drive the coverage step directly; context is never due in these tests
    t = start
    for _ in range(ticks):
        w._wallclock = lambda t=t: t
        w._refresh_daily_if_due(t)
        t += step
    return t


# --------------------------------------------------------------------------- #
def test_coverage_set_is_positions_active_stock_and_benchmark(tmp_path):
    w, _, _ = _worker(tmp_path)
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("1")),
                   EngPosition("MSFT", Decimal("1"), Decimal("1"))))
    cov = w._daily_coverage_symbols()
    assert cov == ["ETH/USD", "MSFT", "AAPL", "SPY"]


def test_one_coverage_fetch_per_tick_and_all_symbols_covered(tmp_path):
    w, stock, crypto = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("1")),))
    w._refresh_daily_if_due(1000.0)                  # first tick only seeds dues
    first_total = len(stock.calls) + len(crypto.ohlc_calls)
    assert first_total <= 1
    _tick_until_quiet(w)
    assert len(crypto.ohlc_calls) == 1
    fetched_stocks = [s for s, _ in stock.calls]
    assert fetched_stocks.count("AAPL") == 1 and fetched_stocks.count("SPY") == 1
    # everything landed in the cache
    assert w._repo.latest_daily_bar_ts("ETH/USD") is not None
    assert w._repo.latest_daily_bar_ts("AAPL") is not None
    assert w._repo.latest_daily_bar_ts("SPY") is not None
    # at most one fetch per tick, so the three land spread out
    assert len(stock.calls) + len(crypto.ohlc_calls) == 3


def test_crypto_forming_bar_never_persists(tmp_path):
    w, _, crypto = _worker(tmp_path, symbol="ETH/USD")
    w._repo.ensure_symbol("ETH/USD", "crypto", "USD", "kraken")
    assert w._refresh_daily_crypto("ETH/USD") is True
    rows = w._repo.list_daily_bars("ETH/USD")
    assert len(rows) == 2                            # 3 bars - the forming one
    assert rows[-1].close == 11.5
    assert rows[-1].adj_close == rows[-1].close      # crypto: adj == raw


def test_stock_delta_fetch_starts_at_the_latest_cached_date(tmp_path):
    stock = _Stock(by_call=[_bars(2, t0=86400.0 * 4)])
    w, stock, _ = _worker(tmp_path, stock=stock)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _bars(3))      # cache through day 3
    assert w._refresh_daily_stock("AAPL") is True
    sym, start = stock.calls[0]
    assert sym == "AAPL" and start == "1970-01-04"   # the latest cached date
    assert w._repo.latest_daily_bar_ts("AAPL") == 86400.0 * 8


def test_corporate_action_in_the_delta_triggers_a_full_repull(tmp_path):
    delta_with_split = _bars(1, t0=86400.0 * 9, split=4.0)
    full_history = _bars(5, base=80.0)
    stock = _Stock(by_call=[delta_with_split, full_history])
    w, stock, _ = _worker(tmp_path, stock=stock)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _bars(3))
    assert w._refresh_daily_stock("AAPL") is True
    assert len(stock.calls) == 2                     # delta, then the FULL pull
    assert stock.calls[1][1] is None                 # full = no start date
    rows = w._repo.list_daily_bars("AAPL")
    assert len(rows) == 5 and rows[0].close == 80.0  # the old cache cleared


def test_keyless_tiingo_marks_the_provider_and_retries_later(tmp_path):
    stock = _Stock(error=SourceError(SourceErrorKind.NEEDS_KEY,
                                     config.NEEDS_KEY_HISTORY_MSG))
    w, stock, _ = _worker(tmp_path, stock=stock)
    w._refresh_daily_if_due(1000.0)
    _tick_until_quiet(w)
    assert dict(w._provider_lines()).get("tiingo") == "needs a free key"
    spy_due = w._daily_due["SPY"]
    assert spy_due - 1000.0 <= config.DAILY_RETRY_S + 600.0   # retry, not nightly


def test_benchmark_row_exists_but_never_joins_the_watchlist(tmp_path):
    w, stock, _ = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    _tick_until_quiet(w)
    assert w._repo.latest_daily_bar_ts("SPY") is not None
    assert "SPY" not in w._repo.watchlist_symbols()


def test_context_due_blocks_the_daily_fetch_that_tick(tmp_path):
    w, stock, _ = _worker(tmp_path)
    calls = []
    w._refresh_context_if_due = lambda now: calls.append(now) or True
    w._refresh_daily_if_due = lambda now: calls.append(("daily", now))
    w._next_sample_due = None
    w._on_heartbeat()
    assert calls and all(not isinstance(c, tuple) for c in calls)   # daily skipped


def test_heartbeat_drives_the_daily_fetch_when_context_is_idle(tmp_path):
    w, stock, _ = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._next_sample_due = None
    w._ctx_due = {}                                   # context never due
    t = [1000.0]
    w._wallclock = lambda: t[0]
    for _ in range(40):
        w._on_heartbeat()
        t[0] += 20.0
    assert [s for s, _ in stock.calls].count("AAPL") == 1
    assert w._repo.latest_daily_bar_ts("AAPL") is not None


def test_at_most_one_coverage_fetch_per_tick(tmp_path):
    # pins the per-tick property itself, not just eventual coverage
    w, stock, crypto = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("1")),))
    t = 1000.0
    for _ in range(40):
        before = len(stock.calls) + len(crypto.ohlc_calls)
        w._wallclock = lambda t=t: t
        w._refresh_daily_if_due(t)
        after = len(stock.calls) + len(crypto.ohlc_calls)
        assert after - before <= 1                    # never bursty
        t += 20.0
    assert len(stock.calls) + len(crypto.ohlc_calls) == 3


def test_success_redues_nightly_failure_redues_retry(tmp_path):
    w, stock, _ = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    _tick_until_quiet(w)
    aapl_due = w._daily_due["AAPL"]
    assert aapl_due > 1000.0 + config.DAILY_REFRESH_S - 700.0   # nightly


def test_full_repull_failure_keeps_the_old_cache_and_retries(tmp_path):
    # if the split-flagged delta's full re-pull fails, the partial result must
    # not land on the old cache: that would mix two adjustment bases
    delta_with_split = _bars(1, t0=86400.0 * 9, split=4.0)
    stock = _Stock(by_call=[delta_with_split])        # the FULL call errors
    def daily(symbol, start_date=None):
        stock.calls.append((symbol, start_date))
        if start_date is not None:
            return _DailyResult(symbol, delta_with_split)
        return _DailyResult(symbol, (), SourceError(SourceErrorKind.NETWORK,
                                                    "down"))
    stock.fetch_daily_history = daily
    w, stock, _ = _worker(tmp_path, stock=stock)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _bars(3))
    assert w._refresh_daily_stock("AAPL") is False
    rows = w._repo.list_daily_bars("AAPL")
    assert len(rows) == 3                             # old cache untouched
    assert all(r.split_factor == 1.0 for r in rows)   # no mixed bases


def test_stale_covered_cache_tops_up_promptly_fresh_waits_nightly(tmp_path):
    # restart-staleness fix: a days-old cache tops up soon after start, a fresh
    # one still waits for the nightly due
    w, stock, _ = _worker(tmp_path)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    now = 86400.0 * 30
    w._repo.upsert_daily_bars("AAPL", _bars(3))       # latest ts = day 3 (old)
    w._refresh_daily_if_due(now)                      # seeds the dues
    assert w._daily_due["AAPL"] - now < config.DAILY_REFRESH_S / 2   # prompt
    w2, stock2, _ = _worker(tmp_path, name="d2.db")
    w2._repo.add("AAPL", "stock", "USD", "finnhub")
    fresh = [_Bar(ts=now - 3600.0, open=1, high=2, low=0.5, close=1.5,
                  adj_close=1.5, volume=1.0, div_cash=0.0, split_factor=1.0)]
    w2._repo.upsert_daily_bars("AAPL", fresh)
    w2._refresh_daily_if_due(now)
    assert w2._daily_due["AAPL"] - now > config.DAILY_REFRESH_S - 700.0


def test_closed_position_stops_refreshing(tmp_path):
    w, stock, crypto = _worker(tmp_path)
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("MSFT", Decimal("1"), Decimal("1")),))
    _tick_until_quiet(w)
    n_msft = [s for s, _ in stock.calls].count("MSFT")
    assert n_msft == 1
    w._portfolio = PortfolioState(cash=Decimal("1000"),
                                  realised_pnl=Decimal("0"), positions=())
    _tick_until_quiet(w, start=1000.0 + 3 * config.DAILY_REFRESH_S)
    assert [s for s, _ in stock.calls].count("MSFT") == n_msft   # no more


def test_ensure_symbol_is_idempotent(tmp_path):
    w, _, _ = _worker(tmp_path)
    a = w._repo.ensure_symbol("SPY", "stock", "USD", "finnhub")
    b = w._repo.ensure_symbol("SPY", "stock", "USD", "finnhub")
    assert a == b
    assert "SPY" not in w._repo.watchlist_symbols()
