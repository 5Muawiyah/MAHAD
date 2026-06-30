from __future__ import annotations

import gc
import json
import logging
import os
import time
from decimal import Decimal
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import (Boolean, Float, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine, delete, event, func,
                        select)
from sqlalchemy.exc import DatabaseError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.types import TypeDecorator

from mahad import config
from mahad.data.symbols import classify, normalize_symbol, provider_for

log = logging.getLogger("mahad.repository")

SCHEMA_VERSION = 1
ALERT_CAP = 20

# bump SCHEMA_VERSION only on incompatible table changes; additive tables do not


class Base(DeclarativeBase):
    pass


class DecimalText(TypeDecorator):
    # exact Decimal stored as TEXT, never a lossy Float

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return None if value is None else str(value)

    def process_result_value(self, value, dialect):
        return None if value is None else Decimal(value)


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)        # always the single row id=1
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class Symbol(Base):
    __tablename__ = "symbols"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ticker: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    asset_class: Mapped[str] = mapped_column(String(16), nullable=False)
    provider: Mapped[str] = mapped_column(String(24), nullable=False)
    quote_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    display_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    __table_args__ = (UniqueConstraint("ticker", "provider",
                                       name="uq_symbol_ticker_provider"),)


class WatchlistEntry(Base):
    __tablename__ = "watchlist"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), unique=True, nullable=False)
    added_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Setting(Base):
    # key/value store; value is JSON text, validated on read

    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False, default="json")


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    condition_type: Mapped[str] = mapped_column(String(32), nullable=False)
    params: Mapped[str] = mapped_column(Text, nullable=False)          # canonical JSON, sorted keys, for dedup
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    armed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    fired_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)


class Portfolio(Base):
    # single virtual USD portfolio; the one row is created on first run

    __tablename__ = "portfolio"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, default="paper")
    base_currency: Mapped[str] = mapped_column(String(8), nullable=False, default="USD")
    starting_cash: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    cash: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    realised_pnl: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    peak_value: Mapped[Optional[Decimal]] = mapped_column(DecimalText, nullable=True)   # (unused here)
    peak_ts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)              # (unused here)
    created_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    reset_at: Mapped[Optional[float]] = mapped_column(Float, nullable=True)


class Position(Base):
    # open long position; row is deleted when quantity hits 0

    __tablename__ = "positions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    avg_cost: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    opened_at: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    __table_args__ = (UniqueConstraint("portfolio_id", "symbol_id",
                                       name="uq_position_portfolio_symbol"),)


class Trade(Base):
    # append-only; carries its own symbol string so the CSV export is self-contained

    __tablename__ = "trades"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("symbols.id", ondelete="SET NULL"), nullable=True, index=True)
    symbol: Mapped[str] = mapped_column(String(40), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    fill_price: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    avg_cost_at_fill: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    qty_before: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    qty_after: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    realised_pnl: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    ts: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, index=True)


class ValueHistory(Base):
    __tablename__ = "value_history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    portfolio_value: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    cash: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    positions_value: Mapped[Decimal] = mapped_column(DecimalText, nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DailyBar(Base):
    __tablename__ = "daily_bars"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    symbol_id: Mapped[int] = mapped_column(
        ForeignKey("symbols.id", ondelete="CASCADE"), nullable=False, index=True)
    ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    adj_close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    div_cash: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    split_factor: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    __table_args__ = (UniqueConstraint("symbol_id", "ts",
                                       name="uq_daily_bar_symbol_ts"),)


@dataclass(frozen=True, slots=True)
class PersistedDailyBar:
    # plain DTO so the worker reads bars without importing the engine

    ts: float
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


class VarBacktestRow(Base):
    __tablename__ = "var_backtest"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolio.id", ondelete="CASCADE"), nullable=False, index=True)
    forecast_ts: Mapped[float] = mapped_column(Float, nullable=False, index=True)
    var99_pct: Mapped[float] = mapped_column(Float, nullable=False)
    weights_json: Mapped[str] = mapped_column(Text, nullable=False)
    realised_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    exception: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    resolved_ts: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    __table_args__ = (UniqueConstraint("portfolio_id", "forecast_ts",
                                       name="uq_backtest_portfolio_day"),)


