# Expected values are hand-derived from each formula in the comments so a
# non-author can reproduce them. EMA seeds at index n-1 with the SMA of the
# first n; RSI follows Wilder (1978), SMA-seeded.
from __future__ import annotations

import math

import numpy as np
import pytest

from mahad.data.models import Candle
from mahad.engine.indicators import (EMA, RSI, SMA, IndicatorSettings,
                                      bars_needed, clamp_period, compute, ema,
                                      sma, wilder_rsi)
from mahad.engine.snapshot import build_render_snapshot


def test_sma_basic_and_warmup():
    # closes 1..6, period 3:
    # idx0,1 -> NaN (fewer than 3 bars)
    # idx2 = mean(1,2,3)=2; idx3 = mean(2,3,4)=3; idx4=4; idx5=5
    out = sma([1, 2, 3, 4, 5, 6], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert list(out[2:]) == pytest.approx([2.0, 3.0, 4.0, 5.0])


def test_sma_period_equals_length_one_value():
    out = sma([4, 8, 12], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx(8.0)


def test_sma_period_greater_than_history_all_nan():
    out = sma([10, 20], 5)
    assert out.shape == (2,)
    assert np.all(np.isnan(out))


def test_ema_sma_seeded_alpha_half():
    # closes [10,12,11,13,15], period 3 -> alpha = 2/(3+1) = 0.5
    # idx0,1 -> NaN
    # idx2 (seed) = SMA(10,12,11) = 33/3 = 11.0
    # idx3 = 0.5*13 + 0.5*11.0 = 12.0
    # idx4 = 0.5*15 + 0.5*12.0 = 13.5
    out = ema([10, 12, 11, 13, 15], 3)
    assert math.isnan(out[0]) and math.isnan(out[1])
    assert out[2] == pytest.approx(11.0)
    assert out[3] == pytest.approx(12.0)
    assert out[4] == pytest.approx(13.5)


def test_ema_seed_equals_sma_of_first_n():
    closes = [3.0, 5.0, 2.0, 8.0, 6.0, 7.0]
    n = 4
    e = ema(closes, n)
    assert e[n - 1] == pytest.approx(np.mean(closes[:n]))


def test_ema_wrong_alpha_would_fail_this_vector():
    # catches the alpha = 2/(n-1) slip: for n=3 that is 1.0, giving idx3 = 13.0
    out = ema([10, 12, 11, 13, 15], 3)
    assert out[3] != pytest.approx(13.0)
    assert out[3] == pytest.approx(12.0)


def test_wilder_rsi_hand_computed_period_3():
    # closes = [10,11,10,11,12,11,12], period = 3
    # deltas into closes 1..6: +1,-1,+1,+1,-1,+1
    # gains = [1,0,1,1,0,1] losses = [0,1,0,0,1,0]
    # SMA seed over first 3 deltas -> lands on close index 3:
    # avg_gain = (1+0+1)/3 = 2/3; avg_loss = (0+1+0)/3 = 1/3
    # RS = 2 -> RSI = 100 - 100/3 = 200/3 ~ 66.66667 [idx 3]
    # Wilder smoothing avg_t = (avg_{t-1}*(n-1)+x_t)/n:
    # idx4 (+1): ag=(2/3*2+1)/3=7/9; al=(1/3*2+0)/3=2/9; RS=3.5
    # RSI = 100 - 200/9 = 700/9 ~ 77.77778 [idx 4]
    # idx5 (1): ag=(7/9*2+0)/3=14/27; al=(2/9*2+1)/3=13/27; RS=14/13
    # RSI = 100 - 1300/27 = 1400/27 ~ 51.85185 [idx 5]
    # idx6 (+1): ag=(14/27*2+1)/3=55/81; al=(13/27*2+0)/3=26/81; RS=55/26
    # RSI = 100 - 2600/81 = 5500/81 ~ 67.90123 [idx 6]
    out = wilder_rsi([10, 11, 10, 11, 12, 11, 12], 3)
    assert np.all(np.isnan(out[:3]))                          # need n+1=4 closes
    assert out[3] == pytest.approx(200 / 3)
    assert out[4] == pytest.approx(700 / 9)
    assert out[5] == pytest.approx(1400 / 27)
    assert out[6] == pytest.approx(5500 / 81)


def test_wilder_rsi_first_value_index_is_period():
    # first defined RSI sits at close index == period (needs period+1 closes)
    out = wilder_rsi(list(range(1, 30)), 14)
    assert np.all(np.isnan(out[:14]))
    assert not math.isnan(out[14])


def test_wilder_rsi_all_gains_is_100_all_losses_is_0_flat_is_50():
    assert wilder_rsi([1, 2, 3, 4, 5, 6, 7, 8], 3)[3:] == pytest.approx(100.0)
    assert wilder_rsi([8, 7, 6, 5, 4, 3, 2, 1], 3)[3:] == pytest.approx(0.0)
    flat = wilder_rsi([5, 5, 5, 5, 5, 5], 3)
    assert flat[3:] == pytest.approx(50.0)                                        # flat series -> neutral, by convention


def test_wilder_rsi_bounded_0_100_on_fixed_oscillating_series():
    rng = np.random.default_rng(1978)
    closes = 100 + np.cumsum(rng.normal(0, 1, size=200))
    out = wilder_rsi(closes, 14)
    defined = out[~np.isnan(out)]
    assert defined.size > 0
    assert np.all(defined >= 0.0) and np.all(defined <= 100.0)


def test_wilder_rsi_matches_textbook_reference_loop():
    # deliberately naive restatement of Wilder 1978, cross-checked against the engine
    def reference(closes, n):
        c = [float(v) for v in closes]
        out = [float("nan")] * len(c)
        gains, losses = [], []
        for i in range(1, len(c)):
            ch = c[i] - c[i - 1]
            gains.append(max(ch, 0.0))
            losses.append(max(-ch, 0.0))
        if len(c) < n + 1:
            return out
        ag = sum(gains[:n]) / n
        al = sum(losses[:n]) / n
        out[n] = 100.0 if al == 0 and ag != 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
        for i in range(n + 1, len(c)):
            ag = (ag * (n - 1) + gains[i - 1]) / n
            al = (al * (n - 1) + losses[i - 1]) / n
            out[i] = 100.0 if al == 0 and ag != 0 else (50.0 if al == 0 else 100 - 100 / (1 + ag / al))
        return out

    rng = np.random.default_rng(42)
    closes = (50 + np.cumsum(rng.normal(0, 0.8, size=80))).tolist()
    got = wilder_rsi(closes, 14)
    ref = reference(closes, 14)
    for g, r in zip(got, ref):
        if math.isnan(r):
            assert math.isnan(g)
        else:
            assert g == pytest.approx(r, rel=1e-12, abs=1e-9)


def test_bars_needed():
    assert bars_needed(SMA, 20, 19) == 1
    assert bars_needed(SMA, 20, 20) == 0
    assert bars_needed(EMA, 12, 0) == 12
    assert bars_needed(RSI, 14, 14) == 1          # RSI needs period+1 closes
    assert bars_needed(RSI, 14, 15) == 0
    assert bars_needed(RSI, 14, 100) == 0


def test_clamp_period_bounds():
    assert clamp_period(1) == 2
    assert clamp_period(20) == 20
    assert clamp_period(9999) == 400
    assert clamp_period("not-a-number") == 2       # junk coerces to MIN rather than raising


def test_compute_dispatch_matches_direct_calls():
    closes = [10, 11, 10, 11, 12, 11, 12]
    assert np.allclose(compute(SMA, closes, 3), sma(closes, 3), equal_nan=True)
    assert np.allclose(compute(EMA, closes, 3), ema(closes, 3), equal_nan=True)
    assert np.allclose(compute(RSI, closes, 3), wilder_rsi(closes, 3), equal_nan=True)


def _candles(symbol, closes, *, last_forming):
    out = []
    for i, c in enumerate(closes):
        is_closed = not (last_forming and i == len(closes) - 1)
        out.append(Candle(symbol=symbol, timeframe="1d", ts=float(i),
                           open=c, high=c, low=c, close=c, volume=1.0,
                           is_closed=is_closed))
    return out


def test_snapshot_indicators_exclude_the_forming_bar():
    # 7th bar is forming, so SMA(3) runs over the 6 closed closes only and the
    # forming 999 must not leak in
    closes = [1, 2, 3, 4, 5, 6, 999]
    settings = IndicatorSettings(sma_enabled=True, sma_period=3)
    snap = build_render_snapshot(_candles("AAPL", closes, last_forming=True),
                                 quote=None, settings=settings)
    assert snap.sma is not None
    last_ts, last_val = snap.sma.points[-1]
    assert last_val == pytest.approx(5.0)              # mean(4,5,6)
    assert snap.closed_count == 6


def test_snapshot_indicator_needs_more_bars_when_period_exceeds_history():
    closes = [10, 11, 12]
    settings = IndicatorSettings(rsi_enabled=True, rsi_period=14)
    snap = build_render_snapshot(_candles("AAPL", closes, last_forming=False),
                                 quote=None, settings=settings)
    assert snap.rsi is not None
    assert snap.rsi.points == ()
    assert snap.rsi.needs_more == 12                   # 14+1 - 3
