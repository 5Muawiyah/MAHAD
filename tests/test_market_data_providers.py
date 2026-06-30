# provider adapters against captured fixtures; no network, no Qt
from __future__ import annotations

import json
import urllib.error
from pathlib import Path

import pytest

from mahad.data import sampled_bars
from mahad.data.budget import RateBudget
from mahad.data.finnhub_source import FinnhubSource
from mahad.data.kraken_source import (KrakenSource, app_to_kraken_pair,
                                      kraken_key_to_app, mark_from_kraken_ticker)
from mahad.data.source import SourceErrorKind
from mahad.data.stock_source import StockSource
from mahad.data.tiingo_source import TiingoSource

FIX = Path(__file__).parent / "fixtures" / "providers"


def _load(name: str):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def _patch_json(monkeypatch, obj, payload):
    if isinstance(payload, Exception):
        def _raise(url):
            raise payload
        monkeypatch.setattr(obj, "_get_json", _raise)
    else:
        monkeypatch.setattr(obj, "_get_json", lambda url: payload)


def _budget(allow: bool = True) -> RateBudget:
    b = RateBudget(1000)
    if not allow:
        b.try_acquire = lambda: False        # type: ignore[method-assign]
    return b


def test_app_to_kraken_pair_uses_the_xbt_alias():
    assert app_to_kraken_pair("BTC/USD") == "XBTUSD"
    assert app_to_kraken_pair("ETH/USD") == "ETHUSD"
    assert app_to_kraken_pair("DOGE/USD") == "XDGUSD"


@pytest.mark.parametrize("key,expected", [
    ("XXBTZUSD", "BTC/USD"),
    ("XETHZUSD", "ETH/USD"),
    ("SOLUSD", "SOL/USD"),
    ("ADAUSD", "ADA/USD"),
])
def test_kraken_key_to_app_maps_legacy_and_modern_keys(key, expected):
    requested = {expected.split("/")[0] + "/USD": expected}
    assert kraken_key_to_app(key, requested) == expected


def test_kraken_key_to_app_unrequested_pair_is_none():
    assert kraken_key_to_app("XXBTZUSD", {"ETH/USD": "ETH/USD"}) is None


# crypto mark rule: c[0] last, else bid/ask mid
def test_kraken_mark_prefers_last():
    entry = _load("kraken_ticker_batch.json")["result"]["XXBTZUSD"]
    assert mark_from_kraken_ticker(entry) == pytest.approx(73541.8)


def test_kraken_mark_falls_back_to_bid_ask_mid():
    entry = dict(_load("kraken_ticker_batch.json")["result"]["XXBTZUSD"])
    entry["c"] = ["0.0", "0"]
    assert mark_from_kraken_ticker(entry) == pytest.approx((73541.0 + 73544.1) / 2.0)


@pytest.mark.parametrize("entry", [
    None, {}, {"c": None}, {"c": []}, {"c": ["0", "0"]}, {"c": ["-3", "1"]},
    {"c": ["abc", "1"]}, {"b": ["1.0"], "a": None}, {"b": ["-1"], "a": ["2"]},
])
def test_kraken_mark_rejects_unusable(entry):
    assert mark_from_kraken_ticker(entry) is None


def test_kraken_batch_covers_every_requested_pair(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, _load("kraken_ticker_batch.json"))
    out = src.fetch_mark_batch(["BTC/USD", "ETH/USD", "SOL/USD"])
    assert out["BTC/USD"].ok and out["BTC/USD"].quote.mark == pytest.approx(73541.8)
    assert out["ETH/USD"].ok and out["ETH/USD"].quote.mark == pytest.approx(3921.25)
    assert out["SOL/USD"].ok and out["SOL/USD"].quote.mark == pytest.approx(171.2)
    assert all(r.quote.source == "kraken" for r in out.values())


