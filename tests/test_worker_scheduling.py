# Headless, Qt-free (tests/_qt_stub), tmp_path DBs, no network.
from __future__ import annotations

import time
from dataclasses import dataclass
from decimal import Decimal

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Quote
from mahad.data.source import (FetchResult, SourceError, SourceErrorKind,
                               normalize_ohlcv)
from mahad.engine.portfolio import PortfolioState, Position as EngPosition
from mahad.worker import PollWorker


def _series(symbol, timeframe, n=30, base=100.0):
    t0 = time.time() - n * 3600
    rows = [(t0 + i * 3600, base + i, base + i + 1, base + i - 1,
             base + i + 0.5, 10.0) for i in range(n)]
    return normalize_ohlcv(symbol, timeframe, rows, 500, last_is_forming=True)


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


@dataclass(frozen=True)
class _DailyResult:
    symbol: str
    bars: tuple
    error: object = None

    @property
    def ok(self):
        return self.error is None and bool(self.bars)


class _BatchCryptoSource:
    # Kraken-like: fetch_mark_batch covers every pair in one call
    def __init__(self):
        self.batch_calls: list = []
        self.single_calls: list = []

    def fetch(self, symbol, timeframe):
        candles = _series(symbol, timeframe)
        q = Quote(symbol, float(candles[-1].close), time.time(), "kraken")
        return FetchResult(symbol, timeframe, quote=q, candles=candles)

    def fetch_mark(self, symbol):
        self.single_calls.append(symbol)
        return FetchResult(symbol, "1d",
                           quote=Quote(symbol, 7.0, time.time(), "kraken"))

    def fetch_mark_batch(self, symbols):
        self.batch_calls.append(tuple(symbols))
        return {s: FetchResult(s, "1d",
                               quote=Quote(s, 11.0, time.time(), "kraken"))
                for s in symbols}


class _StockishSource:
    # marks plus an official daily history feed
    def __init__(self, daily_bars=(), daily_error=None, needs_key=False):
        self.daily_calls: list = []
        self._bars = tuple(daily_bars)
        self._daily_error = daily_error
        self.needs_key = needs_key

    def fetch(self, symbol, timeframe):
        if self.needs_key:
            return FetchResult(symbol, timeframe, error=SourceError(
                SourceErrorKind.NEEDS_KEY, config.NEEDS_KEY_STOCK_MSG))
        q = Quote(symbol, 312.06, time.time(), "finnhub")
        return FetchResult(symbol, timeframe, quote=q, candles=())

    def fetch_mark(self, symbol):
        return self.fetch(symbol, "1d")

    def fetch_daily_history(self, symbol, start_date=None):
        self.daily_calls.append(symbol)
        return _DailyResult(symbol, self._bars, self._daily_error)


def _bars(n=5, base=300.0):
    return tuple(_Bar(ts=86400.0 * (i + 1), open=base + i, high=base + i + 2,
                      low=base + i - 2, close=base + i + 1,
                      adj_close=base + i + 0.5, volume=1e6, div_cash=0.0,
                      split_factor=1.0) for i in range(n))


def _worker(tmp_path, src, symbol="AAPL", name="w.db"):
    w = PollWorker(symbol=symbol, timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / name}")
    w._open_repo()
    w._load_portfolio()
    w._source = src
    w._adapters = {"stock:active": src, "stock:held": src,
                   "crypto:kraken:active": src, "crypto:kraken:held": src}
    return w


# --------------------------------------------------------------------------- #
# Held crypto marks ride ONE batched Ticker call
# --------------------------------------------------------------------------- #
def test_held_crypto_marks_ride_one_batch_call(tmp_path):
    src = _BatchCryptoSource()
    w = _worker(tmp_path, src, symbol="BTC/USD")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("100")),
                   EngPosition("SOL/USD", Decimal("2"), Decimal("50")),
                   EngPosition("ADA/USD", Decimal("9"), Decimal("1")),
                   EngPosition("DOGE/USD", Decimal("5"), Decimal("1"))))
    changed = w._poll_held()
    assert changed
    assert len(src.batch_calls) == 1
    assert set(src.batch_calls[0]) == {"ETH/USD", "SOL/USD", "ADA/USD", "DOGE/USD"}
    assert src.single_calls == []
    assert all(w._marks[s].mark == 11.0 for s in src.batch_calls[0])


