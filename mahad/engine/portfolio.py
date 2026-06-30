from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Iterable, Mapping, Optional

BUY = "buy"
SELL = "sell"

_CENT = Decimal("0.01")
_QTY_Q = Decimal("0.00000001")          # 8 dp


def D(x: object) -> Decimal:
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def money(x: object) -> Decimal:
    return D(x).quantize(_CENT, rounding=ROUND_HALF_UP)


def qty_q(x: object) -> Decimal:
    return D(x).quantize(_QTY_Q, rounding=ROUND_HALF_UP)


@dataclass(frozen=True, slots=True)
class Position:
    symbol: str
    quantity: Decimal
    avg_cost: Decimal           # full precision


@dataclass(frozen=True, slots=True)
class PortfolioState:
    cash: Decimal
    realised_pnl: Decimal
    positions: tuple[Position, ...] = ()

    def position(self, symbol: str) -> Optional[Position]:
        for p in self.positions:
            if p.symbol == symbol:
                return p
        return None


@dataclass(frozen=True, slots=True)
class TradeFill:
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    avg_cost_at_fill: Decimal
    qty_before: Decimal
    qty_after: Decimal
    realised_pnl: Decimal       # 0 for a buy
    cash_delta: Decimal         # signed money applied to cash


@dataclass(frozen=True, slots=True)
class OrderResult:
    ok: bool
    state: PortfolioState
    fill: Optional[TradeFill] = None
    reason: str = ""


def validate_qty(raw: object) -> tuple[bool, Decimal, str]:
    try:
        q = D(raw)
    except Exception:
        return False, Decimal(0), "enter a valid quantity"
    if not q.is_finite():                       # NaN/Infinity cannot trade
        return False, Decimal(0), "enter a valid quantity"
    if q <= 0:
        return False, Decimal(0), "quantity must be greater than zero"
    try:
        quantised = q.quantize(_QTY_Q, rounding=ROUND_HALF_UP)
    except InvalidOperation:                    # beyond the 8-dp form
        return False, Decimal(0), "enter a valid quantity"
    if q != quantised:                          # > 8 dp
        return False, Decimal(0), "quantity supports at most 8 decimal places"
    return True, q, ""


def place_order(state: PortfolioState, side: str, symbol: str,
                qty: object, mark: Optional[Decimal]) -> OrderResult:
    # market order against the USD mark; returns a fresh state, never mutates
    ok_q, q, reason = validate_qty(qty)
    if not ok_q:
        return OrderResult(False, state, None, reason)
    if mark is None:
        return OrderResult(False, state, None, "no usable mark")
    m = D(mark)
    if not m.is_finite():                       # non-finite mark cannot fill
        return OrderResult(False, state, None, "no usable mark")
    pos = state.position(symbol)

    if side == BUY:
        cost = money(q * m)
        if state.cash - cost < 0:                            # cash >= 0
            return OrderResult(False, state, None, "insufficient cash")
        if pos is None:
            new_qty = qty_q(q)
            new_avg = m
        else:
            new_qty = qty_q(pos.quantity + q)
            new_avg = (pos.quantity * pos.avg_cost + q * m) / new_qty   # full precision
        new_cash = money(state.cash - cost)
        new_positions = _upsert(state.positions, Position(symbol, new_qty, new_avg))
        fill = TradeFill(symbol, BUY, q, m, new_avg,
                         qty_before=(pos.quantity if pos else Decimal(0)),
                         qty_after=new_qty, realised_pnl=money(0),
                         cash_delta=money(-cost))
        return OrderResult(True, replace(state, cash=new_cash,
                                         positions=new_positions), fill, "")

    if side == SELL:
        if pos is None:
            return OrderResult(False, state, None, "no position to sell")
        if q > pos.quantity:
            return OrderResult(False, state, None, "sell exceeds position")
        realised_delta = money(q * (m - pos.avg_cost))       # avg_cost full precision
        proceeds = money(q * m)
        new_cash = money(state.cash + proceeds)
        new_realised = state.realised_pnl + realised_delta   # sum of 2dp deltas
        new_qty = qty_q(pos.quantity - q)
        if new_qty == 0:
            new_positions = _remove(state.positions, symbol)         # delete at 0
        else:
            new_positions = _upsert(state.positions,
                                    Position(symbol, new_qty, pos.avg_cost))  # avg unchanged
        fill = TradeFill(symbol, SELL, q, m, pos.avg_cost,
                         qty_before=pos.quantity, qty_after=new_qty,
                         realised_pnl=realised_delta, cash_delta=money(proceeds))
        return OrderResult(True, replace(state, cash=new_cash, realised_pnl=new_realised,
                                         positions=new_positions), fill, "")

    return OrderResult(False, state, None, "unknown order side")


