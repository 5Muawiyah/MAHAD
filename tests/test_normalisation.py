# normalisation against recorded fixtures, no live network
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mahad.config import is_stale, staleness_window
from mahad.data.models import Candle, Quote
from mahad.data.kraken_source import mark_from_kraken_ticker
from mahad.data.source import dedupe_sort_candles, normalize_ohlcv

FIX = Path(__file__).parent / "fixtures"


def _load(name: str):
    return json.loads((FIX / name).read_text())


def test_quote_shape_and_frozen():
    q = Quote(symbol="AAPL", mark=123.45, ts=1_700_000_000.0, source="finnhub")
    assert (q.symbol, q.mark, q.ts, q.source, q.stale) == \
           ("AAPL", 123.45, 1_700_000_000.0, "finnhub", False)
    with pytest.raises(Exception):
        q.mark = 1.0


def test_candle_shape_and_frozen():
    c = Candle("BTC/USDT", "1d", 1_700_000_000.0, 1.0, 2.0, 0.5, 1.5, 9.0)
    assert (c.symbol, c.timeframe, c.open, c.high, c.low, c.close, c.volume) == \
           ("BTC/USDT", "1d", 1.0, 2.0, 0.5, 1.5, 9.0)
    assert c.is_closed is True
    with pytest.raises(Exception):
        c.close = 2.0


def test_crypto_mark_prefers_the_last_trade():
    e = _load("providers/kraken_ticker_batch.json")["result"]["XXBTZUSD"]
    assert mark_from_kraken_ticker(e) == pytest.approx(73541.8)


def test_crypto_mark_falls_back_to_bid_ask_mid():
    e = dict(_load("providers/kraken_ticker_batch.json")["result"]["XXBTZUSD"])
    e["c"] = ["0", "0"]
    assert mark_from_kraken_ticker(e) == pytest.approx((73541.0 + 73544.1) / 2.0)


def test_crypto_mark_none_when_nothing_usable():
    assert mark_from_kraken_ticker({"c": ["0", "0"], "b": None, "a": None}) is None
    assert mark_from_kraken_ticker({"c": ["-5", "1"]}) is None    # non-positive last is invalid
    assert mark_from_kraken_ticker(None) is None
    assert mark_from_kraken_ticker({}) is None


def test_ohlcv_normalises_sorts_dedupes_and_marks_forming():
    raw = _load("ohlcv_ms_rows.json")                                # rows are [ms, o,h,l,c,v]
    rows = [(b[0] / 1000.0, b[1], b[2], b[3], b[4], b[5]) for b in raw]
    candles = normalize_ohlcv("BTC/USDT", "1d", rows)

    assert len(candles) == 3                                          # 4 raw -> 3 unique
    ts = [c.ts for c in candles]
    assert ts == sorted(ts) and len(set(ts)) == 3
    mid = [c for c in candles if c.ts == 1_700_000_000.0][0]
    assert mid.close == pytest.approx(100.7)                          # duplicate ts: last write wins
    assert all(c.symbol == "BTC/USDT" and c.timeframe == "1d" for c in candles)
    assert candles[-1].is_closed is False                            # newest bar is still forming
    assert all(c.is_closed for c in candles[:-1])


def test_dedupe_key_is_symbol_timeframe_ts():
    a = Candle("X", "1d", 100.0, 1, 1, 1, 1, 1)
    b = Candle("X", "1h", 100.0, 2, 2, 2, 2, 2)    # same ts but different timeframe stays distinct
    c = Candle("X", "1d", 100.0, 3, 3, 3, 3, 3)    # same key as a, so it collapses
    out = dedupe_sort_candles([a, b, c])
    assert len(out) == 2
    one_d = [x for x in out if x.timeframe == "1d"][0]
    assert one_d.open == 3


def test_history_cap_keeps_most_recent():
    rows = [(float(i), 1, 1, 1, float(i), 1) for i in range(10)]
    capped = normalize_ohlcv("X", "1d", rows, 4)
    assert len(capped) == 4
    assert [c.ts for c in capped] == [6.0, 7.0, 8.0, 9.0]


def test_staleness_window_floor_and_multiple():
    assert staleness_window(5) == 15.0
    assert staleness_window(2) == 15.0      # 3*2=6, lifted to the 15s floor
    assert staleness_window(10) == 30.0     # 3*10 clears the floor


def test_is_stale_boundary():
    now = 1_000_000.0
    w = staleness_window(5)
    assert is_stale(now - (w - 0.01), now=now, poll_interval_s=5) is False  # just inside
    assert is_stale(now - w,          now=now, poll_interval_s=5) is False  # at the window is not yet stale
    assert is_stale(now - (w + 0.01), now=now, poll_interval_s=5) is True   # just past
    assert is_stale(None, now=now) is True                                  # missing ts counts as stale