def test_kraken_batch_unknown_pair_maps_to_empty(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, _load("kraken_ticker_unknown.json"))
    out = src.fetch_mark_batch(["NOPE/USD"])
    assert not out["NOPE/USD"].ok
    assert out["NOPE/USD"].error.kind == SourceErrorKind.EMPTY


def test_kraken_batch_missing_symbol_is_empty(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, _load("kraken_ticker_batch.json"))
    out = src.fetch_mark_batch(["BTC/USD", "ZZZ/USD"])
    assert out["BTC/USD"].ok
    assert out["ZZZ/USD"].error.kind == SourceErrorKind.EMPTY


def test_kraken_network_failure_is_a_value(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, urllib.error.URLError("unreachable"))
    out = src.fetch_mark_batch(["BTC/USD"])
    assert out["BTC/USD"].error.kind == SourceErrorKind.NETWORK
    res = src.fetch("BTC/USD", "1d")
    assert not res.ok and res.error is not None


def test_kraken_timeout_is_typed(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, OSError("timed out"))
    out = src.fetch_mark_batch(["BTC/USD"])
    assert out["BTC/USD"].error.kind == SourceErrorKind.TIMEOUT


def test_kraken_malformed_payload_is_a_value(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, {"result": "garbage"})
    out = src.fetch_mark_batch(["BTC/USD"])
    assert not out["BTC/USD"].ok


def test_kraken_ohlc_parses_and_marks_the_forming_bar(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src, _load("kraken_ohlc.json"))
    candles, err = src.fetch_ohlc("BTC/USD", "1d")
    assert err is None and len(candles) == 3
    assert candles[-1].is_closed is False                  # venue forming bar
    assert all(c.is_closed for c in candles[:-1])
    assert candles[-1].close == pytest.approx(73541.8)
    assert candles[0].volume == pytest.approx(812.34)      # row[6], not vwap


def test_kraken_fetch_assembles_quote_and_candles(monkeypatch):
    src = KrakenSource()
    calls = []
    def fake(url):
        calls.append(url)
        return (_load("kraken_ohlc.json") if "OHLC" in url
                else _load("kraken_ticker_batch.json"))
    monkeypatch.setattr(src, "_get_json", fake)
    res = src.fetch("BTC/USD", "1d")
    assert res.ok and res.quote.mark == pytest.approx(73541.8)
    assert len(res.candles) == 3
    assert any("/0/public/Ticker" in u for u in calls)
    assert any("/0/public/OHLC" in u for u in calls)
    assert all("/0/public/" in u for u in calls)           # public endpoints only


def test_finnhub_mark_is_quote_c_with_exchange_ts(monkeypatch):
    src = FinnhubSource(key="k-test", budget=_budget())
    _patch_json(monkeypatch, src, _load("finnhub_quote.json"))
    res = src.fetch_mark("AAPL")
    assert res.ok and res.quote.mark == pytest.approx(312.06)
    assert res.quote.exchange_ts == pytest.approx(1765486622.0)
    assert res.quote.source == "finnhub"
    assert res.quote.ts != res.quote.exchange_ts           # feed clock vs venue clock


def test_finnhub_unknown_symbol_zero_payload_is_empty(monkeypatch):
    src = FinnhubSource(key="k-test", budget=_budget())
    _patch_json(monkeypatch, src, _load("finnhub_quote_unknown.json"))
    res = src.fetch_mark("ZZZZZ")
    assert not res.ok and res.error.kind == SourceErrorKind.EMPTY


def test_finnhub_without_key_is_needs_key():
    src = FinnhubSource(key="", budget=_budget())
    assert src.needs_key
    res = src.fetch_mark("AAPL")
    assert res.error.kind == SourceErrorKind.NEEDS_KEY
    assert "finnhub.io" in res.error.message


