# Expected values are hand-derived inline so a non-author can reproduce them.
# Vectors are chosen to fail at least one assertion against a plausible wrong
# implementation (equality fires, strict/non-strict swapped, fast/slow swapped,
# forming bar included, RSI off the live mark, no-replay missing).
from __future__ import annotations

import math

import pytest

from mahad.data.models import Candle
from mahad.engine.signals import (DOWN, PRICE_SMA_CROSS, PRICE_THRESHOLD,
                                   RSI_THRESHOLD, SMA_EMA_CROSS, UP, AlertSpec,
                                   bars_adjacent, bars_needed_for,
                                   canonical_params, cross_at, cross_fired,
                                   crossover_d, evaluate_alert,
                                   evaluate_crossover, evaluate_threshold,
                                   scan_crossover, summary, threshold_fired,
                                   threshold_value, validate_params)

DAY = 86400.0


def _spec(condition_type, params, direction=UP, **kw):
    return AlertSpec(symbol="AAPL", condition_type=condition_type, params=params,
                     direction=direction, **kw)


def test_validate_params_canonical_and_ranges():
    ok, p, _ = validate_params(PRICE_SMA_CROSS, {"sma_period": 20})
    assert ok and p == {"sma_period": 20}
    ok, p, _ = validate_params(PRICE_SMA_CROSS, {"sma_period": "not-a-number"})
    assert ok and p == {"sma_period": 2}  # junk clamps to MIN (never raises)

    ok, p, _ = validate_params(RSI_THRESHOLD, {"rsi_period": 14, "level": 70})
    assert ok and p == {"level": 70.0, "rsi_period": 14}
    assert validate_params(RSI_THRESHOLD, {"rsi_period": 14, "level": 150})[0] is False  # >100
    assert validate_params(PRICE_THRESHOLD, {"level": 0})[0] is False  # not > 0
    assert validate_params("nonsense", {})[0] is False


def test_canonical_params_defeats_150_vs_150_point_0():
  # 150 and 150.0 must canonicalise identically or the duplicate-block check
  # is defeated by numeric formatting
    _, a, _ = validate_params(PRICE_THRESHOLD, {"level": 150})
    _, b, _ = validate_params(PRICE_THRESHOLD, {"level": 150.0})
    assert canonical_params(a) == canonical_params(b) == '{"level":150.0}'


def test_cross_fired_up_and_down_boundaries():
  # up: d_prev <= 0 and d_curr > 0
    assert cross_fired(-0.5, 3.0, UP) is True  # negative -> positive
    assert cross_fired(0.0, 3.0, UP) is True  # zero counts as the <=0 "before"
    assert cross_fired(-0.5, 0.0, UP) is False  # negative -> zero: equality is NOT a cross
    assert cross_fired(0.0, 0.0, UP) is False
    assert cross_fired(3.0, 1.0, UP) is False
  # down is symmetric: d_prev >= 0 and d_curr < 0
    assert cross_fired(1.0, -2.0, DOWN) is True
    assert cross_fired(0.0, -2.0, DOWN) is True
    assert cross_fired(1.0, 0.0, DOWN) is False  # equality is NOT a cross
  # a zero-touch then rebound from the firing side still fires (the <=0 boundary)
    assert cross_fired(0.0, 2.0, UP) is True  # the (0 -> +2) step of [+1, 0, +2]


def test_cross_fired_nan_is_never_a_cross_both_directions():
    assert cross_fired(float("nan"), 3.0, UP) is False
    assert cross_fired(float("nan"), -3.0, DOWN) is False
    assert cross_fired(2.0, float("nan"), UP) is False


def test_bars_adjacent_intraday_hole_blocks_daily_weekend_ok():
  # 1m: interval 60s, factor 1.5 -> adjacent iff 0 < dt <= 90s
    assert bars_adjacent(0.0, 60.0, "1m") is True
    assert bars_adjacent(0.0, 120.0, "1m") is False  # a 2-interval hole
    assert bars_adjacent(60.0, 0.0, "1m") is False  # out-of-order / dt <= 0
  # consecutive fetched daily bars count as adjacent, no calendar: Fri -> Mon is 3 days
    assert bars_adjacent(2 * DAY, 5 * DAY, "1d") is True


