from __future__ import annotations

import datetime as dt

from mahad.data.models import Candle
from mahad.engine.resample import RESAMPLE_TIMEFRAMES, resample_daily_candles

UTC = dt.timezone.utc


def _day(y, m, d, o, h, lo, c, v=10.0):
    ts = dt.datetime(y, m, d, tzinfo=UTC).timestamp()
    return Candle(symbol="AAPL", timeframe="1d", ts=ts, open=o, high=h, low=lo,
                  close=c, volume=v, is_closed=True)


def test_non_resample_timeframe_returns_input_unchanged():
    bars = [_day(2026, 1, 5, 1, 2, 0.5, 1.5)]
    assert resample_daily_candles(bars, "1d") == tuple(bars)
    assert resample_daily_candles(bars, "1h") == tuple(bars)


def test_empty_series():
    assert resample_daily_candles([], "1w") == ()
    assert resample_daily_candles([], "1mo") == ()


def test_monthly_ohlc_aggregation_and_trailing_forming():
    # Jan closed, Feb still forming
    bars = [_day(2026, 1, 5, 10, 12, 9, 11, 1),
            _day(2026, 1, 6, 11, 15, 10, 13, 2),
            _day(2026, 1, 7, 13, 14, 8, 9, 3),
            _day(2026, 2, 2, 9, 20, 8, 18, 4),
            _day(2026, 2, 3, 18, 19, 17, 17, 5)]
    out = resample_daily_candles(bars, "1mo")
    assert len(out) == 2
    jan, feb = out
    assert jan.is_closed is True and feb.is_closed is False
    assert (jan.open, jan.high, jan.low, jan.close, jan.volume) == (10, 15, 8, 9, 6)
    assert (feb.open, feb.high, feb.low, feb.close, feb.volume) == (9, 20, 8, 17, 9)
    assert all(b.timeframe == "1mo" for b in out)


def test_weekly_buckets_by_iso_week():
    # both 2026-01-05 and 2026-01-12 are Mondays, so they start adjacent ISO weeks
    bars = [_day(2026, 1, 5, 1, 2, 1, 2), _day(2026, 1, 6, 2, 3, 1, 2),
            _day(2026, 1, 12, 3, 4, 2, 3), _day(2026, 1, 13, 3, 5, 2, 4)]
    out = resample_daily_candles(bars, "1w")
    assert len(out) == 2
    assert out[0].is_closed is True and out[1].is_closed is False
    assert out[0].high == 3 and out[1].high == 5


def test_three_day_windows_of_three_consecutive_bars():
    bars = [_day(2026, 1, d, 1, d, 0, d) for d in range(5, 12)]
    out = resample_daily_candles(bars, "3d")
    assert len(out) == 3                       # windows [5,6,7] [8,9,10] [11]
    assert [b.is_closed for b in out] == [True, True, False]
    assert out[0].high == 7 and out[1].high == 10 and out[2].high == 11


def test_resample_timeframes_constant():
    assert RESAMPLE_TIMEFRAMES == ("3d", "1w", "1mo")
