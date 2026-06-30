# every expected value is worked out by hand in the comments so a non-author can check it
from __future__ import annotations

from math import sqrt

import pytest

from mahad.engine.risk import (
    ValueSample, exposure, simple_returns, volatility, max_drawdown,
    periods_per_year, PERIODS_PER_YEAR, VOL_WINDOW,
)


# demo end-state: AAPL 100 @ 312.06 (31,206.00) + BTC/USDT 0.30 @ 73,541.80 (22,062.54),
# cash 46,460.00 -> positions 53,268.54, portfolio 99,728.54
_POS_VALUE = 53_268.54
_PORT_VALUE = 99_728.54
_AAPL_VALUE = 31_206.00
_BTC_VALUE = 22_062.54


def test_exposure_overall_fraction_and_abs():
    e = exposure(_POS_VALUE, _PORT_VALUE)
    assert e.defined and not e.out_of_range
    assert e.abs_value == pytest.approx(53_268.54)
    # 53,268.54 / 99,728.54 = 0.534135...
    assert e.pct == pytest.approx(0.534135, abs=1e-6)
    assert f"{e.pct * 100:.2f}%" == "53.41%"


def test_exposure_per_position_sums_to_overall():
    overall = exposure(_POS_VALUE, _PORT_VALUE).pct
    aapl = exposure(_AAPL_VALUE, _PORT_VALUE).pct      # 31,206.00 / 99,728.54 = 0.312909
    btc = exposure(_BTC_VALUE, _PORT_VALUE).pct        # 22,062.54 / 99,728.54 = 0.221226
    assert aapl == pytest.approx(0.312909, abs=1e-6)
    assert btc == pytest.approx(0.221226, abs=1e-6)
    assert aapl + btc == pytest.approx(overall)        # same denominator, so they sum
    assert f"{aapl*100:.2f}%" == "31.29%" and f"{btc*100:.2f}%" == "22.12%"


def test_exposure_undefined_when_value_non_positive():
    assert exposure(10.0, 0.0).defined is False        # portfolio_value <= 0 -> "-"
    assert exposure(10.0, 0.0).pct is None
    assert exposure(10.0, -5.0).defined is False


def test_exposure_out_of_range_flag_both_bounds():
    assert exposure(110.0, 100.0).out_of_range is True    # 1.10 > 1
    assert exposure(-10.0, 100.0).out_of_range is True    # -0.10 < 0, defensive lower bound
    assert exposure(53.0, 100.0).out_of_range is False


# returns and volatility
def _samples(values, stale_idx=()):
    return [ValueSample(ts=float(i), value=float(v), stale=(i in stale_idx))
            for i, v in enumerate(values)]


def test_simple_returns_basic():
    # [100, 110, 99] -> 110/100-1 = 0.10, 99/110-1 = -0.10
    r, skipped = simple_returns(_samples([100, 110, 99]))
    assert r == pytest.approx([0.10, -0.10])
    assert skipped is False


def test_volatility_ddof1_per_period_and_annualised():
    # returns [0.10, -0.10], mean 0, sample var (ddof=1) = (0.1^2 + 0.1^2)/(2-1) = 0.02;
    # ddof=0 would instead give 10.00%
    r, _ = simple_returns(_samples([100, 110, 99]))
    sigma = sqrt(0.02)
    v1d = volatility(r, "1d")
    assert v1d.defined and v1d.n_returns == 2
    assert v1d.per_period_pct == pytest.approx(sigma * 100.0)          # 14.1421%
    # assert the annualisation FORMULA, not a literal
    assert v1d.annualised_pct == pytest.approx(sigma * sqrt(365) * 100.0)   # ~270.18%
    assert volatility(r, "1h").annualised_pct == pytest.approx(sigma * sqrt(8760) * 100.0)   # ~1323.6%
    assert volatility(r, "1m").annualised_pct == pytest.approx(sigma * sqrt(525600) * 100.0)  # ~10252.7%