def test_finnhub_budget_denial_serves_the_cached_quote(monkeypatch):
    src = FinnhubSource(key="k-test", budget=_budget())
    _patch_json(monkeypatch, src, _load("finnhub_quote.json"))
    first = src.fetch_mark("AAPL")
    assert first.ok
    src._budget = _budget(allow=False)
    paced = src.fetch_mark("AAPL")
    assert paced.ok and paced.quote.ts == first.quote.ts   # the cached quote
    cold = src.fetch_mark("MSFT")                          # nothing cached
    assert not cold.ok and cold.error.kind == SourceErrorKind.TIMEOUT


def test_finnhub_errors_are_redacted_of_the_key(monkeypatch):
    src = FinnhubSource(key="SECRETKEY", budget=_budget())
    _patch_json(monkeypatch, src, RuntimeError("boom SECRETKEY boom"))
    res = src.fetch_mark("AAPL")
    assert not res.ok and "SECRETKEY" not in res.error.message
    assert "***" in res.error.message


def test_finnhub_http_error_is_network(monkeypatch):
    src = FinnhubSource(key="k", budget=_budget())
    _patch_json(monkeypatch, src,
                urllib.error.HTTPError("u", 429, "too many", {}, None))
    res = src.fetch_mark("AAPL")
    assert res.error.kind == SourceErrorKind.NETWORK and "429" in res.error.message


def test_finnhub_401_is_invalid_key(monkeypatch):
    src = FinnhubSource(key="k", budget=_budget())
    _patch_json(monkeypatch, src,
                urllib.error.HTTPError("u", 401, "unauthorized", {}, None))
    res = src.fetch_mark("AAPL")
    assert res.error.kind == SourceErrorKind.INVALID_KEY
    assert "README" in res.error.message and "401" in res.error.message


def test_tiingo_401_is_invalid_key(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src,
                urllib.error.HTTPError("u", 401, "unauthorized", {}, None))
    res = src.fetch_daily("AAPL")
    assert res.error.kind == SourceErrorKind.INVALID_KEY
    assert "README" in res.error.message


def test_rate_budget_sliding_window():
    t = [0.0]
    b = RateBudget(2, monotonic=lambda: t[0])
    assert b.try_acquire() and b.try_acquire()
    assert not b.try_acquire()                  # window full
    t[0] = 61.0
    assert b.try_acquire()                      # window slid


def test_tiingo_daily_parses_raw_adjusted_and_actions(monkeypatch):
    # fixture has a 0.26 dividend on row 3 and a 4:1 split on row 4, so adjClose
    # diverges from close on the pre-action rows; a raw-vs-adjusted mixup downstream
    # (the risk series) cannot slip through
    src = TiingoSource(key="k-test")
    _patch_json(monkeypatch, src, _load("tiingo_daily.json"))
    res = src.fetch_daily("AAPL")
    assert res.ok and len(res.bars) == 4
    assert res.bars[-1].close == pytest.approx(78.4)        # raw post-split
    assert res.bars[-1].adj_close == pytest.approx(78.4)    # latest row: adj == raw
    assert res.bars[2].close == pytest.approx(312.06)       # raw pre-split
    assert res.bars[2].adj_close == pytest.approx(78.015)   # split-divided (4:1)
    assert res.bars[2].div_cash == pytest.approx(0.26)      # dividend row
    assert res.bars[3].split_factor == pytest.approx(4.0)   # split row
    # the dividend nudges the PRE-ex-date adjusted chain below close/4
    assert res.bars[1].adj_close == pytest.approx(77.49)
    assert res.bars[1].adj_close < 310.22 / 4.0
    assert res.bars[0].ts < res.bars[1].ts < res.bars[2].ts < res.bars[3].ts


def test_tiingo_without_key_is_needs_key():
    src = TiingoSource(key="")
    res = src.fetch_daily("AAPL")
    assert res.error.kind == SourceErrorKind.NEEDS_KEY
    assert "tiingo.com" in res.error.message


def test_tiingo_malformed_payload_is_a_value(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src, {"detail": "not a list"})
    res = src.fetch_daily("AAPL")
    assert not res.ok and res.error.kind == SourceErrorKind.BAD_DATA


