from __future__ import annotations

import math
import pytest
from mahad.engine import risk_metrics as rm


WORST6 = [-0.050, -0.040, -0.035, -0.030, -0.028, -0.025]

CHECK_B_SET = WORST6 + [0.001 + 0.0001 * i for i in range(94)]

CHECK_H_RETURNS = [0.004, -0.002, 0.003, 0.001, -0.001]

R = {
    "AAA": [0.020, -0.010, 0.015, -0.020, 0.005, 0.010],
    "BBB": [0.010, 0.000, -0.005, 0.010, -0.010, 0.005],
    "CCC": [-0.015, 0.020, 0.010, -0.005, 0.000, -0.010],
}

W = {"AAA": 0.50, "BBB": 0.30, "CCC": 0.20}


def test_check_a_quantiles():
    assert rm.z_quantile(0.95) == pytest.approx(1.6449, abs=5e-5)
    assert rm.z_quantile(0.975) == pytest.approx(1.95996, abs=5e-6)
    assert rm.z_quantile(0.99) == pytest.approx(2.3263, abs=5e-5)
    crit = rm.CHI2_1_CRIT_95
    assert crit == pytest.approx(3.8415, abs=5e-5)


def test_check_b_historical_var():
    var = rm.historical_var(CHECK_B_SET, 0.95)
    assert var.m == 6 and var.n == 100
    assert var.value == pytest.approx(0.0250, abs=1e-12)    # -r(6) = 2.50%
    assert 100000.0 * var.value == pytest.approx(2500.0)


def test_check_b_expected_shortfall():
    es = rm.expected_shortfall(CHECK_B_SET, 0.95)
    assert es.m == 6
    assert es.value == pytest.approx(0.034667, abs=5e-7)    # mean of the 6 worst
    assert es.value == pytest.approx(-sum(WORST6) / 6.0, abs=1e-12)


def test_check_c_parametric_from_moments():
    var95 = rm.parametric_var_from_moments(0.0004, 0.012, 0.95)
    var99 = rm.parametric_var_from_moments(0.0004, 0.012, 0.99)
    assert var95 == pytest.approx(0.019339, abs=1e-6)       # 1.6449*0.012-0.0004
    assert var99 == pytest.approx(0.027516, abs=1e-6)
    assert 100000.0 * var95 == pytest.approx(1933.82, abs=0.05)


def test_parametric_from_a_window_matches_the_moments():
    # a 2-point window with mu = 0.0004 and sample sd (ddof=1) = 0.012
    a = 0.0004 + 0.006 * math.sqrt(2.0)
    b = 0.0004 - 0.006 * math.sqrt(2.0)
    assert rm.sample_sd([a, b]) == pytest.approx(0.012, abs=1e-15)
    assert rm.parametric_var([a, b], 0.95) == pytest.approx(0.019339, abs=1e-6)


def test_check_d_normal_es_multipliers():
    assert rm.normal_es_multiplier(0.975) == pytest.approx(2.3378, abs=5e-5)
    assert rm.normal_es_multiplier(0.95) == pytest.approx(2.0627, abs=5e-5)
    assert rm.z_quantile(0.99) == pytest.approx(2.3263, abs=5e-5)   # the cited pair


@pytest.mark.parametrize("x,lr,reject", [
    (0, 5.0252, True),       # too FEW exceptions also fails coverage
    (4, 0.7691, False),
    (7, 5.4970, True),
    (10, 12.9555, True),
])
def test_check_e_kupiec(x, lr, reject):
    res = rm.kupiec_pof(x, 250, 0.01)
    assert res.lr == pytest.approx(lr, abs=5e-5)
    assert res.reject is reject
    assert 0.0 <= res.p_value <= 1.0


def test_kupiec_p_value_calibration():
    # at the 5% critical value the p-value is exactly 0.05
    res = rm.kupiec_pof(4, 250, 0.01)
    assert math.erfc(math.sqrt(rm.CHI2_1_CRIT_95 / 2.0)) == pytest.approx(0.05, abs=5e-5)
    assert res.p_value > 0.05                               # accept region