def test_price_sma_crossover_up_fires_down_does_not():
  # closes [10,10,10,9,14], SMA(3):
  # idx2 = mean(10,10,10) = 10 -> d = 10 - 10 = 0
  # idx3 = mean(10,10,9) = 29/3 -> d = 9 - 9.667 = -0.667
  # idx4 = mean(10,9,14) = 11 -> d = 14 - 11 = 3
  # last pair (idx3, idx4): d_prev = -0.667 <= 0, d_curr = 3 > 0 -> UP fires; DOWN does not.
    closes = [10.0, 10.0, 10.0, 9.0, 14.0]
    ts = [0.0, 60.0, 120.0, 180.0, 240.0]
    d = crossover_d(_spec(PRICE_SMA_CROSS, {"sma_period": 3}), closes)
    assert d[3] == pytest.approx(9.0 - 29.0 / 3) and d[4] == pytest.approx(3.0)
    assert evaluate_crossover(_spec(PRICE_SMA_CROSS, {"sma_period": 3}, UP),
                              closes, ts, "1m") is not None
    assert evaluate_crossover(_spec(PRICE_SMA_CROSS, {"sma_period": 3}, DOWN),
                              closes, ts, "1m") is None


def test_crossover_warmup_boundary_then_real_cross():
  # first defined d has a NaN predecessor: it is the baseline, not a cross, even
  # when positive. a genuine cross after it does fire.
  # closes [8,12,9,13], SMA(2): sma=[nan,10,10.5,11]; d = close - sma = [nan, 2, -1.5, 2]
    closes = [8.0, 12.0, 9.0, 13.0]
    ts = [0.0, 60.0, 120.0, 180.0]
    spec = _spec(PRICE_SMA_CROSS, {"sma_period": 2}, UP)
    d = crossover_d(spec, closes)
    assert math.isnan(d[0]) and d[1] == pytest.approx(2.0)
    assert cross_at(spec, d, ts, 1, "1m", 0.0) is None  # first defined d (NaN predecessor) -> no fire
    assert cross_at(spec, d, ts, 3, "1m", 0.0) is not None  # genuine cross (1.5 -> 2) fires


def test_crossover_no_signal_across_a_data_gap_intraday():
  # Same up-cross at idx3, but ts has a 2-interval hole between idx2 and idx3.
    closes = [8.0, 12.0, 9.0, 13.0]
    ts_gap = [0.0, 60.0, 120.0, 240.0]  # 240 - 120 = 120s = 2 * interval (hole)
    spec = _spec(PRICE_SMA_CROSS, {"sma_period": 2}, UP)
    d = crossover_d(spec, closes)
    assert cross_at(spec, d, ts_gap, 3, "1m", 0.0) is None  # no signal across the gap
    ts_daily = [0.0, DAY, 2 * DAY, 5 * DAY]  # Fri -> Mon (3-day step) is adjacent
    assert cross_at(spec, d, ts_daily, 3, "1d", 0.0) is not None  # daily fires


def test_sma_ema_crossover_direction_is_decisive_against_a_swap():
  # d = SMA - EMA (fast=SMA, slow=EMA). Arm UP, assert it fires; assert a DOWN
  # alert on the SAME pair does NOT fire (a fast/slow swap flips both -> decisive).
  # closes [10,11,12,13,14,10] (rising then a drop), period 3, alpha=2/(3+1)=0.5:
  # SMA: idx4 = mean(12,13,14) = 13; idx5 = mean(13,14,10) = 12.333
  # EMA (SMA-seeded at idx2=11): idx3=12, idx4=13, idx5 = 0.5*10 + 0.5*13 = 11.5
  # d = SMA - EMA: idx4 = 13 - 13 = 0; idx5 = 12.333 - 11.5 = 0.833 -> UP cross (0 -> +0.833)
    closes = [10.0, 11.0, 12.0, 13.0, 14.0, 10.0]
    ts = [i * 60.0 for i in range(len(closes))]
    spec_up = _spec(SMA_EMA_CROSS, {"sma_period": 3, "ema_period": 3}, UP)
    d = crossover_d(spec_up, closes)
    assert d[-2] <= 0.0 < d[-1]  # the pair really is an up-cross
    assert evaluate_crossover(spec_up, closes, ts, "1m") is not None
    spec_down = _spec(SMA_EMA_CROSS, {"sma_period": 3, "ema_period": 3}, DOWN)
    assert evaluate_crossover(spec_down, closes, ts, "1m") is None


