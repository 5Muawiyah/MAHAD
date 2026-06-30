"""Decimal-exactness vector for the paper-trade engine, hand-checkable:

    start cash 100,000.00
    buy AAPL 60 @ 305.00 -> avg 305.00, cash 81,700.00
    buy AAPL 40 @ 312.50 -> avg 308.00, cash 69,200.00 (60*305+40*312.5)/100
    buy BTC/USDT 0.30 @ 74,800.00 -> avg 74,800.00, cash 46,760.00
    buy RBLX 200 @ 47.80 -> avg 47.80, cash 37,200.00
    sell RBLX 200 @ 46.30 -> realised 200*(46.30-47.80) = -300.00, cash 46,460.00, deleted
    marks: AAPL 312.06, BTC/USDT 73,541.80
    unrealised: AAPL +406.00; BTC -377.46; total +28.54
    value = 46,460.00 + 100*312.06 + 0.30*73,541.80 = 99,728.54
    total P&L = realised + unrealised = -300.00 + 28.54 = -271.46
"""
from decimal import Decimal

from mahad.engine.portfolio import (
    BUY, SELL, PortfolioState, place_order, money, validate_qty,
    unrealised, portfolio_value, total_pnl, position_unrealised,
    record_from_fill, build_trade_csv, reconstruct_cash, reconstruct_realised,
)

D = Decimal


def _fresh():
    return PortfolioState(cash=D("100000.00"), realised_pnl=D("0.00"), positions=())


def _ok(state, side, sym, qty, mark):
    r = place_order(state, side, sym, D(qty), D(mark))
    assert r.ok, f"unexpected reject: {r.reason}"
    return r


def _run_demo():
    s = _fresh()
    fills = []
    for side, sym, q, m in [
        (BUY, "AAPL", "60", "305.00"),
        (BUY, "AAPL", "40", "312.50"),
        (BUY, "BTC/USDT", "0.30", "74800.00"),
        (BUY, "RBLX", "200", "47.80"),
        (SELL, "RBLX", "200", "46.30"),
    ]:
        r = _ok(s, side, sym, q, m)
        s = r.state
        fills.append(r.fill)
    return s, fills


def test_buy_averages_cost_and_decrements_cash():
    s = _fresh()
    s = _ok(s, BUY, "AAPL", "60", "305.00").state
    assert s.position("AAPL").avg_cost == D("305")
    assert s.cash == D("81700.00")                       # 100000 - 60*305
    s = _ok(s, BUY, "AAPL", "40", "312.50").state
    assert s.position("AAPL").avg_cost == D("308.00")    # (60*305 + 40*312.5)/100
    assert s.position("AAPL").quantity == D("100")
    assert s.cash == D("69200.00")                       # 81700 - 40*312.5


def test_sell_to_reduce_books_realised_and_deletes_at_zero():
    s, _ = _run_demo()
    assert s.position("RBLX") is None
    assert s.realised_pnl == D("-300.00")                # 200*(46.30-47.80)
    assert s.cash == D("46460.00")
    assert s.position("AAPL").avg_cost == D("308.00")
    assert s.position("BTC/USDT").avg_cost == D("74800.00")


def test_sell_avg_cost_unchanged_partial_reduce():
    s = _fresh()
    s = _ok(s, BUY, "AAPL", "100", "308.00").state
    s = _ok(s, SELL, "AAPL", "40", "320.00").state
    p = s.position("AAPL")
    assert p.quantity == D("60")
    assert p.avg_cost == D("308.00")                     # reduce does not touch avg
    assert s.realised_pnl == D("480.00")                 # 40*(320-308)
    assert s.cash == money(D("100000") - D("30800.00") + D("12800.00"))


def test_unrealised_value_total_signs():
    s, _ = _run_demo()
    marks = {"AAPL": D("312.06"), "BTC/USDT": D("73541.80")}
    assert position_unrealised(s.position("AAPL"), marks["AAPL"]) == D("406.00")
    assert position_unrealised(s.position("BTC/USDT"), marks["BTC/USDT"]) == D("-377.46")
    assert money(unrealised(s, marks)) == D("28.54")
    assert money(portfolio_value(s, marks)) == D("99728.54")
    assert money(total_pnl(s, marks)) == D("-271.46")


def test_closed_position_has_no_unrealised():
    s, _ = _run_demo()
    # a mark for a closed symbol must not leak into unrealised
    marks = {"AAPL": D("312.06"), "BTC/USDT": D("73541.80"), "RBLX": D("99.00")}
    assert money(unrealised(s, marks)) == D("28.54")


# every reject below must leave state byte-identical
def test_buy_to_exactly_zero_cash_accepted():
    s = PortfolioState(cash=D("100.00"), realised_pnl=D("0.00"), positions=())
    r = place_order(s, BUY, "AAPL", D("4"), D("25.00"))   # 4*25 = 100 exactly
    assert r.ok
    assert r.state.cash == D("0.00")                      # zero cash is allowed, negative is not


