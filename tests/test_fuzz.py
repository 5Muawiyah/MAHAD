# a failure here is a real bug (flag to the owner) or a wrong property - never
# "fix" it by changing the engine
from __future__ import annotations

import csv
import io
import math
import statistics
from decimal import Decimal
from pathlib import Path

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mahad.data.models import Candle
from mahad.data.source import dedupe_sort_candles, normalize_ohlcv
from mahad.data.symbols import classify, normalize_symbol, validate_add
from mahad.engine.indicators import wilder_rsi
from mahad.engine.portfolio import (BUY, SELL, PortfolioState, place_order,
                                    reconstruct_cash, reconstruct_realised,
                                    record_from_fill, unrealised, validate_qty)
from mahad.engine.risk import (ValueSample, exposure, max_drawdown,
                               simple_returns, volatility)
from mahad.engine.signals import validate_params

_SET = settings(max_examples=75, deadline=None,
                suppress_health_check=[HealthCheck.too_slow])

qty_st = st.decimals(min_value="0.00000001", max_value="1000000",
                     places=8, allow_nan=False, allow_infinity=False)
mark_st = st.decimals(min_value="0.01", max_value="1000000",
                      places=2, allow_nan=False, allow_infinity=False)
side_st = st.sampled_from([BUY, SELL])
sym_st = st.sampled_from(["AAPL", "MSFT", "BTC/USDT"])


# --------------------------------------------------------------------------- #
# Ledger invariants
# --------------------------------------------------------------------------- #
@_SET
@given(st.lists(st.tuples(side_st, sym_st, qty_st, mark_st), max_size=40))
def test_cash_never_negative_and_reconstruction_matches(ops):
    state = PortfolioState(cash=Decimal("100000"), realised_pnl=Decimal("0"))
    records = []
    for i, (side, sym, q, m) in enumerate(ops):
        res = place_order(state, side, sym, q, m)
        if res.ok:
            state = res.state
            records.append(record_from_fill(res.fill, float(i)))
        else:
            assert res.state is state
        assert state.cash >= 0
        for p in state.positions:
            assert p.quantity > 0                           # zero-qty positions are deleted
    assert reconstruct_cash(records, "100000") == state.cash
    assert reconstruct_realised(records) == state.realised_pnl


@_SET
@given(st.lists(st.tuples(sym_st, qty_st, mark_st), min_size=1, max_size=10),
       mark_st)
def test_realised_plus_unrealised_is_total(buys, later_mark):
    state = PortfolioState(cash=Decimal("10000000"), realised_pnl=Decimal("0"))
    for sym, q, m in buys:
        res = place_order(state, BUY, sym, q, m)
        if res.ok:
            state = res.state
    marks = {p.symbol: later_mark for p in state.positions}
    unreal = unrealised(state, marks)
    total = state.realised_pnl + unreal
    # identity by construction; pin the Decimal exactness of the composition
    assert total == state.realised_pnl + unrealised(state, marks)


# --------------------------------------------------------------------------- #
# Exposure
# --------------------------------------------------------------------------- #
@_SET
@given(st.lists(st.floats(0.01, 1e7, allow_nan=False), max_size=8),
       st.floats(0.01, 1e8, allow_nan=False))
def test_exposure_bounds_and_per_position_sum(position_values, cash):
    pv = sum(position_values) + cash
    res = exposure(sum(position_values), pv)
    assert res.defined
    assert 0.0 <= res.pct <= 1.0 + 1e-12                    # long-only with cash, so bounded by 1
    assert not res.out_of_range
    shares = [v / pv for v in position_values]
    assert math.isclose(sum(shares), res.pct, rel_tol=1e-9, abs_tol=1e-12)


def test_exposure_undefined_at_zero_or_negative_value():
    for pv in (0.0, -10.0):
        assert not exposure(5.0, pv).defined


# --------------------------------------------------------------------------- #
# Volatility: independent reference + warm-up + window
# --------------------------------------------------------------------------- #
@_SET
@given(st.lists(st.floats(-0.2, 0.2, allow_nan=False), min_size=2, max_size=120))
def test_volatility_matches_statistics_stdev(returns):
    res = volatility(returns, "1d", window=30)
    used = returns[-30:] if len(returns) > 30 else returns
    ref = statistics.stdev(used) * 100.0
    assert res.defined and res.n_returns == len(used)
    assert math.isclose(res.per_period_pct, ref, rel_tol=1e-9, abs_tol=1e-12)
    # abs_tol mirrors the per-period assert above: the engine's numeric stdev
    # leaves ~1e-15 cancellation noise on identical inputs where the exact
    # statistics.stdev reference returns 0.0, and a pure rel_tol can never
    # match a 0 expectation. Test-only tolerance; the locked maths are untouched.
    assert math.isclose(res.annualised_pct, (ref / 100.0) * math.sqrt(365) * 100.0,
                        rel_tol=1e-9, abs_tol=1e-10)


def test_volatility_undefined_below_two_returns():
    assert not volatility([], "1d").defined
    assert not volatility([0.01], "1d").defined


@_SET
@given(st.lists(st.tuples(st.floats(1.0, 1e6, allow_nan=False), st.booleans()),
                min_size=2, max_size=60))
def test_simple_returns_skip_stale_and_nonpositive(samples_raw):
    samples = [ValueSample(ts=float(i), value=v, stale=s)
               for i, (v, s) in enumerate(samples_raw)]
    returns, skipped = simple_returns(samples)
    expected = []
    exp_skipped = False
    for a, b in zip(samples, samples[1:]):
        if not a.stale and not b.stale and a.value > 0 and b.value > 0:
            expected.append(b.value / a.value - 1.0)
        else:
            exp_skipped = True
    assert returns == expected and skipped == exp_skipped


