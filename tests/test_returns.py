from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import pytest

from mahad.engine import returns as R


def _ts(d: dt.date) -> float:
    return dt.datetime(d.year, d.month, d.day,
                       tzinfo=dt.timezone.utc).timestamp()


# hand-checked reference values, the answer key
def test_check_n_portfolio_day_return_is_exact():
    # w = [0.6, 0.4], asset returns [0.01, -0.005] -> 0.0040
    out = R.single_day_return({"A": 0.6, "B": 0.4}, {"A": 0.01, "B": -0.005})
    assert out.value == pytest.approx(0.0040, abs=1e-12)
    assert out.included == ("A", "B") and out.excluded == ()
    assert out.coverage_weight == pytest.approx(1.0)


def test_check_m_risk_free_deannualisation_is_exact():
    # annual 5.25% -> rf_daily = 0.00020833 (2.0833 bp/day)
    rf = R.rf_daily_from_annual_pct(5.25)
    assert rf == pytest.approx(0.00020833333333, rel=1e-9)
    assert rf * 1e4 == pytest.approx(2.0833, abs=5e-5)
    assert R.rf_daily_from_annual_pct(None) is None


def test_weekend_bars_fold_into_monday():
    fri = dt.date(2026, 6, 5)              # Friday
    sat, sun, mon = (dt.date(2026, 6, 6), dt.date(2026, 6, 7),
                     dt.date(2026, 6, 8))
    rows = [(_ts(fri), 100.0), (_ts(sat), 101.0), (_ts(sun), 99.0),
            (_ts(mon), 104.0)]
    aligned = R.align_daily_closes(rows)
    assert aligned == [(fri, 100.0), (mon, 104.0)]          # weekend dropped
    rets = R.simple_returns_by_date(aligned)
    assert rets == [(mon, pytest.approx(0.04))]             # the move folds


def test_holiday_bar_folds_into_the_next_trading_day():
    # 2026-01-01 (Thursday) is a full-day NYSE holiday
    nye, holiday, jan2 = (dt.date(2025, 12, 31), dt.date(2026, 1, 1),
                          dt.date(2026, 1, 2))
    assert R.is_us_trading_day(holiday) is False
    assert R.is_us_trading_day(jan2) is True
    rows = [(_ts(nye), 200.0), (_ts(holiday), 210.0), (_ts(jan2), 198.0)]
    aligned = R.align_daily_closes(rows)
    assert [d for d, _ in aligned] == [nye, jan2]
    rets = R.simple_returns_by_date(aligned)
    assert rets[0][1] == pytest.approx(198.0 / 200.0 - 1.0)


def test_align_keeps_last_duplicate_and_drops_unusable():
    d = dt.date(2026, 6, 8)
    rows = [(_ts(d), 100.0), (_ts(d) + 60.0, 105.0),        # same UTC date
            (_ts(dt.date(2026, 6, 9)), -3.0),               # non-positive
            (_ts(dt.date(2026, 6, 10)), "junk")]            # unusable
    aligned = R.align_daily_closes(rows)
    assert aligned == [(d, 105.0)]


def test_current_weights_include_cash_in_the_denominator():
    w = R.current_weights([("AAPL", 100.0, 312.06), ("BTC/USD", 0.3, 73541.8)],
                          cash=46460.0)
    value = 46460.0 + 100.0 * 312.06 + 0.3 * 73541.8
    assert w["AAPL"] == pytest.approx(100.0 * 312.06 / value)
    assert w["BTC/USD"] == pytest.approx(0.3 * 73541.8 / value)
    assert sum(w.values()) < 1.0                            # cash earns zero
    assert R.current_weights([], cash=0.0) == {}
    assert R.current_weights([("X", 1.0, 1.0)], cash=-5.0) == {}


# as-if portfolio series: intersection grid plus exclusion honesty
def _series(start: dt.date, vals):
    out = []
    d = start
    i = 0
    while i < len(vals):
        if R.is_us_trading_day(d):
            out.append((d, vals[i]))
            i += 1
        d += dt.timedelta(days=1)
    return out