@dataclass(frozen=True, slots=True)
class PersistedBacktestRow:
    forecast_ts: float
    var99_pct: float
    weights: dict
    realised_pct: Optional[float]
    exception: Optional[bool]


@dataclass(frozen=True, slots=True)
class PersistedSymbol:
    symbol: str
    asset_class: str
    quote_currency: str
    provider: str
    active: bool


@dataclass(frozen=True, slots=True)
class PersistedAlert:
    # params here is the decoded dict, not the stored JSON text

    id: int
    symbol: str
    condition_type: str
    params: dict
    direction: str
    armed: bool
    fired_at: Optional[float] = None


@dataclass(frozen=True, slots=True)
class PersistedPortfolio:
    # ledger snapshot kept engine-free so the layering holds

    starting_cash: Decimal
    cash: Decimal
    realised_pnl: Decimal


@dataclass(frozen=True, slots=True)
class PersistedPosition:
    symbol: str
    quantity: Decimal
    avg_cost: Decimal


@dataclass(frozen=True, slots=True)
class PersistedTrade:
    ts: float
    symbol: str
    side: str
    quantity: Decimal
    fill_price: Decimal
    avg_cost_at_fill: Decimal
    qty_before: Decimal
    qty_after: Decimal
    realised_pnl: Decimal


@dataclass(frozen=True, slots=True)
class PersistedValueSample:
    ts: float
    portfolio_value: Decimal
    cash: Decimal
    positions_value: Decimal
    stale: bool


@dataclass(frozen=True, slots=True)
class PersistedPeak:
    # all-time peak; either field is None on a fresh DB

    peak_value: Optional[Decimal]
    peak_ts: Optional[float]


class SchemaMismatch(Exception):
    def __init__(self, found: int, expected: int) -> None:
        super().__init__(f"schema version {found} != expected {expected}")
        self.found = found
        self.expected = expected


INDICATORS_KEY = "indicators"
RISK_TIMEFRAME_KEY = "risk_timeframe"
CONTEXT_KEY = "market_context"        # cached tiles row
SCHEMA_MIGRATION_KEY = "schema_migration"  # idempotency marker for the one-time migration
SECTORS_KEY = "sector_map"             # profile2 sector cache