def test_mixed_held_book_batches_crypto_and_budgets_stocks(tmp_path):
    # crypto rides one batch; the round-robin budget applies to stock marks only
    class _Mixed(_BatchCryptoSource):
        def __init__(self):
            super().__init__()
            self.stock_marks: list = []

        def fetch_mark(self, symbol):
            if "/" not in symbol:
                self.stock_marks.append(symbol)
                return FetchResult(symbol, "1d",
                                   quote=Quote(symbol, 5.0, time.time(),
                                               "finnhub"))
            return super().fetch_mark(symbol)
    src = _Mixed()
    w = _worker(tmp_path, src, symbol="BTC/USD")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("1")),
                   EngPosition("SOL/USD", Decimal("1"), Decimal("1")),
                   EngPosition("AAPL", Decimal("1"), Decimal("1")),
                   EngPosition("MSFT", Decimal("1"), Decimal("1")),
                   EngPosition("NVDA", Decimal("1"), Decimal("1")),
                   EngPosition("META", Decimal("1"), Decimal("1"))))
    w._poll_held()
    assert len(src.batch_calls) == 1
    assert set(src.batch_calls[0]) == {"ETH/USD", "SOL/USD"}
    assert len(src.stock_marks) == config.HELD_POLL_BUDGET
    assert all("/" not in s for s in src.stock_marks)
    assert src.single_calls == []


def test_batchless_source_keeps_the_budgeted_round_robin(tmp_path):
    class _NoBatch(_BatchCryptoSource):
        fetch_mark_batch = None                            # not callable, worker must fall back
    src = _NoBatch()
    w = _worker(tmp_path, src, symbol="BTC/USD")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=tuple(EngPosition(f"C{i}/USD", Decimal("1"), Decimal("1"))
                        for i in range(5)))
    w._poll_held()
    assert len(src.single_calls) == config.HELD_POLL_BUDGET


def test_failed_batch_stales_prior_marks(tmp_path):
    src = _BatchCryptoSource()
    def bad_batch(symbols):
        return {s: FetchResult(s, "1d", error=SourceError(
            SourceErrorKind.NETWORK, "down")) for s in symbols}
    src.fetch_mark_batch = bad_batch
    w = _worker(tmp_path, src, symbol="BTC/USD")
    w._portfolio = PortfolioState(
        cash=Decimal("1000"), realised_pnl=Decimal("0"),
        positions=(EngPosition("ETH/USD", Decimal("1"), Decimal("100")),))
    w._marks["ETH/USD"] = Quote("ETH/USD", 3900.0, time.time(), "kraken")
    w._poll_held()
    assert w._marks["ETH/USD"].stale is True               # kept, not wiped
    assert dict(w._build_health_view().providers).get("kraken", "").startswith("retrying")


# --------------------------------------------------------------------------- #
# The official 1d series: DailyBar hydration + the overlay
# --------------------------------------------------------------------------- #
def test_ensure_stock_history_fetches_persists_and_overlays(tmp_path):
    src = _StockishSource(daily_bars=_bars())
    w = _worker(tmp_path, src)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._ensure_stock_history("AAPL")
    assert src.daily_calls == ["AAPL"]                     # one Tiingo fetch
    assert len(w._daily_series["AAPL"]) == 5
    assert w._repo.latest_daily_bar_ts("AAPL") == 86400.0 * 5
    w._poll()
    assert len(w._candles) == 5
    assert all(c.is_closed for c in w._candles)
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.closed_count == 5
    assert snap.points[-1][1] == 312.06                    # live mark, not a closed bar