def test_volatility_undefined_until_two_returns():
    assert volatility([], "1d").defined is False
    one, _ = simple_returns(_samples([100, 110]))
    assert len(one) == 1 and volatility(one, "1d").defined is False
    two, _ = simple_returns(_samples([100, 110, 99]))                  # two returns -> defined
    assert volatility(two, "1d").defined is True


def test_volatility_rolling_window_cap_min_available_30():
    # two big leading returns then 30 small ones; N=30 drops the big pair, so the windowed
    # sigma matches the last-30 sigma
    small = [0.01, -0.01] * 15                                         # 30 returns, mean 0
    returns32 = [9.0, 9.0] + small
    windowed = volatility(returns32, "1d", window=30)
    last30_only = volatility(small, "1d", window=30)
    assert windowed.n_returns == 30
    assert windowed.per_period_pct == pytest.approx(last30_only.per_period_pct)
    # not the all-history sigma; the two 9.0s would dominate
    allhist = volatility(returns32, "1d", window=100)
    assert windowed.per_period_pct != pytest.approx(allhist.per_period_pct)


def test_returns_skipped_on_stale_sample():
    # a stale middle sample drops both returns touching it
    r, skipped = simple_returns(_samples([100, 110, 99], stale_idx={1}))
    assert r == [] and skipped is True
    assert volatility(r, "1d").defined is False


def test_returns_skipped_on_non_positive_sample():
    # a zero middle value breaks the chain just like a stale sample
    r, skipped = simple_returns(_samples([100, 0, 99]))
    assert r == [] and skipped is True


def test_periods_per_year_constants():
    assert PERIODS_PER_YEAR == {"1m": 525_600, "1h": 8_760, "1d": 365}
    assert periods_per_year("1d") == 365 and periods_per_year("1h") == 8_760
    assert periods_per_year("1m") == 525_600
    assert periods_per_year("???") == 365                             # unknown falls back to 1d
    assert VOL_WINDOW == 30


# maximum drawdown
def test_max_drawdown_core_vector():
    # values 100,120,90,110 -> running max 100,120,120,120 -> worst dd 90/120-1 = -0.25
    s = [ValueSample(0, 100), ValueSample(1, 120), ValueSample(2, 90), ValueSample(3, 110)]
    dd = max_drawdown(s, peak_value=100.0, peak_ts=0.0)
    assert dd.max_dd_pct == pytest.approx(-25.0)
    assert dd.trough_ts == 2 and dd.peak_ts == 1        # running-max 120 was set at ts1


def test_max_drawdown_flat_rising_is_zero():
    s = [ValueSample(0, 100), ValueSample(1, 110), ValueSample(2, 120)]
    dd = max_drawdown(s, peak_value=100.0, peak_ts=0.0)
    assert dd.max_dd_pct == pytest.approx(0.0)
    assert dd.trough_ts is None                          # never below running max


def test_max_drawdown_seeded_persisted_peak_survives_capping():
    # true peak 120 rolled off the window; only [90, 110] remain, but the persisted peak
    # 120 @ ts0 seeds running_max, so drawdown is still -25%
    s = [ValueSample(2, 90), ValueSample(3, 110)]
    dd = max_drawdown(s, peak_value=120.0, peak_ts=0.0)
    assert dd.max_dd_pct == pytest.approx(-25.0)
    assert dd.peak_ts == 0.0 and dd.trough_ts == 2       # peak_ts is the seeded ts


def test_max_drawdown_stale_sample_registers_trough_but_excluded_from_returns():
    # a stale value 80 still deepens the value-based drawdown: 80/120-1 = -33.3%
    s = [ValueSample(0, 120, stale=False), ValueSample(1, 80, stale=True)]
    dd = max_drawdown(s, peak_value=120.0, peak_ts=0.0)
    assert dd.max_dd_pct == pytest.approx(-100.0 / 3.0)  # -33.333%
    assert dd.trough_ts == 1
    # but it is excluded from the returns series
    r, skipped = simple_returns(s)
    assert r == [] and skipped is True


def test_max_drawdown_empty_is_zero_undefined():
    dd = max_drawdown([], peak_value=None, peak_ts=None)
    assert dd.defined is False and dd.max_dd_pct == pytest.approx(0.0)