class MahadRepository:
    # one Session, owned by the worker thread; do not share across threads

    def __init__(self, url: str,
                 busy_timeout_ms: int = config.SQLITE_BUSY_TIMEOUT_MS) -> None:
        self._engine = create_engine(url, future=True)
        self._busy_ms = int(busy_timeout_ms)
        try:
            self._attach_pragmas()
            Base.metadata.create_all(self._engine)
            self._session = Session(self._engine, future=True)
            self._ensure_schema()
        except Exception:
            # release the SQLite file before re-raising; Windows rename needs the handle freed
            sess = getattr(self, "_session", None)
            if sess is not None:
                try:
                    sess.close()
                except Exception:
                    pass
            self._engine.dispose()
            raise

    # -- setup ---------------------------------------------------------------- #
    def _attach_pragmas(self) -> None:
        busy_ms = self._busy_ms

        @event.listens_for(self._engine, "connect")
        def _on_connect(dbapi_conn, _record):           # noqa: ANN001
            cur = dbapi_conn.cursor()
            try:
                cur.execute("PRAGMA journal_mode=WAL")   # lets readers and the writer overlap
                cur.execute(f"PRAGMA busy_timeout={busy_ms}")
                cur.execute("PRAGMA foreign_keys=ON")    # off by default; needed for ON DELETE CASCADE
            finally:
                cur.close()

    def _ensure_schema(self) -> None:
        row = self._session.get(SchemaVersion, 1)
        if row is None:
            self._session.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
            self._session.commit()
        elif row.version != SCHEMA_VERSION:
            raise SchemaMismatch(row.version, SCHEMA_VERSION)

    # -- watchlist reads ------------------------------------------------------ #
    def list_watchlist(self) -> list[PersistedSymbol]:
        stmt = (select(Symbol)
                .join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
                .order_by(WatchlistEntry.added_at, WatchlistEntry.id))
        return [PersistedSymbol(s.ticker, s.asset_class, s.quote_currency,
                                s.provider, s.active)
                for s in self._session.scalars(stmt)]

    def watchlist_symbols(self) -> list[str]:
        return [p.symbol for p in self.list_watchlist()]

    def active_symbol(self) -> Optional[str]:
        stmt = (select(Symbol.ticker)
                .join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
                .where(Symbol.active.is_(True)))
        return self._session.scalar(stmt)

    # -- watchlist writes ----------------------------------------------------- #
    def add(self, symbol: str, asset_class: str, quote_currency: str,
            provider: str) -> bool:
        sym = self._session.scalar(
            select(Symbol).where(Symbol.ticker == symbol, Symbol.provider == provider))
        if sym is None:
            sym = Symbol(ticker=symbol, asset_class=asset_class, provider=provider,
                         quote_currency=quote_currency, display_name=symbol,
                         active=False, created_at=time.time())
            self._session.add(sym)
            self._session.flush()
        existing = self._session.scalar(
            select(WatchlistEntry).where(WatchlistEntry.symbol_id == sym.id))
        if existing is not None:
            self._session.commit()
            return False
        self._session.add(WatchlistEntry(symbol_id=sym.id, added_at=time.time()))
        if self.active_symbol() is None:                 # first symbol added becomes the active one
            self._make_active(sym)
        self._session.commit()
        return True

    def remove(self, symbol: str) -> Optional[str]:
        # returns whichever symbol is active once this one is gone
        sym = self._session.scalar(
            select(Symbol).join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
            .where(Symbol.ticker == symbol))
        if sym is None:
            return self.active_symbol()
        was_active = bool(sym.active)
        self._session.execute(
            delete(WatchlistEntry).where(WatchlistEntry.symbol_id == sym.id))
        self._session.delete(sym)
        self._session.flush()
        new_active: Optional[str] = None
        if was_active:
            nxt = self._session.scalars(
                select(Symbol).join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
                .order_by(WatchlistEntry.added_at, WatchlistEntry.id)).first()
            if nxt is not None:
                nxt.active = True
                new_active = nxt.ticker
        else:
            new_active = self.active_symbol()
        self._session.commit()
        return new_active

    def set_active(self, symbol: str) -> Optional[str]:
        sym = self._session.scalar(
            select(Symbol).join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
            .where(Symbol.ticker == symbol))
        if sym is None:
            return self.active_symbol()
        self._make_active(sym)
        self._session.commit()
        return sym.ticker

    def _make_active(self, sym: Symbol) -> None:
        for other in self._session.scalars(select(Symbol).where(Symbol.active.is_(True))):
            other.active = False
        sym.active = True

    def ensure_symbol(self, ticker: str, asset_class: str, quote_currency: str,
                      provider: str) -> int:
        # creates the Symbol row but, unlike add(), leaves it off the watchlist
        sym = self._session.scalar(
            select(Symbol).where(Symbol.ticker == ticker,
                                 Symbol.provider == provider))
        if sym is None:
            sym = Symbol(ticker=ticker, asset_class=asset_class,
                         provider=provider, quote_currency=quote_currency,
                         display_name=ticker, active=False,
                         created_at=time.time())
            self._session.add(sym)
            self._session.commit()
        return int(sym.id)

    def seed_if_empty(self, default_watchlist, venue: str) -> bool:
        count = self._session.scalar(select(func.count()).select_from(WatchlistEntry))
        if count and count > 0:
            return False
        for raw in default_watchlist:
            sym = normalize_symbol(raw)
            asset_class, quote = classify(sym)
            self.add(sym, asset_class, quote, provider_for(asset_class, venue))
        return True

    # -- settings ------------------------------------------------------------- #
    def get_setting(self, key: str):
        row = self._session.get(Setting, key)
        if row is None:
            return None
        try:
            return json.loads(row.value)
        except (ValueError, TypeError):
            return None                                  # corrupt value; caller falls back to its default

    def set_setting(self, key: str, value) -> None:
        payload = json.dumps(value)
        row = self._session.get(Setting, key)
        if row is None:
            self._session.add(Setting(key=key, value=payload, value_type="json"))
        else:
            row.value = payload
        self._session.commit()

    # -- alerts --------------------------------------------------------------- #
    def list_alerts(self) -> list[PersistedAlert]:
        stmt = (select(Alert, Symbol.ticker)
                .join(Symbol, Alert.symbol_id == Symbol.id)
                .order_by(Alert.created_at, Alert.id))
        out: list[PersistedAlert] = []
        for alert, ticker in self._session.execute(stmt):
            try:
                params = json.loads(alert.params)
            except (ValueError, TypeError):
                params = {}
            out.append(PersistedAlert(id=alert.id, symbol=ticker,
                                      condition_type=alert.condition_type, params=params,
                                      direction=alert.direction, armed=bool(alert.armed),
                                      fired_at=alert.fired_at))
        return out

    def count_alerts(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Alert)) or 0

    def add_alert(self, symbol: str, condition_type: str, params: dict,
                  direction: str) -> tuple[Optional[PersistedAlert], str]:
        # enforces the cap and rejects duplicates; second tuple slot is the reason on failure
        sym = self._session.scalar(
            select(Symbol).join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
            .where(Symbol.ticker == symbol))
        if sym is None:
            return None, "add a symbol to the watchlist first"
        if self.count_alerts() >= ALERT_CAP:
            return None, f"alerts are capped at {ALERT_CAP} - remove one first"
        params_json = json.dumps(params, sort_keys=True, separators=(",", ":"))
        dup = self._session.scalar(
            select(Alert).where(Alert.symbol_id == sym.id,
                                Alert.condition_type == condition_type,
                                Alert.params == params_json,
                                Alert.direction == direction))
        if dup is not None:
            return None, "an identical alert already exists"
        row = Alert(symbol_id=sym.id, condition_type=condition_type, params=params_json,
                    direction=direction, armed=True, fired_at=None, created_at=time.time())
        self._session.add(row)
        self._session.commit()
        return PersistedAlert(id=row.id, symbol=symbol, condition_type=condition_type,
                              params=dict(params), direction=direction, armed=True,
                              fired_at=None), ""

    def set_alert_state(self, alert_id: int, armed: bool,
                        fired_at: Optional[float]) -> bool:
        # False if the alert was deleted underneath us
        row = self._session.get(Alert, alert_id)
        if row is None:
            return False
        row.armed = bool(armed)
        row.fired_at = fired_at
        self._session.commit()
        return True

    def remove_alert(self, alert_id: int) -> bool:
        row = self._session.get(Alert, alert_id)
        if row is None:
            return False
        self._session.delete(row)
        self._session.commit()
        return True

    # -- portfolio / positions / trades -------------------------------------- #
    def load_or_create_portfolio(self, starting_cash) -> PersistedPortfolio:
        row = self._session.scalar(select(Portfolio).limit(1))
        if row is None:
            sc = Decimal(str(starting_cash))
            _now = time.time()
            row = Portfolio(name="paper", base_currency="USD", starting_cash=sc,
                            cash=sc, realised_pnl=Decimal("0"), created_at=_now,
                            peak_value=sc, peak_ts=_now)   # peak starts at inception value
            self._session.add(row)
            self._session.commit()
        return PersistedPortfolio(starting_cash=row.starting_cash, cash=row.cash,
                                  realised_pnl=row.realised_pnl)

    def get_positions(self) -> list[PersistedPosition]:
        stmt = (select(Symbol.ticker, Position.quantity, Position.avg_cost)
                .join(Symbol, Position.symbol_id == Symbol.id)
                .order_by(Position.opened_at, Position.id))
        return [PersistedPosition(symbol=t, quantity=q, avg_cost=a)
                for t, q, a in self._session.execute(stmt)]

    def _portfolio_row(self) -> Optional[Portfolio]:
        return self._session.scalar(select(Portfolio).limit(1))

    def _symbol_id_for(self, ticker: str) -> Optional[int]:
        sid = self._session.scalar(
            select(Symbol.id).join(WatchlistEntry, WatchlistEntry.symbol_id == Symbol.id)
            .where(Symbol.ticker == ticker))
        if sid is not None:
            return sid
        return self._session.scalar(select(Symbol.id).where(Symbol.ticker == ticker))

    def record_fill(self, *, cash, realised_pnl, symbol, new_quantity, new_avg_cost,
                    trade: PersistedTrade) -> None:
        # cash, realised, position and trade all land in one commit
        pf = self._portfolio_row()
        if pf is None:
            return
        pf.cash = Decimal(str(cash))
        pf.realised_pnl = Decimal(str(realised_pnl))
        sym_id = self._symbol_id_for(symbol)
        pos = None
        if sym_id is not None:
            pos = self._session.scalar(
                select(Position).where(Position.portfolio_id == pf.id,
                                       Position.symbol_id == sym_id))
        if new_quantity is None or Decimal(str(new_quantity)) == 0:
            if pos is not None:
                self._session.delete(pos)
        elif sym_id is not None:
            if pos is None:
                self._session.add(Position(portfolio_id=pf.id, symbol_id=sym_id,
                                           quantity=Decimal(str(new_quantity)),
                                           avg_cost=Decimal(str(new_avg_cost)),
                                           opened_at=time.time()))
            else:
                pos.quantity = Decimal(str(new_quantity))
                pos.avg_cost = Decimal(str(new_avg_cost))
        self._session.add(Trade(portfolio_id=pf.id, symbol_id=sym_id, symbol=trade.symbol,
                                side=trade.side, quantity=trade.quantity,
                                fill_price=trade.fill_price,
                                avg_cost_at_fill=trade.avg_cost_at_fill,
                                qty_before=trade.qty_before, qty_after=trade.qty_after,
                                realised_pnl=trade.realised_pnl, ts=trade.ts))
        self._session.commit()

    def list_trades(self) -> list[PersistedTrade]:
        stmt = select(Trade).order_by(Trade.ts, Trade.id)
        return [PersistedTrade(ts=t.ts, symbol=t.symbol, side=t.side, quantity=t.quantity,
                               fill_price=t.fill_price, avg_cost_at_fill=t.avg_cost_at_fill,
                               qty_before=t.qty_before, qty_after=t.qty_after,
                               realised_pnl=t.realised_pnl)
                for t in self._session.scalars(stmt)]

    def count_trades(self) -> int:
        return self._session.scalar(select(func.count()).select_from(Trade)) or 0

    def clear_trades(self) -> None:
        self._session.execute(delete(Trade))
        self._session.commit()

    def reset_portfolio(self, starting_cash=None) -> PersistedPortfolio:
        pf = self._portfolio_row()
        if pf is None:
            return self.load_or_create_portfolio(
                starting_cash if starting_cash is not None else config.STARTING_CASH)
        self._session.execute(delete(Position).where(Position.portfolio_id == pf.id))
        pf.cash = pf.starting_cash
        pf.realised_pnl = Decimal("0")
        pf.reset_at = time.time()
        # a reset re-bases everything: drop history, drop the backtest series, re-seed the peak
        self._session.execute(
            delete(ValueHistory).where(ValueHistory.portfolio_id == pf.id))
        self._session.execute(
            delete(VarBacktestRow).where(VarBacktestRow.portfolio_id == pf.id))
        pf.peak_value = pf.starting_cash
        pf.peak_ts = pf.reset_at
        self._session.commit()
        return PersistedPortfolio(starting_cash=pf.starting_cash, cash=pf.cash,
                                  realised_pnl=pf.realised_pnl)

    # -- value-history + all-time peak --------------------------------------- #
    def append_value_history(self, *, ts, portfolio_value, cash, positions_value,
                             stale, cap, peak_value=None, peak_ts=None) -> None:
        # appends a point then prunes the oldest rows down to cap
        pf = self._portfolio_row()
        if pf is None:
            return
        self._session.add(ValueHistory(
            portfolio_id=pf.id, ts=float(ts),
            portfolio_value=Decimal(str(portfolio_value)),
            cash=Decimal(str(cash)), positions_value=Decimal(str(positions_value)),
            stale=bool(stale)))
        self._session.flush()
        count = self._session.scalar(
            select(func.count()).select_from(ValueHistory)
            .where(ValueHistory.portfolio_id == pf.id)) or 0
        if cap and count > cap:
            old_ids = list(self._session.scalars(
                select(ValueHistory.id).where(ValueHistory.portfolio_id == pf.id)
                .order_by(ValueHistory.ts, ValueHistory.id).limit(count - cap)))
            if old_ids:
                self._session.execute(
                    delete(ValueHistory).where(ValueHistory.id.in_(old_ids)))
        if peak_value is not None:                  # piggyback the peak onto this same commit
            pf.peak_value = Decimal(str(peak_value))
            pf.peak_ts = None if peak_ts is None else float(peak_ts)
        self._session.commit()

    def list_value_history(self) -> list[PersistedValueSample]:
        pf = self._portfolio_row()
        if pf is None:
            return []
        stmt = (select(ValueHistory).where(ValueHistory.portfolio_id == pf.id)
                .order_by(ValueHistory.ts, ValueHistory.id))
        return [PersistedValueSample(ts=v.ts, portfolio_value=v.portfolio_value,
                                     cash=v.cash, positions_value=v.positions_value,
                                     stale=bool(v.stale))
                for v in self._session.scalars(stmt)]

    def count_value_history(self) -> int:
        pf = self._portfolio_row()
        if pf is None:
            return 0
        return self._session.scalar(
            select(func.count()).select_from(ValueHistory)
            .where(ValueHistory.portfolio_id == pf.id)) or 0

    def get_peak(self) -> PersistedPeak:
        pf = self._portfolio_row()
        if pf is None:
            return PersistedPeak(None, None)
        return PersistedPeak(peak_value=pf.peak_value, peak_ts=pf.peak_ts)

    def set_peak(self, peak_value, peak_ts) -> None:
        # writes whatever it is given; the worker is what enforces rise-only
        pf = self._portfolio_row()
        if pf is None:
            return
        pf.peak_value = None if peak_value is None else Decimal(str(peak_value))
        pf.peak_ts = None if peak_ts is None else float(peak_ts)
        self._session.commit()

    def rebase_value_history(self, *, ts, value, timeframe: Optional[str] = None) -> None:
        # called when the risk timeframe switches: wipe history, re-seed the peak
        pf = self._portfolio_row()
        if pf is None:
            return
        self._session.execute(
            delete(ValueHistory).where(ValueHistory.portfolio_id == pf.id))
        pf.peak_value = Decimal(str(value))
        pf.peak_ts = float(ts)
        if timeframe is not None:
            payload = json.dumps(timeframe)
            row = self._session.get(Setting, RISK_TIMEFRAME_KEY)
            if row is None:
                self._session.add(Setting(key=RISK_TIMEFRAME_KEY, value=payload,
                                          value_type="json"))
            else:
                row.value = payload
        self._session.commit()

    # -- the DailyBar cache (worker-written) --------------------------------- #
    def upsert_daily_bars(self, symbol: str, rows) -> int:
        sym_id = self._symbol_id_for(symbol)
        if sym_id is None or not rows:
            return 0
        existing = {b.ts: b for b in self._session.scalars(
            select(DailyBar).where(DailyBar.symbol_id == sym_id))}
        n = 0
        for row in rows:
            ts = float(row.ts)
            bar = existing.get(ts)
            if bar is None:
                self._session.add(DailyBar(
                    symbol_id=sym_id, ts=ts, open=float(row.open),
                    high=float(row.high), low=float(row.low),
                    close=float(row.close), adj_close=float(row.adj_close),
                    volume=float(row.volume), div_cash=float(row.div_cash),
                    split_factor=float(row.split_factor)))
            else:
                bar.open, bar.high = float(row.open), float(row.high)
                bar.low, bar.close = float(row.low), float(row.close)
                bar.adj_close = float(row.adj_close)
                bar.volume = float(row.volume)
                bar.div_cash = float(row.div_cash)
                bar.split_factor = float(row.split_factor)
            n += 1
        self._session.commit()
        return n

    def list_daily_bars(self, symbol: str, limit: Optional[int] = None
                        ) -> list[PersistedDailyBar]:
        # takes the most-recent `limit` bars but hands them back oldest-first
        sym_id = self._symbol_id_for(symbol)
        if sym_id is None:
            return []
        stmt = (select(DailyBar).where(DailyBar.symbol_id == sym_id)
                .order_by(DailyBar.ts.desc()))
        if limit:
            stmt = stmt.limit(int(limit))
        rows = list(self._session.scalars(stmt))
        rows.reverse()
        return [PersistedDailyBar(ts=b.ts, open=b.open, high=b.high, low=b.low,
                                  close=b.close, adj_close=b.adj_close,
                                  volume=b.volume, div_cash=b.div_cash,
                                  split_factor=b.split_factor) for b in rows]

    def latest_daily_bar_ts(self, symbol: str) -> Optional[float]:
        sym_id = self._symbol_id_for(symbol)
        if sym_id is None:
            return None
        return self._session.scalar(
            select(func.max(DailyBar.ts)).where(DailyBar.symbol_id == sym_id))

    def clear_daily_bars(self, symbol: str) -> None:
        # used before a full re-pull when a corporate action invalidates the cache
        sym_id = self._symbol_id_for(symbol)
        if sym_id is None:
            return
        self._session.execute(delete(DailyBar).where(DailyBar.symbol_id == sym_id))
        self._session.commit()

    # -- the one-time legacy-schema migration -------------------------------- #
    def migrate_legacy_schema(self) -> bool:
        # runs at most once, guarded by a marker row; fixes old providers and crypto tickers
        marker = self._session.get(Setting, SCHEMA_MIGRATION_KEY)
        if marker is not None:
            return False
        migrated = 0
        try:
            for sym in self._session.scalars(select(Symbol)):
                if sym.asset_class == "stock" and sym.provider == "yfinance":
                    sym.provider = "finnhub"
                    migrated += 1
                elif sym.asset_class == "crypto" and "/" in sym.ticker:
                    base, _, quote = sym.ticker.partition("/")
                    if quote.upper() in ("USDT", "USDC"):
                        target = f"{base}/USD"
                        clash = self._session.scalar(
                            select(Symbol).where(Symbol.ticker == target,
                                                 Symbol.provider == sym.provider))
                        if clash is not None:
                            log.warning("legacy-schema migration: %s -> %s skipped "
                                        "(target exists)", sym.ticker, target)
                            continue
                        sym.ticker = target
                        sym.quote_currency = "USD"
                        sym.display_name = target
                        migrated += 1
            self._session.add(Setting(key=SCHEMA_MIGRATION_KEY,
                                      value=json.dumps({"done": True,
                                                        "ts": time.time(),
                                                        "migrated": migrated}),
                                      value_type="json"))
            self._session.commit()
        except Exception:
            self._session.rollback()
            log.exception("legacy-schema migration failed; will retry next launch")
            return False
        log.info("legacy-schema migration ran (%d row(s) updated)", migrated)
        return True

    # -- the VaR backtest series --------------------------------------------- #
    def upsert_backtest_forecast(self, forecast_ts: float, var99_pct: float,
                                 weights: dict) -> None:
        # only an unresolved day's forecast is refreshed; resolved rows are left alone
        pf = self._portfolio_row()
        if pf is None:
            return
        row = self._session.scalar(
            select(VarBacktestRow).where(
                VarBacktestRow.portfolio_id == pf.id,
                VarBacktestRow.forecast_ts == float(forecast_ts)))
        if row is None:
            self._session.add(VarBacktestRow(
                portfolio_id=pf.id, forecast_ts=float(forecast_ts),
                var99_pct=float(var99_pct), weights_json=json.dumps(weights)))
        elif row.realised_pct is None:
            row.var99_pct = float(var99_pct)
            row.weights_json = json.dumps(weights)
        self._session.commit()

    def open_backtest_rows(self) -> list[PersistedBacktestRow]:
        pf = self._portfolio_row()
        if pf is None:
            return []
        stmt = (select(VarBacktestRow)
                .where(VarBacktestRow.portfolio_id == pf.id,
                       VarBacktestRow.realised_pct.is_(None))
                .order_by(VarBacktestRow.forecast_ts))
        out = []
        for row in self._session.scalars(stmt):
            try:
                weights = json.loads(row.weights_json)
            except (TypeError, ValueError):
                weights = {}
            out.append(PersistedBacktestRow(
                forecast_ts=row.forecast_ts, var99_pct=row.var99_pct,
                weights=weights if isinstance(weights, dict) else {},
                realised_pct=None, exception=None))
        return out

    def resolve_backtest_row(self, forecast_ts: float, realised_pct: float,
                             exception: bool, resolved_ts: float) -> bool:
        pf = self._portfolio_row()
        if pf is None:
            return False
        row = self._session.scalar(
            select(VarBacktestRow).where(
                VarBacktestRow.portfolio_id == pf.id,
                VarBacktestRow.forecast_ts == float(forecast_ts)))
        if row is None or row.realised_pct is not None:
            return False
        row.realised_pct = float(realised_pct)
        row.exception = bool(exception)
        row.resolved_ts = float(resolved_ts)
        self._session.commit()
        return True

    def list_resolved_backtest_rows(self, limit: int = 250
                                    ) -> list[PersistedBacktestRow]:
        # newest `limit` resolved rows, returned oldest-first
        pf = self._portfolio_row()
        if pf is None:
            return []
        stmt = (select(VarBacktestRow)
                .where(VarBacktestRow.portfolio_id == pf.id,
                       VarBacktestRow.realised_pct.is_not(None))
                .order_by(VarBacktestRow.forecast_ts.desc()).limit(int(limit)))
        rows = list(self._session.scalars(stmt))
        rows.reverse()
        out = []
        for row in rows:
            try:
                weights = json.loads(row.weights_json)
            except (TypeError, ValueError):
                weights = {}
            out.append(PersistedBacktestRow(
                forecast_ts=row.forecast_ts, var99_pct=row.var99_pct,
                weights=weights if isinstance(weights, dict) else {},
                realised_pct=row.realised_pct, exception=row.exception))
        return out

    def backtest_counts(self, window: int = 250) -> tuple[int, int]:
        # returns (exceptions, observations) over the newest resolved window
        pf = self._portfolio_row()
        if pf is None:
            return (0, 0)
        stmt = (select(VarBacktestRow)
                .where(VarBacktestRow.portfolio_id == pf.id,
                       VarBacktestRow.realised_pct.is_not(None))
                .order_by(VarBacktestRow.forecast_ts.desc()).limit(int(window)))
        rows = list(self._session.scalars(stmt))
        return (sum(1 for r in rows if r.exception), len(rows))

    # -- lifecycle ------------------------------------------------------------ #
    def close(self) -> None:
        try:
            self._session.close()
        finally:
            self._engine.dispose()


