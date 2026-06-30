from __future__ import annotations

from decimal import Decimal

import pytest

from mahad.data.symbols import (EMPTY_MSG, USD_REJECT_MSG, classify,
                                is_usd_quoted, validate_add)
from mahad.engine.portfolio import (BUY, SELL, PortfolioState, place_order,
                                    validate_qty)
from mahad.engine.signals import validate_params


# Watchlist add
def test_empty_and_whitespace_rejected():
    for text in (None, "", "   ", "\t"):
        out = validate_add(text, [])
        assert out.status == "rejected" and out.reason == EMPTY_MSG


@pytest.mark.parametrize("sym", ["BTC/EUR", "ETH/GBP", "XRP/JPY", "SOL/CHF"])
def test_non_usd_rejected_verbatim(sym):
    out = validate_add(sym, [])
    assert out.status == "rejected" and out.reason == USD_REJECT_MSG
    assert not is_usd_quoted(sym)


@pytest.mark.parametrize("sym", ["BTC/USD", "ETH/USD", "AAPL"])
def test_usd_and_proxies_accepted(sym):
    assert is_usd_quoted(sym)
    assert validate_add(sym, []).ok


def test_duplicate_ignored_case_insensitive():
    out = validate_add("aapl", ["AAPL"])
    assert out.status == "duplicate"               # ignored, not an error


def test_watchlist_cap_message():
    existing = [f"S{i}" for i in range(20)]
    out = validate_add("NEW", existing, cap=20)
    assert out.status == "rejected"
    assert out.reason == "Watchlist is full (max 20)."


def test_classify_quote_currency():
    assert classify("BTC/USDT") == ("crypto", "USDT")
    assert classify("AAPL") == ("stock", "USD")


# Order quantity
@pytest.mark.parametrize("qty,msg", [
    ("0", "quantity must be greater than zero"),
    ("-1", "quantity must be greater than zero"),
    ("0.000000001", "quantity supports at most 8 decimal places"),   # 9 dp
    ("abc", "enter a valid quantity"),
    ("", "enter a valid quantity"),
    (None, "enter a valid quantity"),
    ("1e1000", "enter a valid quantity"),          # Decimal overflow-ish input
    ("NaN", "enter a valid quantity"),
    ("Infinity", "enter a valid quantity"),
])
def test_invalid_quantities(qty, msg):
    ok, _q, reason = validate_qty(qty)
    assert not ok and reason == msg


def test_eight_dp_exactly_accepted():
    ok, q, _ = validate_qty("0.00000001")
    assert ok and q == Decimal("0.00000001")


# Orders against the ledger, boundary included
def _state(cash="100000"):
    return PortfolioState(cash=Decimal(cash), realised_pnl=Decimal("0"))


def test_buy_exactly_all_cash_passes_boundary():
    res = place_order(_state("100"), BUY, "AAPL", "1", Decimal("100"))
    assert res.ok and res.state.cash == Decimal("0.00")     # cash >= 0 holds


def test_buy_one_cent_over_rejected():
    res = place_order(_state("100"), BUY, "AAPL", "1", Decimal("100.01"))
    assert not res.ok and res.reason == "insufficient cash"
    assert res.state.cash == Decimal("100")                  # unchanged


def test_sell_without_position_rejected():
    res = place_order(_state(), SELL, "AAPL", "1", Decimal("10"))
    assert not res.ok and res.reason == "no position to sell"


def test_sell_more_than_position_rejected():
    s = place_order(_state(), BUY, "AAPL", "2", Decimal("10")).state
    res = place_order(s, SELL, "AAPL", "3", Decimal("10"))
    assert not res.ok and res.reason == "sell exceeds position"


def test_absent_mark_rejected():
    res = place_order(_state(), BUY, "AAPL", "1", None)
    assert not res.ok and res.reason == "no usable mark"


def test_unknown_side_rejected():
    res = place_order(_state(), "short", "AAPL", "1", Decimal("10"))
    assert not res.ok and res.reason == "unknown order side"


# Alert params, typed validation
@pytest.mark.parametrize("ct,params,frag", [
    ("rsi_threshold", {"level": 150}, "0 - 100"),
    ("rsi_threshold", {"level": -1}, "0 - 100"),
    ("rsi_threshold", {"level": "x"}, "number"),
    ("rsi_threshold", {"level": float("nan")}, "number"),
    ("price_threshold", {"level": 0}, "positive"),
    ("price_threshold", {"level": -5}, "positive"),
    ("price_threshold", {"level": float("inf")}, "number"),
    ("made_up_condition", {}, "unknown condition"),
])
def test_invalid_alert_params(ct, params, frag):
    ok, canonical, reason = validate_params(ct, params)
    assert not ok and canonical is None and frag in reason


def test_crossover_periods_clamped_not_rejected():
    ok, params, _ = validate_params("sma_ema_cross",
                                    {"sma_period": -5, "ema_period": 10**9})
    assert ok and params["sma_period"] == 2 and params["ema_period"] == 400


# CSV export path failure; UI surfacing is covered elsewhere
def test_csv_write_to_unwritable_path_raises_oserror(tmp_path):
    from mahad.engine.portfolio import build_trade_csv
    text = build_trade_csv([], "100000")
    target = tmp_path / "no-such-dir" / "out.csv"
    with pytest.raises(OSError):
        with open(target, "w", encoding="utf-8") as fh:    # noqa: SIM115
            fh.write(text)