def test_portfolio_returns_single_asset_equals_its_series():
    s = _series(dt.date(2026, 5, 4), [0.01, -0.02, 0.015, -0.005])
    out = R.portfolio_returns({"A": 1.0}, {"A": s})
    assert out.returns == pytest.approx(tuple(v for _, v in s))
    assert out.dates == tuple(d for d, _ in s)
    assert out.included == ("A",) and out.excluded == ()


def test_portfolio_returns_intersection_grid_and_window_cap():
    a = _series(dt.date(2026, 1, 5), [0.01] * 60)
    b = _series(dt.date(2026, 3, 2), [0.02] * 30)           # shorter history
    out = R.portfolio_returns({"A": 0.5, "B": 0.5}, {"A": a, "B": b},
                              window=10)
    assert out.n == 10                                      # capped
    assert set(out.dates) <= {d for d, _ in b}              # the common grid
    assert all(r == pytest.approx(0.5 * 0.01 + 0.5 * 0.02) for r in out.returns)


def test_portfolio_returns_reports_excluded_assets():
    a = _series(dt.date(2026, 5, 4), [0.01, 0.02])
    out = R.portfolio_returns({"A": 0.6, "GHOST": 0.3}, {"A": a})
    assert out.included == ("A",) and out.excluded == ("GHOST",)
    assert out.coverage_weight == pytest.approx(0.6)        # honest label input
    empty = R.portfolio_returns({"GHOST": 1.0}, {})
    assert empty.n == 0 and empty.excluded == ("GHOST",)


def test_check_n_through_the_full_series_path():
    # same reference vector, built through portfolio_returns
    d1, d2 = dt.date(2026, 6, 8), dt.date(2026, 6, 9)
    out = R.portfolio_returns(
        {"A": 0.6, "B": 0.4},
        {"A": [(d1, 0.0), (d2, 0.01)], "B": [(d1, 0.0), (d2, -0.005)]})
    assert out.returns[-1] == pytest.approx(0.0040, abs=1e-12)


def test_zero_overlap_yields_n_zero_with_coverage_still_described():
    # disjoint histories give an empty grid but coverage still describes the
    # weights, so consumers must gate on n, never on coverage alone
    a = [(dt.date(2026, 1, 5), 0.01)]
    b = [(dt.date(2026, 3, 2), 0.02)]
    out = R.portfolio_returns({"A": 0.5, "B": 0.5}, {"A": a, "B": b})
    assert out.n == 0 and out.dates == () and out.returns == ()
    assert out.included == ("A", "B") and out.coverage_weight == pytest.approx(1.0)


def test_window_zero_or_negative_means_uncapped():
    s = _series(dt.date(2026, 1, 5), [0.01] * 40)
    assert R.portfolio_returns({"A": 1.0}, {"A": s}, window=0).n == 40
    assert R.portfolio_returns({"A": 1.0}, {"A": s}, window=-1).n == 40


def test_align_handles_unsorted_input():
    d1, d2 = dt.date(2026, 6, 8), dt.date(2026, 6, 9)
    rows = [(_ts(d2), 101.0), (_ts(d1), 100.0), (_ts(d1) + 60.0, 999.0)]
    aligned = R.align_daily_closes(rows)
    assert aligned == [(d1, 999.0), (d2, 101.0)]   # ascending; latest-ts wins


def test_half_day_counts_as_a_trading_day():
    from mahad.engine.market_session import early_closes
    half_days = sorted(early_closes(2026))
    assert half_days and all(R.is_us_trading_day(d) for d in half_days)


def test_split_factor_zero_reads_as_missing_not_an_action():
    assert R.needs_full_repull([_Row(split_factor=0.0)]) is False


@dataclass(frozen=True)
class _Row:
    div_cash: float = 0.0
    split_factor: float = 1.0


def test_needs_full_repull_rule():
    assert R.needs_full_repull([_Row(), _Row()]) is False
    assert R.needs_full_repull([_Row(div_cash=0.26)]) is True
    assert R.needs_full_repull([_Row(split_factor=4.0)]) is True
    assert R.needs_full_repull([_Row(split_factor=0.5)]) is True   # reverse split
    assert R.needs_full_repull([]) is False