def test_tiingo_network_failure_is_a_value(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src, urllib.error.URLError("down"))
    res = src.fetch_daily("AAPL")
    assert res.error.kind == SourceErrorKind.NETWORK


def test_tiingo_errors_are_redacted_of_the_key(monkeypatch):
    src = TiingoSource(key="TOPSECRET")
    _patch_json(monkeypatch, src, RuntimeError("x TOPSECRET y"))
    res = src.fetch_daily("AAPL")
    assert "TOPSECRET" not in res.error.message


def test_tiingo_iex_intraday_parses(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src, _load("tiingo_iex.json"))
    candles, err = src.fetch_intraday("AAPL", "1m")
    assert err is None and len(candles) == 3
    assert candles[-1].close == pytest.approx(311.0)


def test_tiingo_iex_paid_tier_403_degrades_to_a_value(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src,
                urllib.error.HTTPError("u", 403, "forbidden", {}, None))
    candles, err = src.fetch_intraday("AAPL", "1m")
    assert candles == () and err is not None               # caller: start at launch


# each adapter carries its own _error_for copy, so cross-adapter coverage does not protect these
def test_finnhub_timeout_is_typed(monkeypatch):
    src = FinnhubSource(key="k", budget=_budget())
    _patch_json(monkeypatch, src, OSError("timed out"))
    res = src.fetch_mark("AAPL")
    assert res.error.kind == SourceErrorKind.TIMEOUT


def test_tiingo_timeout_is_typed(monkeypatch):
    src = TiingoSource(key="k")
    _patch_json(monkeypatch, src, OSError("timed out"))
    res = src.fetch_daily("AAPL")
    assert res.error.kind == SourceErrorKind.TIMEOUT


def test_kraken_http_error_is_network_with_the_code(monkeypatch):
    src = KrakenSource()
    _patch_json(monkeypatch, src,
                urllib.error.HTTPError("u", 520, "cf", {}, None))
    out = src.fetch_mark_batch(["BTC/USD"])
    err = out["BTC/USD"].error
    assert err.kind == SourceErrorKind.NETWORK and "520" in err.message


def test_kraken_fetch_falls_back_to_the_last_close_when_no_mark(monkeypatch):
    # partial outage: OHLC bars arrive but the Ticker is unusable, so the mark
    # is assembled from the last close
    src = KrakenSource()
    def fake(url):
        if "OHLC" in url:
            return _load("kraken_ohlc.json")
        raise OSError("ticker down")
    monkeypatch.setattr(src, "_get_json", fake)
    res = src.fetch("BTC/USD", "1d")
    assert res.ok and res.quote.mark == pytest.approx(73541.8)  # last close
    assert len(res.candles) == 3


def test_bucket_opens_tracks_and_closes_on_the_boundary():
    closed, b = sampled_bars.update(None, "AAPL", "1m", 100.0, 60.0)
    assert closed is None and b.open == b.close == 100.0 and b.start_ts == 60.0
    closed, b = sampled_bars.update(b, "AAPL", "1m", 102.0, 70.0)   # same bucket
    assert closed is None and b.high == 102.0 and b.close == 102.0
    closed, b = sampled_bars.update(b, "AAPL", "1m", 99.0, 80.0)
    assert closed is None and b.low == 99.0
    closed, b = sampled_bars.update(b, "AAPL", "1m", 101.0, 120.0)  # next boundary
    assert closed is not None and closed.is_closed
    assert (closed.ts, closed.open, closed.high, closed.low, closed.close,
            closed.volume) == (60.0, 100.0, 102.0, 99.0, 99.0, 0.0)
    assert b.start_ts == 120.0 and b.open == 101.0