def test_check_e_basel_zones():
    assert [rm.basel_zone(x) for x in (0, 4)] == ["green", "green"]
    assert [rm.basel_zone(x) for x in (5, 9)] == ["yellow", "yellow"]
    assert rm.basel_zone(10) == "red" and rm.basel_zone(31) == "red"


def test_kupiec_degenerate_inputs():
    assert rm.kupiec_pof(0, 0) is None
    assert rm.kupiec_pof(-1, 250) is None
    assert rm.kupiec_pof(251, 250) is None
    full = rm.kupiec_pof(5, 5, 0.01)                        # x == t branch
    assert full is not None and full.reject is True


def test_backcast_hand_vector():
    # window 4, m = 1 so VaR is the window minimum:
    # t=4 min(-0.02) vs r=-0.03 breaches; t=5 and t=6 do not -> 1 of 3
    r = [0.01, -0.02, 0.005, -0.01, -0.03, 0.002, -0.025]
    out = rm.backcast_exceptions(r, confidence=0.95, window=4)
    assert (out.exceptions, out.observations) == (1, 3)
    assert rm.backcast_exceptions(r, window=250) is None    # not enough data


def test_check_g_beta():
    rb = [0.010, -0.010, 0.020, -0.020]
    rp = [0.012, -0.008, 0.026, -0.022]
    assert rm.beta(rp, rb) == pytest.approx(1.1600, abs=1e-12)


def test_check_h_sharpe():
    res = rm.sharpe(CHECK_H_RETURNS, rf_daily=0.0002)
    excess = [r - 0.0002 for r in CHECK_H_RETURNS]
    assert sum(excess) / 5.0 == pytest.approx(0.0008, abs=1e-15)
    assert rm.sample_sd(excess) == pytest.approx(0.002550, abs=5e-7)
    assert res.daily == pytest.approx(0.3138, abs=5e-5)
    assert res.annualised == pytest.approx(4.9812, abs=5e-4)


def test_check_h_sortino():
    res = rm.sortino(CHECK_H_RETURNS, target=0.0)
    assert res.daily == pytest.approx(1.0000, abs=5e-5)     # dd_dev 0.0010, full-N
    assert res.annualised == pytest.approx(15.8745, abs=5e-4)


def test_check_f_ewma_steps():
    seed = 1e-4                                             # sigma0 = 1% daily
    assert rm.ewma_volatility([0.01], seed_variance=seed) == pytest.approx(0.010000, abs=5e-7)
    assert rm.ewma_volatility([0.01, -0.02], seed_variance=seed) == pytest.approx(0.010863, abs=5e-7)
    assert rm.ewma_volatility([0.01, -0.02, 0.005], seed_variance=seed) == pytest.approx(0.010603, abs=5e-7)


def test_ewma_default_seed_is_the_sample_variance():
    rets = [0.01, -0.02, 0.005]
    sd = rm.sample_sd(rets)
    expected = sd * sd
    for r in rets:
        expected = 0.94 * expected + 0.06 * r * r
    assert rm.ewma_volatility(rets) == pytest.approx(math.sqrt(expected), abs=1e-15)


def test_check_k_correlation():
    ra = [0.01, -0.02, 0.015, -0.005]
    rb = [0.008, -0.015, 0.010, -0.002]
    assert rm.correlation(ra, rb) == pytest.approx(0.9950, abs=5e-5)


def test_correlation_matrix_shape_and_diagonal():
    syms, mat = rm.correlation_matrix(
        {"A": [0.01, -0.02, 0.015], "B": [0.008, -0.015, 0.010]})
    assert syms == ("A", "B")
    assert mat[0][0] == 1.0 and mat[1][1] == 1.0
    assert mat[0][1] == pytest.approx(mat[1][0])            # symmetric