def test_crossover_uses_closed_closes_only_forming_bar_excluded():
  # worker feeds [c.close for c in candles if c.is_closed], so a wild forming bar
  # must not move the price-cross decision. close=5 here would flip it but is excluded.
    closed = [10.0, 10.0, 10.0, 9.0, 14.0]
    candles = [Candle("AAPL", "1m", float(i) * 60, c, c, c, c, 1.0, is_closed=True)
               for i, c in enumerate(closed)]
    candles.append(Candle("AAPL", "1m", 5 * 60.0, 5, 5, 5, 5, 1.0, is_closed=False))  # forming, wild
    closed_closes = [c.close for c in candles if c.is_closed]
    closed_ts = [c.ts for c in candles if c.is_closed]
    assert closed_closes == closed  # forming bar excluded
    spec = _spec(PRICE_SMA_CROSS, {"sma_period": 3}, UP)
    assert evaluate_crossover(spec, closed_closes, closed_ts, "1m") is not None


def test_price_threshold_level_triggered_and_demo_recipe():
  # arm "price >= level" while the mark is ALREADY above -> fires now.
    up = _spec(PRICE_THRESHOLD, {"level": 100.0}, UP)
    assert evaluate_threshold(up, [], 150.0, now=1.0) is not None  # 150 >= 100
    assert evaluate_threshold(up, [], 99.0, now=1.0) is None  # 99 < 100
  # the demo recipe: a hair below the live mark fires within one poll
    hair = _spec(PRICE_THRESHOLD, {"level": 149.9}, UP)
    assert evaluate_threshold(hair, [], 150.0, now=1.0) is not None
  # down (at or below)
    dn = _spec(PRICE_THRESHOLD, {"level": 100.0}, DOWN)
    assert evaluate_threshold(dn, [], 99.0, now=1.0) is not None
    assert evaluate_threshold(dn, [], 101.0, now=1.0) is None
    assert evaluate_threshold(up, [], None, now=1.0) is None  # no mark -> no fire


def test_rsi_threshold_uses_latest_closed_bar_rsi():
  # closes [10,11,10,11,12,11,12], RSI(3) last value (idx6) = 5500/81 ~ 67.901
  # (hand-derived in test_indicators.py). fires off that closed value, never the
  # live mark, so the wild mark argument is irrelevant.
    closes = [10.0, 11.0, 10.0, 11.0, 12.0, 11.0, 12.0]
    val = threshold_value(_spec(RSI_THRESHOLD, {"rsi_period": 3, "level": 0}), closes, mark=99999.0)
    assert val == pytest.approx(5500 / 81)
    assert evaluate_threshold(_spec(RSI_THRESHOLD, {"rsi_period": 3, "level": 60}, UP),
                              closes, 99999.0, now=1.0) is not None  # 67.9 >= 60
    assert evaluate_threshold(_spec(RSI_THRESHOLD, {"rsi_period": 3, "level": 70}, UP),
                              closes, 99999.0, now=1.0) is None  # 67.9 < 70


def test_rsi_threshold_warmup_returns_no_value():
  # RSI(3) needs period+1 = 4 closes; with 3 it is all-NaN, so threshold_value
  # is None and stays None every poll (closed-bar RSI only, never the forming bar)
    closes = [10.0, 11.0, 12.0]
    spec = _spec(RSI_THRESHOLD, {"rsi_period": 3, "level": 50}, UP)
    assert threshold_value(spec, closes, mark=50.0) is None
    assert evaluate_threshold(spec, closes, 50.0, now=1.0) is None
    assert evaluate_threshold(spec, closes, 50.0, now=2.0) is None  # stable across polls


def test_threshold_fired_primitive():
    assert threshold_fired(70.0, 60.0, UP) is True
    assert threshold_fired(60.0, 60.0, UP) is True  # at-or-above
    assert threshold_fired(59.0, 60.0, UP) is False
    assert threshold_fired(30.0, 30.0, DOWN) is True  # at-or-below
    assert threshold_fired(None, 30.0, DOWN) is False