def _upsert(positions: tuple[Position, ...], pos: Position) -> tuple[Position, ...]:
    out = [p for p in positions if p.symbol != pos.symbol]
    out.append(pos)
    return tuple(out)


def _remove(positions: tuple[Position, ...], symbol: str) -> tuple[Position, ...]:
    return tuple(p for p in positions if p.symbol != symbol)


# valuation marks are {symbol: Decimal-or-number}; results stay exact, never money-rounded
def position_unrealised(p: Position, mark: object) -> Optional[Decimal]:
    if mark is None:
        return None
    return p.quantity * (D(mark) - p.avg_cost)


def unrealised(state: PortfolioState, marks: Mapping[str, object]) -> Decimal:
    total = Decimal(0)
    for p in state.positions:
        m = marks.get(p.symbol)
        if m is not None:
            total += p.quantity * (D(m) - p.avg_cost)
    return total


def positions_value(state: PortfolioState, marks: Mapping[str, object]) -> Decimal:
    total = Decimal(0)
    for p in state.positions:
        m = marks.get(p.symbol)
        if m is not None:
            total += p.quantity * D(m)
    return total


def portfolio_value(state: PortfolioState, marks: Mapping[str, object]) -> Decimal:
    return state.cash + positions_value(state, marks)


def total_pnl(state: PortfolioState, marks: Mapping[str, object]) -> Decimal:
    return state.realised_pnl + unrealised(state, marks)


# trade log + CSV: no Qt, no file I/O; imports sit here beside their only use
import csv as _csv  # noqa: E402 (module-level helpers, kept with their use)
import io as _io            # noqa: E402
import time as _time        # noqa: E402

CSV_COLUMNS = ("ts", "symbol", "side", "quantity", "fill_price",
               "avg_cost_at_fill", "qty_before", "qty_after", "realised_pnl")


@dataclass(frozen=True, slots=True)
class TradeRecord:
    ts: float
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    avg_cost_at_fill: Decimal
    qty_before: Decimal
    qty_after: Decimal
    realised_pnl: Decimal


def record_from_fill(fill: TradeFill, ts: float) -> TradeRecord:
    return TradeRecord(ts=float(ts), symbol=fill.symbol, side=fill.side,
                       quantity=fill.quantity, fill_price=fill.fill_price,
                       avg_cost_at_fill=fill.avg_cost_at_fill,
                       qty_before=fill.qty_before, qty_after=fill.qty_after,
                       realised_pnl=fill.realised_pnl)


def _plain(d: object) -> str:
    return format(D(d), "f")  # fixed-point, never scientific notation


def _qty_str(d: object) -> str:
    # normalize() drops trailing zeros; "f" keeps it out of scientific notation
    return format(D(d).normalize(), "f")


def fmt_ts(ts: float) -> str:
    return _time.strftime("%Y-%m-%d %H:%M:%S", _time.localtime(float(ts)))


def build_trade_csv(records: Iterable[TradeRecord], starting_cash: object) -> str:
    # leading "# starting_cash" preamble line, then the header, then one row per fill
    buf = _io.StringIO()
    buf.write(f"# starting_cash,{_plain(money(starting_cash))}\n")
    w = _csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)
    for r in records:
        w.writerow((fmt_ts(r.ts), r.symbol, r.side, _qty_str(r.quantity),
                    _plain(r.fill_price), _plain(r.avg_cost_at_fill),
                    _qty_str(r.qty_before), _qty_str(r.qty_after),
                    _plain(money(r.realised_pnl))))
    return buf.getvalue()


def reconstruct_cash(records: Iterable[TradeRecord], starting_cash: object) -> Decimal:
    # replays signed cash deltas to reproduce ledger cash; sells add, buys subtract
    cash = money(starting_cash)
    for r in records:
        amt = money(D(r.quantity) * D(r.fill_price))
        cash = money(cash + (amt if r.side == SELL else -amt))
    return cash


def reconstruct_realised(records: Iterable[TradeRecord]) -> Decimal:
    # each row's realised delta is already 2 dp, so plain summing is exact
    total = Decimal(0)
    for r in records:
        total += D(r.realised_pnl)
    return total
