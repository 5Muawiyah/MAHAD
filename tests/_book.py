# a seeded book two test modules share: deterministic daily bars, two positions and a short value history
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from mahad.data.repository import CONTEXT_KEY, MahadRepository, PersistedTrade
from mahad.engine.returns import is_us_trading_day


@dataclass(frozen=True)
class Bar:
    ts: float
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


def trading_bars(start: dt.date, closes):
    out = []
    d = start
    i = 0
    while i < len(closes):
        if is_us_trading_day(d):
            ts = dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp()
            c = closes[i]
            out.append(Bar(ts=ts, open=c, high=c + 1, low=c - 1, close=c, adj_close=c,
                           volume=1e6, div_cash=0.0, split_factor=1.0))
            i += 1
        d += dt.timedelta(days=1)
    return out


def walk(seed: float, n: int) -> list[float]:
    # a deterministic wobble so the returns have a real spread
    closes = [seed]
    for i in range(1, n):
        step = ((i * 7919) % 11 - 5) / 200.0
        closes.append(round(closes[-1] * (1.0 + step), 4))
    return closes


AAPL = trading_bars(dt.date(2026, 3, 2), walk(150.0, 40))
MSFT = trading_bars(dt.date(2026, 3, 2), walk(300.0, 40))
SPY = trading_bars(dt.date(2026, 3, 2), walk(500.0, 40))
SAMPLES = [(1000.0 + i * 86400.0, v) for i, v in enumerate([100000.0, 100500.0, 99800.0, 101000.0, 100200.0])]


def fill(symbol: str, qty: str, price: str) -> PersistedTrade:
    return PersistedTrade(ts=1.0, symbol=symbol, side="buy", quantity=Decimal(qty),
                          fill_price=Decimal(price), avg_cost_at_fill=Decimal(price),
                          qty_before=Decimal("0"), qty_after=Decimal(qty), realised_pnl=Decimal("0"))


def seed(path: Path, with_positions: bool = True) -> None:
    repo = MahadRepository(f"sqlite:///{path.as_posix()}")
    repo.add("AAPL", "stock", "USD", "finnhub")
    repo.add("MSFT", "stock", "USD", "finnhub")
    repo.ensure_symbol("SPY", "stock", "USD", "finnhub")
    repo.load_or_create_portfolio("100000")
    repo.upsert_daily_bars("AAPL", AAPL)
    repo.upsert_daily_bars("MSFT", MSFT)
    repo.upsert_daily_bars("SPY", SPY)
    if with_positions:
        repo.record_fill(cash=Decimal("98500"), realised_pnl=Decimal("0"), symbol="AAPL",
                         new_quantity=Decimal("10"), new_avg_cost=Decimal("150"),
                         trade=fill("AAPL", "10", "150"))
        repo.record_fill(cash=Decimal("97000"), realised_pnl=Decimal("0"), symbol="MSFT",
                         new_quantity=Decimal("5"), new_avg_cost=Decimal("300"),
                         trade=fill("MSFT", "5", "300"))
    for ts, v in SAMPLES:
        repo.append_value_history(ts=ts, portfolio_value=v, cash=97000, positions_value=v - 97000,
                                  stale=False, cap=1000)
    repo.set_setting(CONTEXT_KEY, {"yields": {"y3m": 5.25, "y2y": 4.0, "y10y": 4.5,
                                              "as_of": "2026-06-01"}})
    repo.close()