def test_evaluate_alert_one_shot_then_rearm():
    spec = _spec(PRICE_THRESHOLD, {"level": 100.0}, UP, id=1, armed=True)
    ev, fired = evaluate_alert(spec, closed_closes=[], closed_ts=[], mark=150.0,
                               timeframe="1m", new_indices=[], now=10.0)
    assert ev is not None and fired.armed is False and fired.fired_at == 10.0  # fires once, disarms
    ev2, again = evaluate_alert(fired, closed_closes=[], closed_ts=[], mark=150.0,
                                timeframe="1m", new_indices=[], now=11.0)
    assert ev2 is None and again is fired  # disarmed -> no re-fire
    rearmed = AlertSpec("AAPL", PRICE_THRESHOLD, {"level": 100.0}, UP, id=1, armed=True)
    ev3, _ = evaluate_alert(rearmed, closed_closes=[], closed_ts=[], mark=150.0,
                            timeframe="1m", new_indices=[], now=12.0)
    assert ev3 is not None  # re-arm fires again


def test_scan_crossover_fires_exactly_once_on_first_crossing_over_a_gap():
  # three bars close over a poll gap; the up-cross is on the first newly-closed
  # bar. scan_crossover returns the FIRST event only (one-shot bound within catch-up).
  # closes [8,12,9,13,8,14], SMA(2) d = [nan, 2, -1.5, 2, -2.5, 3]
  # up-crosses at idx3 (1.5 -> 2) AND idx5 (2.5 -> 3); scan returns idx3 (the first).
    closes = [8.0, 12.0, 9.0, 13.0, 8.0, 14.0]
    ts = [i * 60.0 for i in range(len(closes))]
    spec = _spec(PRICE_SMA_CROSS, {"sma_period": 2}, UP)
    d = crossover_d(spec, closes)
    ev = scan_crossover(spec, d, ts, [3, 4, 5], "1m", now=1.0)
    assert ev is not None and ev.value == pytest.approx(2.0)  # the idx3 crossing, not idx5


def test_no_false_fire_when_no_new_bars_for_crossover():
  # armed mid-session with no newly-closed bars (new_indices empty): waits for a
  # close, does not fire off the last closed pair even though it is an up-cross
    closes = [10.0, 10.0, 10.0, 9.0, 14.0]
    ts = [i * 60.0 for i in range(len(closes))]
    spec = _spec(PRICE_SMA_CROSS, {"sma_period": 3}, UP, armed=True)
    ev, same = evaluate_alert(spec, closed_closes=closes, closed_ts=ts, mark=14.0,
                              timeframe="1m", new_indices=[], now=1.0)
    assert ev is None and same.armed is True


def test_summary_strings_are_dash_clean_and_descriptive():
    assert summary(_spec(PRICE_THRESHOLD, {"level": 150.0}, UP)) == "price >= 150"
    assert summary(_spec(RSI_THRESHOLD, {"rsi_period": 14, "level": 70.0}, DOWN)) == "RSI(14) <= 70"
    assert summary(_spec(PRICE_SMA_CROSS, {"sma_period": 20}, UP)) == "price crosses above SMA(20)"
    s = summary(_spec(SMA_EMA_CROSS, {"sma_period": 20, "ema_period": 12}, DOWN))
    assert s == "SMA(20) crosses below EMA(12)"
    for txt in (summary(_spec(PRICE_THRESHOLD, {"level": 1.0}, UP)),):
        assert "\u2014" not in txt and "\u2013" not in txt  # no em / en dash (escape form)


def test_bars_needed_for_drives_dialog_warmup_note():
    assert bars_needed_for(PRICE_THRESHOLD, {"level": 1.0}, 0) == 0  # no indicator
    assert bars_needed_for(PRICE_SMA_CROSS, {"sma_period": 20}, 19) == 1
    assert bars_needed_for(RSI_THRESHOLD, {"rsi_period": 14}, 10) == 5  # needs period+1 = 15
    assert bars_needed_for(SMA_EMA_CROSS, {"sma_period": 20, "ema_period": 12}, 15) == 5