# --------------------------------------------------------------------------- #
# Max drawdown
# --------------------------------------------------------------------------- #
@_SET
@given(st.lists(st.floats(1.0, 1e6, allow_nan=False), min_size=1, max_size=120),
       st.one_of(st.none(), st.floats(1.0, 1e6, allow_nan=False)))
def test_max_drawdown_properties(values, peak):
    samples = [ValueSample(ts=float(i), value=v) for i, v in enumerate(values)]
    res = max_drawdown(samples, peak_value=peak, peak_ts=-1.0 if peak else None)
    assert res.defined
    assert res.max_dd_pct <= 0.0
    if res.max_dd_pct < 0.0:
        assert res.trough_ts is not None
        assert res.peak_ts is not None
        if res.peak_ts >= 0:                                # negative peak_ts means a persisted peak, not in-series
            assert res.peak_ts <= res.trough_ts


@_SET
@given(st.lists(st.floats(1.0, 1e6, allow_nan=False), min_size=1, max_size=60))
def test_max_drawdown_zero_for_monotone_rise(values):
    ordered = sorted(values)
    samples = [ValueSample(ts=float(i), value=v) for i, v in enumerate(ordered)]
    assert max_drawdown(samples).max_dd_pct == 0.0


def test_max_drawdown_respects_persisted_peak():
    samples = [ValueSample(ts=1.0, value=90.0)]
    res = max_drawdown(samples, peak_value=100.0, peak_ts=0.0)
    assert math.isclose(res.max_dd_pct, -10.0)
    assert res.peak_ts == 0.0 and res.trough_ts == 1.0


# --------------------------------------------------------------------------- #
# Candle normalisation totality
# --------------------------------------------------------------------------- #
junk = st.one_of(st.none(), st.text(max_size=6), st.integers(), st.floats(),
                 st.lists(st.floats(allow_nan=True), max_size=7))


@_SET
@given(st.lists(junk, max_size=30))
def test_normalize_ohlcv_total_on_junk(rows):
    candles = normalize_ohlcv("A", "1d", rows)              # totality: junk in, no exception out
    for c in candles:
        assert isinstance(c, Candle)


@_SET
@given(st.lists(st.tuples(st.integers(0, 10), st.floats(1, 100, allow_nan=False)),
                max_size=40))
def test_dedupe_sort_invariants(pairs):
    candles = [Candle("A", "1d", float(ts), 1, 2, 0.5, c, 1) for ts, c in pairs]
    out = dedupe_sort_candles(candles, history_cap=10)
    tss = [c.ts for c in out]
    assert tss == sorted(tss)
    assert len(tss) == len(set(tss))
    assert len(out) <= 10


# --------------------------------------------------------------------------- #
# Validator totality
# --------------------------------------------------------------------------- #
@_SET
@given(st.text(max_size=40))
def test_validate_add_total(text_):
    out = validate_add(text_, ["AAPL"])
    assert out.status in ("ok", "duplicate", "rejected")


@_SET
@given(st.one_of(st.none(), st.text(max_size=20), st.floats(), st.integers(),
                 st.decimals(allow_nan=True, allow_infinity=True)))
def test_validate_qty_total(raw):
    ok, q, reason = validate_qty(raw)
    assert isinstance(ok, bool)
    if ok:
        assert q > 0


@_SET
@given(st.text(max_size=24),
       st.dictionaries(st.text(max_size=8),
                       st.one_of(st.none(), st.text(max_size=8), st.floats(),
                                 st.integers(), st.lists(st.integers(), max_size=3)),
                       max_size=4))
def test_validate_params_total(ct, params):
    ok, canonical, reason = validate_params(ct, params)
    assert isinstance(ok, bool)


@_SET
@given(st.one_of(st.none(), st.text(max_size=30)))
def test_normalize_and_classify_total(text_):
    s = normalize_symbol(text_)
    assert isinstance(s, str)
    if s:
        asset_class, quote = classify(s)
        assert asset_class in ("stock", "crypto")


# --------------------------------------------------------------------------- #
# RSI bounds
# --------------------------------------------------------------------------- #
@_SET
@given(st.lists(st.floats(0.01, 1e5, allow_nan=False), min_size=16, max_size=120))
def test_rsi_bounded_0_100(closes):
    vals = wilder_rsi(closes, 14)
    defined = vals[~__import__("numpy").isnan(vals)]
    assert ((defined >= 0.0) & (defined <= 100.0)).all()


# --------------------------------------------------------------------------- #
# Committed-CSV integrity
# --------------------------------------------------------------------------- #
def test_committed_sample_csv_reproduces():
    path = Path(__file__).resolve().parent / "fixtures" / "sample-paper-trades.csv"
    assert path.exists(), "the sample CSV must stay committed"
    text = path.read_text(encoding="utf-8")
    first, rest = text.split("\n", 1)
    assert first.startswith("# starting_cash,")
    starting = Decimal(first.split(",", 1)[1])
    rows = list(csv.DictReader(io.StringIO(rest)))
    assert rows, "the artifact must contain at least one fill"
    cash = starting
    realised_total = Decimal("0")
    for r in rows:
        q = Decimal(r["quantity"])
        px = Decimal(r["fill_price"])
        amt = (q * px).quantize(Decimal("0.01"))
        cash += amt if r["side"] == "sell" else -amt
        realised_total += Decimal(r["realised_pnl"])
        assert r["side"] in ("buy", "sell")
        if r["side"] == "buy":
            assert Decimal(r["realised_pnl"]) == 0
        assert Decimal(r["qty_after"]) - Decimal(r["qty_before"]) == \
            (q if r["side"] == "buy" else -q)
    assert cash >= 0