def test_check_j_concentration():
    res = rm.concentration({"A": 50.0, "B": 30.0, "C": 20.0})
    assert res.hhi == pytest.approx(0.3800, abs=1e-12)
    assert res.effective_n == pytest.approx(2.6316, abs=5e-5)
    assert res.top_symbol == "A" and res.top_weight == pytest.approx(0.5)
    equal5 = rm.concentration(dict.fromkeys("ABCDE", 20.0))
    assert equal5.hhi == pytest.approx(0.2000, abs=1e-12)
    assert equal5.effective_n == pytest.approx(5.0000, abs=1e-9)


def test_sector_rollup():
    res = rm.concentration({"AAPL": 50.0, "MSFT": 30.0, "BTC/USD": 20.0},
                           sectors={"AAPL": "Technology", "MSFT": "Technology",
                                    "BTC/USD": "Crypto"})
    assert res.sector_hhi == pytest.approx(0.8 ** 2 + 0.2 ** 2)
    assert res.sector_weights[0] == ("Technology", pytest.approx(0.8))


def test_check_i_drawdown_duration():
    path = [100.0, 110.0, 99.0, 104.5, 112.0, 108.0]
    res = rm.drawdown_duration(path)
    assert res.depth_pct == pytest.approx(-10.00, abs=1e-9)
    assert (res.peak_index, res.trough_index) == (1, 2)
    assert res.recovery_index == 4 and res.duration_periods == 3
    assert res.ongoing_periods is None


def test_drawdown_duration_ongoing_and_flat():
    ongoing = rm.drawdown_duration([100.0, 110.0, 99.0, 104.0])
    assert ongoing.duration_periods is None
    assert ongoing.ongoing_periods == 2                     # peak idx 1 -> last idx 3
    flat = rm.drawdown_duration([100.0, 101.0, 102.0])
    assert flat.depth_pct == 0.0 and flat.duration_periods == 0


def test_check_l_stress_replay():
    res = rm.stress_replay(
        "COVID crash", "2020-02-19", "2020-03-23", 100000.0,
        weights={"AAPL": 0.40, "MSFT": 0.35, "BTC/USD": 0.25},
        window_returns={"AAPL": (-0.30, "constant"),
                        "MSFT": (-0.25, "constant"),
                        "BTC/USD": (-0.40, "constant")})
    assert res.pl_usd == pytest.approx(-30750.00, abs=1e-6)
    assert res.covered_weight == pytest.approx(1.0)


def test_stress_replay_no_data_legs_are_honest():
    res = rm.stress_replay("FTX week", "2022-11-04", "2022-11-14", 50000.0,
                           weights={"AAPL": 0.6, "NEW/USD": 0.4},
                           window_returns={"AAPL": (-0.02, "cache")})
    assert res.covered_weight == pytest.approx(0.6)
    legs = {leg.symbol: leg for leg in res.legs}
    assert legs["NEW/USD"].window_return is None            # no data, no guess
    assert res.pl_usd == pytest.approx(50000.0 * 0.6 * -0.02)
    empty = rm.stress_replay("x", "a", "b", 1000.0, {"Z": 1.0}, {})
    assert empty.pl_usd is None                             # nothing covered


def test_property_es_dominates_var_at_the_same_confidence():
    for c in (0.90, 0.95, 0.975, 0.99):
        var = rm.historical_var(CHECK_B_SET, c)
        es = rm.expected_shortfall(CHECK_B_SET, c)
        assert es.value >= var.value


def test_property_var_is_monotone_in_confidence():
    vals = [rm.historical_var(CHECK_B_SET, c).value
            for c in (0.90, 0.95, 0.975, 0.99)]
    assert vals == sorted(vals)


def test_property_hhi_bounds():
    for values in ({"A": 1.0}, {"A": 1.0, "B": 1.0},
                   {"A": 5.0, "B": 3.0, "C": 2.0},
                   dict.fromkeys("ABCDEFGH", 1.0)):
        res = rm.concentration(values)
        n = len(values)
        assert 1.0 / n - 1e-12 <= res.hhi <= 1.0 + 1e-12


def test_property_benchmark_beta_against_itself_is_one():
    rb = [0.010, -0.010, 0.020, -0.020, 0.005]
    assert rm.beta(rb, rb) == pytest.approx(1.0, abs=1e-12)