def test_ensure_stock_history_prefers_the_cache_over_the_network(tmp_path):
    src = _StockishSource(daily_bars=_bars())
    w = _worker(tmp_path, src)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._repo.upsert_daily_bars("AAPL", _bars(3))
    w._ensure_stock_history("AAPL")
    assert src.daily_calls == []
    assert len(w._daily_series["AAPL"]) == 3


def test_keyless_tiingo_keeps_the_sampled_floor(tmp_path):
    src = _StockishSource(daily_error=SourceError(
        SourceErrorKind.NEEDS_KEY, config.NEEDS_KEY_HISTORY_MSG))
    w = _worker(tmp_path, src)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._ensure_stock_history("AAPL")
    assert "AAPL" not in w._daily_series
    w._poll()
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.error is None and snap.points              # history gone, quote still renders mark-forward
    assert dict(w._build_health_view().providers).get("tiingo") == "needs a free key"


def test_crypto_symbols_never_touch_the_daily_path(tmp_path):
    src = _BatchCryptoSource()
    w = _worker(tmp_path, src, symbol="BTC/USD")
    w._ensure_stock_history("BTC/USD")
    assert w._daily_series == {}


# --------------------------------------------------------------------------- #
# Needs-key states (the documented keyless degradation)
# --------------------------------------------------------------------------- #
def test_keyless_finnhub_chart_state_carries_the_friendly_copy(tmp_path):
    src = _StockishSource(needs_key=True)
    w = _worker(tmp_path, src)
    w._poll()
    snap = w.snapshot_ready.emissions[-1][0]
    assert snap.error == config.NEEDS_KEY_STOCK_MSG        # no "needs_key:" prefix
    hv = w._build_health_view()
    assert hv.state == "needs_key" and hv.reason == "needs a free key"


def test_keyless_finnhub_watchlist_row_flags_needs_key(tmp_path):
    src = _StockishSource(needs_key=True)
    w = _worker(tmp_path, src)
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    w._reload_watchlist()
    w._emit_watchlist()
    state = w.watchlist_ready.emissions[-1][0]
    row = next(r for r in state.rows if r.symbol == "AAPL")
    assert row.needs_key is True and row.has_quote is False


# --------------------------------------------------------------------------- #
# Migration runs at start, once
# --------------------------------------------------------------------------- #
def test_worker_migrates_old_rows_on_open(tmp_path):
    seed = _worker(tmp_path, _StockishSource(), name="m.db")
    seed._repo.add("AAPL", "stock", "USD", "yfinance")
    seed._repo.add("BTC/USDT", "crypto", "USDT", "kraken")
    seed._repo.close()
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'm.db'}")
    w._open_repo()
    w._run_data_migration()
    symbols = {p.symbol: p.provider for p in w._repo.list_watchlist()}
    assert symbols == {"AAPL": "finnhub", "BTC/USD": "kraken"}
    assert w._repo.migrate_legacy_schema() is False               # idempotent, marker already set


# --------------------------------------------------------------------------- #
# Provider lines for the chip tooltip
# --------------------------------------------------------------------------- #
def test_provider_lines_cover_ok_retrying_and_needs_key(tmp_path):
    w = _worker(tmp_path, _StockishSource())
    w._note_provider("finnhub", None)
    w._note_provider("kraken", SourceError(SourceErrorKind.TIMEOUT, "slow"))
    w._note_provider("tiingo", SourceError(SourceErrorKind.NEEDS_KEY, "x"))
    lines = dict(w._provider_lines())
    assert lines["finnhub"] == "ok"
    assert lines["kraken"] == "retrying (timeout)"
    assert lines["tiingo"] == "needs a free key"


def test_provider_error_keeps_its_first_since(tmp_path):
    w = _worker(tmp_path, _StockishSource())
    w._wallclock = lambda: 100.0
    w._note_provider("kraken", SourceError(SourceErrorKind.NETWORK, "a"))
    first = w._provider_errors["kraken"][2]
    w._wallclock = lambda: 200.0
    w._note_provider("kraken", SourceError(SourceErrorKind.NETWORK, "b"))
    assert w._provider_errors["kraken"][2] == first