def test_buy_one_cent_over_cash_rejected_and_state_unchanged():
    s = PortfolioState(cash=D("99.99"), realised_pnl=D("0.00"), positions=())
    r = place_order(s, BUY, "AAPL", D("4"), D("25.00"))   # cost 100.00 > 99.99
    assert not r.ok and "insufficient cash" in r.reason
    assert r.state is s and r.fill is None


def test_sell_exceeds_position_rejected():
    s = _fresh()
    s = _ok(s, BUY, "AAPL", "10", "100.00").state
    r = place_order(s, SELL, "AAPL", D("11"), D("100.00"))
    assert not r.ok and "exceeds position" in r.reason
    assert r.fill is None and r.state.position("AAPL").quantity == D("10")


def test_sell_with_no_position_rejected():
    r = place_order(_fresh(), SELL, "AAPL", D("1"), D("100.00"))
    assert not r.ok and r.fill is None


def test_zero_negative_and_overprecise_qty_rejected():
    s = _fresh()
    assert not place_order(s, BUY, "AAPL", D("0"), D("100")).ok
    assert not place_order(s, BUY, "AAPL", D("-1"), D("100")).ok
    ok, _, reason = validate_qty(D("0.000000001"))        # 9 dp, one past the limit
    assert not ok and "8 decimal" in reason
    r = place_order(s, BUY, "AAPL", D("0.000000001"), D("100"))
    assert not r.ok and r.state is s


def test_absent_mark_blocks_the_fill():
    s = _fresh()
    r = place_order(s, BUY, "AAPL", D("1"), None)
    assert not r.ok and "no usable mark" in r.reason
    assert r.state is s and r.fill is None


# rounding-decisive vectors the cent-exact demo above cannot catch
def test_money_rounds_half_up():
    s = _fresh()
    r = place_order(s, BUY, "AAPL", D("1"), D("30.025"))  # 30.025 -> HALF_UP 30.03
    assert r.ok
    assert r.state.cash == D("99969.97")  # 100000 - 30.03 (HALF_EVEN would give.98)


def test_avg_cost_kept_full_precision_changes_realised():
    # 302/3 = 100.6666... is non-terminating; rounding it early shifts realised by a cent
    s = _fresh()
    s = _ok(s, BUY, "AAPL", "1", "100").state
    s = _ok(s, BUY, "AAPL", "2", "101").state
    avg = s.position("AAPL").avg_cost
    assert avg != D("100.67")
    assert avg > D("100.666") and avg < D("100.667")
    r = place_order(s, SELL, "AAPL", D("3"), D("110"))
    assert r.ok
    assert r.state.realised_pnl == D("28.00")             # a rounded avg (100.67) would give 27.99


def test_per_trade_quantisation_matches_reconstruction():
    # quantise each fill, not the raw sum: 3 * money(0.005) = 0.03, not money(0.015) = 0.02
    s = _fresh()
    recs = []
    for i in range(3):
        r = _ok(s, BUY, "PENNY", "1", "0.005")
        s = r.state
        recs.append(record_from_fill(r.fill, ts=1000 + i))
    assert s.cash == D("99999.97")
    assert reconstruct_cash(recs, D("100000")) == s.cash


def test_csv_reconstructs_the_ledger():
    s, fills = _run_demo()
    recs = [record_from_fill(f, ts=1_700_000_000 + i * 60) for i, f in enumerate(fills)]
    # the rows alone, with no live state, must rebuild cash and realised
    assert reconstruct_cash(recs, D("100000")) == s.cash == D("46460.00")
    assert reconstruct_realised(recs) == s.realised_pnl == D("-300.00")
    assert sum((D(r.realised_pnl) for r in recs), D("0")) == s.realised_pnl


def test_csv_rows_are_self_contained():
    s, fills = _run_demo()
    recs = [record_from_fill(f, ts=1_700_000_000 + i * 60) for i, f in enumerate(fills)]
    csv_text = build_trade_csv(recs, D("100000"))
    lines = csv_text.strip().splitlines()
    assert lines[0] == "# starting_cash,100000.00"        # preamble lets the file stand alone
    assert lines[1] == ("ts,symbol,side,quantity,fill_price,avg_cost_at_fill,"
                        "qty_before,qty_after,realised_pnl")
    sell = [ln for ln in lines if ",RBLX,sell," in ln][0]
    cells = sell.split(",")
    assert cells[2] == "sell" and D(cells[3]) == D("200")
    assert D(cells[4]) == D("46.30") and D(cells[5]) == D("47.80")  # fill_price, avg_cost
    assert D(cells[6]) == D("200") and D(cells[7]) == D("0")        # qty_before / qty_after
    assert D(cells[8]) == D("-300.00")
    aapl2 = [ln for ln in lines if ",AAPL,buy," in ln][1]
    bcells = aapl2.split(",")
    assert D(bcells[5]) == D("308.00") and D(bcells[8]) == D("0")  # blended avg, zero realised