# --------------------------------------------------------------------------- #
# Opening with recovery (backup + recreate)
# --------------------------------------------------------------------------- #
def _sqlite_path(url: str) -> Optional[str]:
    prefix = "sqlite:///"
    if url.startswith(prefix) and ":memory:" not in url:
        return url[len(prefix):]
    return None


def open_repository(url: Optional[str] = None) -> MahadRepository:
    # on a corrupt file, back it up and recreate; a lock error is re-raised untouched
    url = url or config.default_db_url()
    corrupt_path: Optional[str] = None
    reason = ""
    try:
        return MahadRepository(url)
    except OperationalError:
        log.exception("DB open failed with a lock-style error; NOT rotating the file")
        raise
    except (SchemaMismatch, DatabaseError) as exc:
        path = _sqlite_path(url)
        if not path or not os.path.exists(path):
            raise
        corrupt_path = path
        reason = str(exc)
    # rotate outside the except block so gc can reclaim the orphaned handle first
    gc.collect()
    if corrupt_path is not None:
        log.warning("DB recovery: backing up + recreating (%s)", reason)
        stamp = int(time.time())
        for suffix in ("", "-wal", "-shm"):
            src = corrupt_path + suffix
            if os.path.exists(src):
                try:
                    os.replace(src, f"{corrupt_path}.corrupt-{stamp}{suffix}")
                except OSError:
                    log.exception("DB recovery: backup of %s failed", src)
    return MahadRepository(url)