def test_degenerate_inputs_return_none():
    assert rm.historical_var([], 0.95) is None
    assert rm.expected_shortfall([], 0.99) is None
    assert rm.parametric_var([0.01], 0.95) is None          # n < 2
    assert rm.beta([0.01], [0.02]) is None
    assert rm.beta([0.0, 0.0], [0.0, 0.0]) is None          # zero-variance bench
    assert rm.sharpe([], 0.0) is None
    assert rm.sortino([0.01, 0.02]) is None                 # no downside -> None
    assert rm.ewma_volatility([], 0.94) is None
    assert rm.correlation([1.0], [1.0]) is None
    assert rm.concentration({}) is None
    assert rm.drawdown_duration([100.0]) is None


def test_covariance_matrix_sample_ddof1():
    cov = rm.covariance_matrix([R["AAA"], R["BBB"], R["CCC"]])
    assert cov[0][0] == pytest.approx(2.36666667e-04, rel=1e-7)
    assert cov[1][1] == pytest.approx(6.66666667e-05, rel=1e-7)
    assert cov[2][2] == pytest.approx(1.70000000e-04, rel=1e-7)
    assert cov[0][1] == pytest.approx(-2.16666667e-05, rel=1e-6)
    assert cov[0][2] == pytest.approx(-7.00000000e-05, rel=1e-7)
    assert cov[1][2] == pytest.approx(-6.00000000e-05, rel=1e-7)
    assert cov[1][0] == cov[0][1] and cov[2][0] == cov[0][2]   # symmetric


def test_covariance_matrix_gates():
    assert rm.covariance_matrix([]) is None
    assert rm.covariance_matrix([[0.01]]) is None              # n < 2
    assert rm.covariance_matrix([[0.01, 0.02], [0.01]]) is None  # ragged


def test_component_var_answer_key():
    res = rm.component_var(W, R, 0.95)
    assert res is not None and res.n == 6
    assert res.confidence == 0.95
    assert res.portfolio_sigma == pytest.approx(0.0066533200, abs=1e-10)
    assert res.portfolio_var == pytest.approx(0.0109437375, abs=1e-10)
    by = {c.symbol: c for c in res.contributions}
    assert by["AAA"].cctr == pytest.approx(0.00735222, abs=5e-8)
    assert by["BBB"].cctr == pytest.approx(-0.00012776, abs=5e-8)
    assert by["CCC"].cctr == pytest.approx(-0.00057114, abs=5e-8)
    assert by["AAA"].comp_var == pytest.approx(0.01209332, abs=5e-8)
    assert by["AAA"].pct == pytest.approx(1.105045, abs=5e-6)
    assert by["BBB"].pct == pytest.approx(-0.019202, abs=5e-6)
    assert by["CCC"].pct == pytest.approx(-0.085843, abs=5e-6)
    # sorted by component contribution, descending
    assert [c.symbol for c in res.contributions] == ["AAA", "BBB", "CCC"]


def test_component_var_euler_identities():
    res = rm.component_var(W, R, 0.95)
    assert sum(c.cctr for c in res.contributions) == pytest.approx(
        res.portfolio_sigma, abs=1e-15)
    assert sum(c.comp_var for c in res.contributions) == pytest.approx(
        res.portfolio_var, abs=1e-15)
    assert sum(c.pct for c in res.contributions) == pytest.approx(1.0, abs=1e-12)


def test_component_var_matches_zero_mean_parametric():
    # cross-anchor: sig_p must equal the sample sd of the as-if portfolio series
    res = rm.component_var(W, R, 0.95)
    rp = [sum(W[s] * R[s][t] for s in W) for t in range(6)]
    sd_rp = rm.sample_sd(rp)
    assert res.portfolio_sigma == pytest.approx(sd_rp, abs=1e-15)
    pv = rm.parametric_var_from_moments(0.0, res.portfolio_sigma, 0.95)
    assert res.portfolio_var == pytest.approx(pv, abs=1e-15)