def test_gap_closes_the_open_bucket_exactly_once():
    _, b = sampled_bars.update(None, "AAPL", "1m", 100.0, 60.0)
    closed, b = sampled_bars.update(b, "AAPL", "1m", 105.0, 600.0)  # 9-minute gap
    assert closed is not None and closed.ts == 60.0                 # ONE bar, no filler
    assert b.start_ts == 600.0


def test_idle_market_never_advances_the_bucket():
    _, b = sampled_bars.update(None, "AAPL", "1m", 100.0, 60.0)
    for _ in range(10):                       # market closed: t never advances
        closed, b = sampled_bars.update(b, "AAPL", "1m", 100.0, 65.0)
        assert closed is None
    assert b.start_ts == 60.0                 # no after-hours flat bars


def test_out_of_order_mark_is_ignored():
    _, b = sampled_bars.update(None, "AAPL", "1m", 100.0, 120.0)
    closed, b2 = sampled_bars.update(b, "AAPL", "1m", 50.0, 30.0)
    assert closed is None and b2 == b


def test_bad_mark_or_ts_is_ignored():
    _, b = sampled_bars.update(None, "AAPL", "1m", 100.0, 60.0)
    for mark, ts in ((0.0, 70.0), (-5.0, 70.0), (100.0, 0.0), (100.0, -1.0)):
        closed, b2 = sampled_bars.update(b, "AAPL", "1m", mark, ts)
        assert closed is None and b2 == b


def _stock(monkeypatch, finn_payloads, tiingo_intraday=None):
    finn = FinnhubSource(key="k-test", budget=_budget())
    seq = list(finn_payloads)
    monkeypatch.setattr(finn, "_get_json",
                        lambda url: seq.pop(0) if len(seq) > 1 else seq[0])
    tii = TiingoSource(key=("k-test" if tiingo_intraday is not None else ""))
    if tiingo_intraday is not None:
        monkeypatch.setattr(tii, "_get_json", lambda url: tiingo_intraday)
    return StockSource(finnhub=finn, tiingo=tii)


def _q(c, t):
    return {"c": c, "t": t, "pc": c, "h": c, "l": c, "o": c}


def test_stock_source_accumulates_intraday_buckets(monkeypatch):
    src = _stock(monkeypatch, [_q(100.0, 60), _q(102.0, 70), _q(101.0, 130)],
                 tiingo_intraday=None)
    r1 = src.fetch("AAPL", "1m")
    assert r1.ok and r1.candles == ()           # first bucket forming
    r2 = src.fetch("AAPL", "1m")
    assert r2.candles == ()                     # still the same bucket
    r3 = src.fetch("AAPL", "1m")                # boundary crossed -> closed bar
    assert len(r3.candles) == 1
    assert r3.candles[0].high == pytest.approx(102.0)
    assert r3.candles[0].volume == 0.0          # the documented sampled field


def test_stock_source_merges_iex_backfill_when_available(monkeypatch):
    iex = _load("tiingo_iex.json")
    src = _stock(monkeypatch, [_q(312.0, 1765486622)], tiingo_intraday=iex)
    res = src.fetch("AAPL", "1m")
    assert res.ok and len(res.candles) == 3


def test_stock_source_keyless_finnhub_is_needs_key(monkeypatch):
    finn = FinnhubSource(key="", budget=_budget())
    src = StockSource(finnhub=finn, tiingo=TiingoSource(key=""))
    assert src.needs_key and src.history_needs_key
    res = src.fetch("AAPL", "1d")
    assert res.error.kind == SourceErrorKind.NEEDS_KEY


def test_stock_source_keyless_tiingo_still_samples_1d(monkeypatch):
    src = _stock(monkeypatch, [_q(100.0, 86400), _q(101.0, 86400 + 86400)],
                 tiingo_intraday=None)
    r1 = src.fetch("AAPL", "1d")
    assert r1.ok and r1.candles == ()           # day bucket forming
    r2 = src.fetch("AAPL", "1d")                # next day -> one sampled bar
    assert len(r2.candles) == 1 and r2.candles[0].volume == 0.0
