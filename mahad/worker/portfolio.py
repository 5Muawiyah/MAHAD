# the simulated book: marks, views, value-history sampling, orders
from __future__ import annotations

import logging
from collections import deque
from decimal import Decimal, InvalidOperation
from typing import Optional

from PySide6.QtCore import Slot

from mahad import config
from mahad.data.portfolio_view import ExposureRow, PortfolioView, PositionRow, RiskView, TradeRow
from mahad.data.repository import PersistedTrade
from mahad.data.source import is_crypto_symbol
from mahad.engine.portfolio import (PortfolioState, Position as EngPosition, TradeFill,
                                    place_order as _place_order, unrealised, portfolio_value)
from mahad.engine.risk import (ValueSample, exposure as _exposure,
                               simple_returns as _simple_returns, volatility as _volatility,
                               max_drawdown as _max_drawdown)
from mahad.worker.state import WorkerState

log = logging.getLogger("mahad.worker")


class PortfolioMixin(WorkerState):
    def _load_portfolio(self) -> None:
        try:
            pp = self._repo.load_or_create_portfolio(config.STARTING_CASH)  # type: ignore[union-attr] # repo seam guarded by the except boundary
            positions = self._repo.get_positions()  # type: ignore[union-attr] # repo seam guarded by the except boundary
            self._starting_cash = pp.starting_cash
            self._portfolio = PortfolioState(
                cash=pp.cash, realised_pnl=pp.realised_pnl,
                positions=tuple(EngPosition(p.symbol, p.quantity, p.avg_cost)
                                for p in positions))
            self._trades = list(self._repo.list_trades())  # type: ignore[union-attr] # repo seam guarded by the except boundary
        except Exception:
            log.exception("portfolio load failed; starting flat")
            self._starting_cash = Decimal(str(config.STARTING_CASH))
            self._portfolio = PortfolioState(cash=self._starting_cash,
                                             realised_pnl=Decimal("0"), positions=())
            self._trades = []

    def _mark_decimal(self, symbol: str) -> tuple[Optional[Decimal], bool]:
        q = self._marks.get(symbol)
        if q is None:
            return None, False
        return Decimal(str(q.mark)), bool(
            q.stale or config.is_stale(q.ts, poll_interval_s=self._poll_interval_s))

    def _build_portfolio_view(self) -> PortfolioView:
        marks: dict[str, Decimal] = {}
        has_marks = False
        any_stale = False
        rows = []
        for p in self._portfolio.positions:
            m, stale = self._mark_decimal(p.symbol)
            asset_class = "crypto" if is_crypto_symbol(p.symbol) else "stock"
            if m is not None:
                marks[p.symbol] = m
                has_marks = True
                any_stale = any_stale or stale
                rows.append(PositionRow(p.symbol, asset_class, p.quantity, p.avg_cost,
                                        mark=m, unrealised=p.quantity * (m - p.avg_cost),
                                        value=p.quantity * m, stale=stale))
            else:
                any_stale = True                  # a missing mark is stale
                rows.append(PositionRow(p.symbol, asset_class, p.quantity, p.avg_cost))
        unreal = unrealised(self._portfolio, marks)  # three valuation views agree
        value = portfolio_value(self._portfolio, marks)
        trades = tuple(TradeRow(t.ts, t.symbol, t.side, t.quantity, t.fill_price,
                                t.avg_cost_at_fill, t.qty_before, t.qty_after, t.realised_pnl)
                       for t in self._trades)
        return PortfolioView(
            starting_cash=self._starting_cash, cash=self._portfolio.cash,
            realised_pnl=self._portfolio.realised_pnl, unrealised_pnl=unreal,
            total_value=value, total_pnl=self._portfolio.realised_pnl + unreal,
            positions=tuple(rows), trades=trades, has_marks=has_marks,
            any_marks_stale=any_stale,
            gbp_rate=(self._ctx_fx.rate if self._ctx_fx.available else None),
            gbp_as_of=(self._ctx_fx.as_of if self._ctx_fx.available else ""),
            gbp_note=(self._ctx_fx.note if self._ctx_fx.available else ""))

    def _value_now(self) -> tuple[Decimal, Decimal, Decimal, bool]:
        cash = self._portfolio.cash
        positions_value = Decimal("0")
        stale = False
        for p in self._portfolio.positions:
            m, st = self._mark_decimal(p.symbol)
            if m is not None:
                positions_value += p.quantity * m
                stale = stale or st
            else:
                stale = True
        value = cash + positions_value
        return value, positions_value, cash, (stale if self._portfolio.positions else False)

    def _load_value_history(self) -> None:
        try:
            peak = self._repo.get_peak() if self._repo is not None else None
            self._peak_value = peak.peak_value if peak is not None else None
            self._peak_ts = peak.peak_ts if peak is not None else None
            samples = self._repo.list_value_history() if self._repo is not None else []
            self._value_history = deque(
                (ValueSample(ts=s.ts, value=float(s.portfolio_value), stale=bool(s.stale))
                 for s in samples), maxlen=config.VALUE_HISTORY_CAP)
        except Exception:
            log.exception("value-history load failed; starting empty")
            self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)
            self._peak_value = None
            self._peak_ts = None

    @Slot()
    def _sample_value_history(self) -> None:
        if self._stop or self._repo is None:
            return
        try:
            now = self._wallclock()
            value, positions_value, cash, stale = self._value_now()
            peak_changed = self._peak_value is None or value > self._peak_value
            if peak_changed:
                self._peak_value, self._peak_ts = value, now
            try:
                self._repo.append_value_history(
                    ts=now, portfolio_value=value, cash=cash,
                    positions_value=positions_value, stale=stale,
                    cap=config.VALUE_HISTORY_CAP,
                    peak_value=(self._peak_value if peak_changed else None),
                    peak_ts=(self._peak_ts if peak_changed else None))  # one commit
            except Exception:
                log.exception("value-history persist failed; keeping in-memory series")
            self._value_history.append(ValueSample(ts=now, value=float(value), stale=stale))
            self._refresh_analytics_view()  # fresh USD figures + dd
            self._emit_snapshot(None)
        except Exception:                                     # structural never-raise
            log.exception("value-history sample failed; skipping this tick")

    @Slot(str)
    def set_risk_timeframe(self, timeframe: str) -> None:
        # changing cadence re-bases the value-history; the old series can't be re-spaced
        if timeframe not in config.VALID_RISK_TIMEFRAMES:
            return
        if timeframe == self._risk_timeframe:
            self.settings_applied.emit("risk timeframe already " + timeframe)
            return
        self._risk_timeframe = timeframe
        now = self._wallclock()
        value, _, _, _ = self._value_now()
        try:
            if self._repo is not None:
                self._repo.rebase_value_history(ts=now, value=value,
                                                timeframe=timeframe)    # one commit
        except Exception:
            log.exception("risk timeframe rebase failed")
        self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)
        self._peak_value, self._peak_ts = value, now
        self._next_sample_due = now + config.risk_timeframe_seconds(timeframe)  # re-anchor
        self.settings_applied.emit("applied (next cycle)")
        self._emit_snapshot(None)

    def _build_risk_view(self) -> RiskView:
        cash = self._portfolio.cash
        positions_value = Decimal("0")
        any_stale = False
        per_pos = []
        for p in self._portfolio.positions:
            m, st = self._mark_decimal(p.symbol)
            if m is not None:
                val = p.quantity * m
                positions_value += val
                per_pos.append((p.symbol, val))
                any_stale = any_stale or st
            else:
                any_stale = True
        port_value = cash + positions_value
        empty = (len(self._portfolio.positions) == 0 and len(self._trades) == 0)

        exp = _exposure(float(positions_value), float(port_value))
        exp_rows: tuple[ExposureRow, ...] = ()
        if exp.defined and float(port_value) > 0.0:
            denom = float(port_value)
            exp_rows = tuple(ExposureRow(sym, float(val) / denom) for sym, val in per_pos)
        exp_out = bool(exp.out_of_range and not any_stale)        # surfaced only when non-stale

        samples = list(self._value_history)
        returns, skipped = _simple_returns(samples)
        vol = _volatility(returns, self._risk_timeframe, window=config.VOLATILITY_WINDOW)
        # seed the running max with the persisted peak only when it predates the window
        peak_v: Optional[float] = None
        peak_ts: Optional[float] = None
        if (self._peak_value is not None and self._peak_ts is not None
                and samples and self._peak_ts <= samples[0].ts):
            peak_v = float(self._peak_value)               # explicit narrowing
            peak_ts = self._peak_ts
        dd = _max_drawdown(samples, peak_value=peak_v, peak_ts=peak_ts)

        spark = tuple(s.value for s in samples)
        trough_idx: Optional[int] = None
        if dd.trough_ts is not None:
            for i, s in enumerate(samples):
                if s.ts == dd.trough_ts:
                    trough_idx = i
                    break
        return RiskView(
            empty=empty, warming=(not vol.defined), any_stale=any_stale,
            returns_skipped_stale=skipped, timeframe=self._risk_timeframe,
            exp_defined=exp.defined,
            exp_abs=(positions_value if exp.defined else None),
            exp_pct=exp.pct, exp_out_of_range=exp_out, exp_rows=exp_rows,
            vol_defined=vol.defined, vol_period_pct=vol.per_period_pct,
            vol_annual_pct=vol.annualised_pct, vol_n=vol.n_returns,
            dd_defined=dd.defined, dd_pct=dd.max_dd_pct,
            dd_peak_ts=dd.peak_ts, dd_trough_ts=dd.trough_ts,
            spark=spark, spark_trough_idx=trough_idx,
            history=tuple((s.ts, s.value, s.stale) for s in samples))   # export rows

    def _emit_order_result(self, ok: bool, fill_mark: Optional[Decimal] = None,
                           summary: str = "", reason: str = "") -> None:
        self.order_result.emit({
            "ok": bool(ok),
            "fill_mark": (str(fill_mark) if fill_mark is not None else None),
            "summary": summary, "reason": reason})

    @Slot(object)
    def place_order(self, payload: object) -> None:
        # fills against the mark the UI froze at click; rejects a second concurrent submit
        if not isinstance(payload, dict):
            return
        if self._stop:                                         # drop intents after shutdown
            return
        if self._order_in_flight:                              # authoritative no-double-submit
            self._emit_order_result(False, reason="order already in progress")
            return
        self._order_in_flight = True
        try:
            side = str(payload.get("side") or "")
            raw_qty = payload.get("qty")
            symbol = str(payload.get("symbol") or self._symbol or "")
            frozen_mark = payload.get("mark")
            frozen_ts = payload.get("ts")
            if not symbol:
                self._emit_order_result(False, reason="add a symbol first")
                return
            if frozen_mark is None:
                self._emit_order_result(False, reason="warming up - no quote yet")
                return
            try:                                              # hostile payload mark
                fill_mark = Decimal(str(frozen_mark))
            except (InvalidOperation, ValueError, TypeError):
                self._emit_order_result(False, reason="no usable mark")
                return
            if not fill_mark.is_finite():
                self._emit_order_result(False, reason="no usable mark")
                return
            if frozen_ts is None or config.is_stale(
                    frozen_ts, poll_interval_s=self._poll_interval_s):  # gate the fill mark
                self._emit_order_result(False, reason="stale price - waiting for a fresh quote")
                return
            result = _place_order(self._portfolio, side, symbol, raw_qty, fill_mark)
            if not result.ok:
                self._emit_order_result(False, reason=result.reason)
                return
            assert result.fill is not None                    # ok=True carries a fill (engine contract)
            try:                                              # persist-before-adopt
                self._persist_fill(result.state, result.fill)
            except Exception:
                log.exception("persist fill failed; not adopting")
                self._emit_order_result(False, reason="could not save - please retry")
                return
            self._portfolio = result.state                    # adopt only after a clean commit
            self._refresh_analytics_view()  # weights changed
            self._emit_order_result(True, fill_mark=result.fill.fill_price,
                                    summary=f"filled @ {result.fill.fill_price}")
            self._emit_snapshot(None)
        except Exception:                                     # structural never-raise
            log.exception("place_order failed on a malformed intent")
            self._emit_order_result(False, reason="invalid order request")
        finally:
            self._order_in_flight = False

    def _persist_fill(self, state: PortfolioState, fill: TradeFill) -> None:
        pos = state.position(fill.symbol)
        trade = PersistedTrade(
            ts=self._wallclock(), symbol=fill.symbol, side=fill.side, quantity=fill.quantity,
            fill_price=fill.fill_price, avg_cost_at_fill=fill.avg_cost_at_fill,
            qty_before=fill.qty_before, qty_after=fill.qty_after,
            realised_pnl=fill.realised_pnl)
        self._repo.record_fill(  # type: ignore[union-attr] # repo seam guarded by the except boundary
            cash=state.cash, realised_pnl=state.realised_pnl, symbol=fill.symbol,
            new_quantity=(pos.quantity if pos is not None else None),
            new_avg_cost=(pos.avg_cost if pos is not None else None), trade=trade)
        self._trades.append(trade)

    @Slot(object)
    def reset_portfolio(self, payload: object) -> None:
        if self._repo is None or self._stop:
            return
        if self._reset_in_flight:
            return
        self._reset_in_flight = True
        try:
            also_clear = bool(isinstance(payload, dict) and payload.get("also_clear_log"))
            export_ok = bool(isinstance(payload, dict) and payload.get("export_succeeded"))
            try:
                pp = self._repo.reset_portfolio(config.STARTING_CASH)
                if also_clear and export_ok:
                    self._repo.clear_trades()
                    self._trades = []
            except Exception:
                log.exception("reset_portfolio failed")
                return
            self._portfolio = PortfolioState(cash=pp.cash, realised_pnl=pp.realised_pnl,
                                             positions=())
            self._value_history = deque(maxlen=config.VALUE_HISTORY_CAP)   # re-base
            self._refresh_analytics_view()  # the book is empty, so the old figures must not stand
            try:
                peak = self._repo.get_peak()
                self._peak_value, self._peak_ts = peak.peak_value, peak.peak_ts
            except Exception:
                log.exception("post-reset peak load failed; seeding from cash")
                self._peak_value, self._peak_ts = self._portfolio.cash, self._wallclock()
            self._emit_snapshot(None)
        finally:
            self._reset_in_flight = False

    @Slot(int)
    def clear_trade_log(self, expected_count: int = -1) -> None:
        # only clears if the log still matches what was exported, else a fresh trade is lost
        if self._repo is None or self._stop:
            return
        if expected_count >= 0 and len(self._trades) != expected_count:
            log.info("clear_trade_log skipped: log changed since export (%d != %d)",
                     len(self._trades), expected_count)
            self._emit_snapshot(None)
            return
        try:
            self._repo.clear_trades()
            self._trades = []
        except Exception:
            log.exception("clear_trade_log failed")
            return
        self._emit_snapshot(None)