def test_component_var_single_position_is_whole_risk():
    res = rm.component_var({"AAA": 0.4}, {"AAA": R["AAA"]}, 0.95)
    assert res is not None and len(res.contributions) == 1
    c = res.contributions[0]
    assert c.pct == pytest.approx(1.0, abs=1e-12)             # 100% of its own risk
    assert c.cctr == pytest.approx(res.portfolio_sigma, abs=1e-15)
    # sig_p = w * sd(asset) for a single position
    assert res.portfolio_sigma == pytest.approx(0.4 * rm.sample_sd(R["AAA"]),
                                                abs=1e-15)


def test_component_var_gates():
    assert rm.component_var({}, {}, 0.95) is None              # no positions
    assert rm.component_var(W, {"AAA": [0.01]}, 0.95) is None  # n < 2
    assert rm.component_var(W, R, 0.0) is None                 # bad confidence
    # a weight with no aligned series is simply skipped (uses the overlap)
    res = rm.component_var({"AAA": 0.5, "ZZZ": 0.5}, {"AAA": R["AAA"]}, 0.95)
    assert res is not None and [c.symbol for c in res.contributions] == ["AAA"]


def test_component_var_zero_variance_returns_none():
    flat = {"AAA": [0.0, 0.0, 0.0, 0.0], "BBB": [0.0, 0.0, 0.0, 0.0]}
    assert rm.component_var({"AAA": 0.5, "BBB": 0.5}, flat, 0.95) is None


def test_correlation_summary_basic():
    syms = ["AAA", "BBB", "CCC"]
    m = [[1.0, 0.8, -0.2],
         [0.8, 1.0, 0.1],
         [-0.2, 0.1, 1.0]]
    cs = rm.correlation_summary(syms, m)
    assert cs is not None and cs.n_pairs == 3
    assert cs.avg == pytest.approx((0.8 - 0.2 + 0.1) / 3.0, abs=1e-12)
    assert cs.max_pair == ("AAA", "BBB", 0.8)
    assert cs.min_pair == ("AAA", "CCC", -0.2)


def test_correlation_summary_skips_none_and_gates():
    assert rm.correlation_summary(["A"], [[1.0]]) is None        # < 2 symbols
    m = [[1.0, None], [None, 1.0]]
    assert rm.correlation_summary(["A", "B"], m) is None          # no defined pair
    m2 = [[1.0, None, 0.5], [None, 1.0, None], [0.5, None, 1.0]]
    cs = rm.correlation_summary(["A", "B", "C"], m2)
    assert cs.n_pairs == 1 and cs.max_pair == ("A", "C", 0.5)


def test_return_on_risk():
    assert rm.return_on_risk(2500.0, 1000.0) == pytest.approx(2.5)
    assert rm.return_on_risk(-500.0, 1000.0) == pytest.approx(-0.5)   # signed
    assert rm.return_on_risk(100.0, None) is None
    assert rm.return_on_risk(None, 1000.0) is None
    assert rm.return_on_risk(100.0, 0.0) is None                      # VaR not positive
    assert rm.return_on_risk(100.0, -5.0) is None


def test_rolling_var_shape_and_recency():
    rets = [0.001 * ((i % 7) - 3) for i in range(120)]
    hist = rm.rolling_var(rets, 0.95, 60, 40)
    assert len(hist) == 40                                    # capped to max_points
    assert all(v >= 0.0 for v in hist)                       # positive loss fractions
    assert hist[-1] == pytest.approx(
        rm.historical_var(rets[-60:], 0.95).value, abs=1e-12)  # newest = latest window


def test_rolling_var_gates():
    assert rm.rolling_var([0.01] * 30, 0.95, 60, 40) == ()    # n <= window
    assert rm.rolling_var([0.01] * 100, 0.95, 1, 40) == ()    # window < 2
    assert rm.rolling_var([0.01] * 100, 0.95, 60, 0) == ()    # no points
    # fewer than max_points available -> as many as fit
    h = rm.rolling_var([0.001 * ((i % 5) - 2) for i in range(70)], 0.95, 60, 40)
    assert len(h) == 11                                       # t = 60..70 inclusive
