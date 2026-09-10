# the risk-analytics assembly, sectors, stress rows, the backtest accrual
from __future__ import annotations

import datetime as _dt
import logging
from typing import Optional


from mahad import config
from mahad.data.portfolio_view import (ContributionRow, RiskAnalyticsView,
                                       StressRow)
from mahad.data.repository import (SECTORS_KEY)
from mahad.data.source import (is_crypto_symbol)
from mahad.engine.portfolio import (unrealised)
from mahad.engine import returns as eng_returns
from mahad.engine import risk_metrics as eng_rm

from mahad.worker.state import WorkerState

log = logging.getLogger("mahad.worker")



class AnalyticsMixin(WorkerState):
    def _load_sectors(self) -> None:
        # local fallback map, overlaid with whatever profile2 lookups we've cached
        self._sectors = dict(config.DEFAULT_SECTOR_MAP)
        cached = self._get_setting(SECTORS_KEY)
        if isinstance(cached, dict):
            for k, v in cached.items():
                if isinstance(k, str) and isinstance(v, str) and v:
                    self._sectors[k] = v

    def _sector_for(self, symbol: str) -> str:
        if is_crypto_symbol(symbol):
            return "Crypto"
        return self._sectors.get(symbol, "Unclassified")

    def _fetch_sector_once(self, symbol: str) -> None:
        # a single profile2 call when a stock is added, then cached for good
        if is_crypto_symbol(symbol) or symbol in self._sectors:
            return
        src = self._get_source(symbol)
        fetcher = getattr(src, "fetch_profile_sector", None)
        if not callable(fetcher):
            return
        try:
            sector, err = fetcher(symbol)
        except Exception:                              # defensive
            log.exception("sector fetch failed (%s)", symbol)
            return
        if err is None and sector:
            self._sectors[symbol] = sector
            try:
                cached = self._get_setting(SECTORS_KEY)
                payload = dict(cached) if isinstance(cached, dict) else {}
                payload[symbol] = sector
                self._set_setting(SECTORS_KEY, payload)
            except Exception:
                log.exception("sector cache persist failed")

    def _rebuild_risk_analytics(self) -> None:
        try:
            self._build_asset_data()
            self._refresh_analytics_view()
            self._accrue_backtest()
            self._refresh_analytics_view()            # counts may have moved
            self._integrity = self._build_integrity_view()
            self._risk_dirty = False
            self._emit_snapshot(None)
        except Exception:                              # structural never-raise
            log.exception("risk analytics rebuild failed; keeping the prior view")
            self._risk_dirty = False

    def _build_asset_data(self) -> None:
        out_r: dict[str, list[tuple[_dt.date, float]]] = {}
        out_c: dict[str, list[tuple[_dt.date, float]]] = {}
        if self._repo is None:
            self._asset_returns, self._asset_closes = out_r, out_c
            return
        symbols = set(self._daily_coverage_symbols())
        for sym in symbols:
            try:
                rows = self._repo.list_daily_bars(sym, limit=config.HISTORY_CAP)
            except Exception:
                log.exception("daily-bar read failed (%s)", sym)
                continue
            if not rows:
                continue
            closes = eng_returns.align_daily_closes(
                (r.ts, r.adj_close) for r in rows)
            if not closes:
                continue
            out_c[sym] = closes
            rets = eng_returns.simple_returns_by_date(closes)
            if rets:
                out_r[sym] = rets
        self._asset_returns, self._asset_closes = out_r, out_c

    def _current_weights_and_value(self) -> tuple[dict[str, float], float]:
        positions = []
        for p in self._portfolio.positions:
            q = self._marks.get(p.symbol)
            if q is not None:
                positions.append((p.symbol, float(p.quantity), float(q.mark)))
        value_dec, _, cash, _ = self._value_now()
        return (eng_returns.current_weights(positions, float(cash)),
                float(value_dec))

    def _refresh_analytics_view(self) -> None:
        try:
            self._analytics = self._build_analytics_view()
        except Exception:
            log.exception("analytics view build failed; keeping the prior view")

    def _build_analytics_view(self) -> RiskAnalyticsView:
        weights, value = self._current_weights_and_value()
        if not weights:
            return RiskAnalyticsView(available=False, note="no positions",
                                     portfolio_value=value)
        pr = eng_returns.portfolio_returns(weights, self._asset_returns,
                                           config.RISK_WINDOW)
        stock_missing = [s for s in pr.excluded if not is_crypto_symbol(s)]
        if pr.n == 0:  # gate on n
            note = ("needs history - free Tiingo key (tiingo.com)"
                    if (stock_missing and any(
                        getattr(self._get_source(s), "history_needs_key", False)
                        for s in stock_missing))
                    else "warming - no overlapping daily history yet")
            return RiskAnalyticsView(available=False, note=note,
                                     excluded=pr.excluded,
                                     coverage_weight=pr.coverage_weight,
                                     portfolio_value=value)
        rets = list(pr.returns)
        var95 = eng_rm.historical_var(rets, 0.95)
        var95_usd = (var95.value * value if var95 else None)
        var99 = eng_rm.historical_var(rets, config.BACKTEST_CONFIDENCE)
        es975 = eng_rm.expected_shortfall(rets, config.ES_CONFIDENCE)
        # risk-free input: the Treasury 3M par yield
        rf_annual = self._ctx_yields.y3m if self._ctx_yields.available else None
        rf_daily = eng_returns.rf_daily_from_annual_pct(rf_annual)
        sharpe_res = (eng_rm.sharpe(rets, rf_daily)
                      if rf_daily is not None else None)
        sortino_res = eng_rm.sortino(rets)
        bench = self._asset_returns.get(config.BENCHMARK_SYMBOL)
        beta_val = None
        if bench:
            bench_map = dict(bench)
            paired_p, paired_b = [], []
            for d, r in zip(pr.dates, pr.returns, strict=False):
                rb = bench_map.get(d)
                if rb is not None:
                    paired_p.append(r)
                    paired_b.append(rb)
            beta_val = eng_rm.beta(paired_p, paired_b)
        held = {p.symbol for p in self._portfolio.positions}
        corr_in = {s: [r for _, r in self._asset_returns[s]]
                   for s in sorted(held) if s in self._asset_returns}
        corr_symbols: tuple[str, ...] = ()
        corr_matrix: tuple[tuple[Optional[float], ...], ...] = ()
        if len(corr_in) >= 2:
            corr_symbols, corr_matrix = eng_rm.correlation_matrix(
                corr_in, config.CORRELATION_WINDOW)
        corr_sum = (eng_rm.correlation_summary(corr_symbols, corr_matrix)
                    if corr_matrix else None)
        position_values = {}
        for p in self._portfolio.positions:
            q = self._marks.get(p.symbol)
            if q is not None:
                position_values[p.symbol] = float(p.quantity) * float(q.mark)
        conc = None
        if position_values:
            conc = eng_rm.concentration(
                position_values,
                {s: self._sector_for(s) for s in position_values})
        dd = eng_rm.drawdown_duration([s.value for s in self._value_history])
        # component VaR / risk contributions on the same common grid
        comp = None
        if pr.n >= 2 and pr.included:
            # reuse the alignment portfolio_returns already built
            comp = eng_rm.component_var(
                {s: weights[s] for s in pr.included if s in weights},
                pr.aligned, config.COMPONENT_VAR_CONFIDENCE)
        contributions: tuple[ContributionRow, ...] = ()
        comp_sigma = comp_var_pct = comp_var_usd = None
        if comp is not None:
            comp_sigma = comp.portfolio_sigma
            comp_var_pct = comp.portfolio_var
            comp_var_usd = comp.portfolio_var * value
            contributions = tuple(
                ContributionRow(symbol=rc.symbol, weight=rc.weight, pct=rc.pct,
                                comp_var_pct=rc.comp_var,
                                comp_var_usd=rc.comp_var * value)
                for rc in comp.contributions)
        x, t = (0, 0)
        if self._repo is not None:
            try:
                x, t = self._repo.backtest_counts(config.RISK_WINDOW)
            except Exception:
                log.exception("backtest counts read failed")
        mode = "ex-ante" if t >= config.RISK_WINDOW else "accruing"
        bx, bt = x, t
        if t < config.RISK_WINDOW:
            # roll the trailing window across the full cached series
            pr_full = eng_returns.portfolio_returns(weights,
                                                    self._asset_returns,
                                                    window=0)
            bc = eng_rm.backcast_exceptions(list(pr_full.returns),
                                            config.BACKTEST_CONFIDENCE,
                                            config.RISK_WINDOW)
            if bc is not None and bc.observations > 0:
                mode = "backcast"
                bx, bt = bc.exceptions, bc.observations
        kup = (eng_rm.kupiec_pof(bx, bt, 1.0 - config.BACKTEST_CONFIDENCE)
               if bt > 0 else None)
        # P&L-to-risk linkage: total P&L against the 1-day 95% VaR
        marks_dec = {}
        for p in self._portfolio.positions:
            md, _st = self._mark_decimal(p.symbol)
            if md is not None:
                marks_dec[p.symbol] = md
        unreal_pnl = float(unrealised(self._portfolio, marks_dec))
        realised_pnl = float(self._portfolio.realised_pnl)
        total_pnl = realised_pnl + unreal_pnl
        pnl_to_var = eng_rm.return_on_risk(total_pnl, var95_usd)
        unreal_to_var = eng_rm.return_on_risk(unreal_pnl, var95_usd)
        # rolling VaR history + trend
        var_hist = eng_rm.rolling_var(rets, 0.95, config.VAR_TREND_WINDOW,
                                      config.VAR_TREND_POINTS)
        var_trend = ""
        if len(var_hist) >= 2 and var_hist[0] > 0.0:
            delta = var_hist[-1] - var_hist[0]
            thr = 0.05 * var_hist[0]
            var_trend = ("rising" if delta > thr
                         else "falling" if delta < -thr else "flat")
        return RiskAnalyticsView(
            available=True, note="", n=pr.n, window=config.RISK_WINDOW,
            as_of=(pr.dates[-1].isoformat() if pr.dates else ""),
            excluded=pr.excluded, coverage_weight=pr.coverage_weight,
            portfolio_value=value,
            var95_pct=(var95.value if var95 else None),
            var99_pct=(var99.value if var99 else None),
            var95_usd=var95_usd,
            var99_usd=(var99.value * value if var99 else None),
            es975_pct=(es975.value if es975 else None),
            es975_usd=(es975.value * value if es975 else None),
            pvar95_pct=eng_rm.parametric_var(rets, 0.95),
            pvar99_pct=eng_rm.parametric_var(rets, 0.99),
            backtest_mode=mode, backtest_exceptions=bx,
            backtest_observations=bt,
            backtest_zone=(eng_rm.basel_zone(bx) if bt > 0 else ""),
            accruing_n=t,
            kupiec_lr=(kup.lr if kup else None),
            kupiec_p=(kup.p_value if kup else None),
            kupiec_reject=(kup.reject if kup else None),
            beta_spy=beta_val,
            sharpe_annual=(sharpe_res.annualised if sharpe_res else None),
            sortino_annual=(sortino_res.annualised if sortino_res else None),
            rf_annual_pct=rf_annual,
            rf_as_of=(self._ctx_yields.as_of if rf_annual is not None else ""),
            rf_source=("US Treasury 3M par yield" if rf_annual is not None
                       else ""),
            ewma_vol_pct=(lambda v: v * 100.0 if v is not None else None)(
                eng_rm.ewma_volatility(rets)),
            corr_symbols=corr_symbols, corr_matrix=corr_matrix,
            corr_window=config.CORRELATION_WINDOW,
            corr_avg=(corr_sum.avg if corr_sum else None),
            corr_max_pair=(corr_sum.max_pair if corr_sum else ()),
            corr_min_pair=(corr_sum.min_pair if corr_sum else ()),
            hhi=(conc.hhi if conc else None),
            effective_n=(conc.effective_n if conc else None),
            top_symbol=(conc.top_symbol if conc else ""),
            top_weight=(conc.top_weight if conc else None),
            sector_hhi=(conc.sector_hhi if conc else None),
            sector_weights=(conc.sector_weights if conc else ()),
            dd_depth_pct=(dd.depth_pct if dd else None),
            dd_duration_periods=(dd.duration_periods if dd else None),
            dd_ongoing_periods=(dd.ongoing_periods if dd else None),
            stress=self._stress_rows(weights, value),
            comp_confidence=config.COMPONENT_VAR_CONFIDENCE,
            comp_sigma_pct=comp_sigma, comp_var_pct=comp_var_pct,
            comp_var_usd=comp_var_usd, contributions=contributions,
            pnl_total_usd=total_pnl, pnl_unrealised_usd=unreal_pnl,
            pnl_realised_usd=realised_pnl, pnl_to_var95=pnl_to_var,
            unreal_to_var95=unreal_to_var,
            var_history=var_hist, var_trend=var_trend)

    def _stress_window_return(self, scenario: str, symbol: str, start: str,
                              end: str) -> Optional[tuple[float, str]]:
        # prefer the cached close-to-close return, fall back to a cited constant, else nothing
        closes = self._asset_closes.get(symbol)
        if closes:
            d0 = _dt.date.fromisoformat(start)
            d1 = _dt.date.fromisoformat(end)
            inside = [(d, c) for d, c in closes if d0 <= d <= d1]
            if (len(inside) >= 2
                    and (inside[0][0] - d0).days <= 5
                    and (d1 - inside[-1][0]).days <= 5):
                return (inside[-1][1] / inside[0][1] - 1.0, "cache")
        const = config.STRESS_CONSTANTS.get((scenario, symbol))
        return None if const is None else (const, "constant")

    def _stress_rows(self, weights: dict[str, float], value: float) -> tuple[StressRow, ...]:
        rows = []
        for name, start, end in config.STRESS_SCENARIOS:
            window_returns: dict[str, tuple[float, str]] = {}
            for sym in weights:
                entry = self._stress_window_return(name, sym, start, end)
                if entry is not None:
                    window_returns[sym] = entry
            res = eng_rm.stress_replay(name, start, end, value, weights,
                                       window_returns)
            rows.append(StressRow(
                scenario=name, start=start, end=end, pl_usd=res.pl_usd,
                covered_weight=res.covered_weight,
                legs_no_data=tuple(leg.symbol for leg in res.legs
                                   if leg.window_return is None),
                constant_legs=tuple(leg.symbol for leg in res.legs
                                    if leg.source == "constant")))
        return tuple(rows)

    def _accrue_backtest(self) -> None:
        # settle yesterday's open forecasts against realised returns, then log today's
        if self._repo is None:
            return
        # resolution first, independent of the current book's grid
        day_maps: dict[_dt.date, dict[str, float]] = {}
        for sym, rows in self._asset_returns.items():
            for d, r in rows:
                day_maps.setdefault(d, {})[sym] = r
        try:
            open_rows = self._repo.open_backtest_rows()
        except Exception:
            log.exception("open backtest rows read failed")
            open_rows = []
        union_dates = sorted(day_maps)
        for row in open_rows:
            f_date = _dt.datetime.fromtimestamp(
                row.forecast_ts, _dt.UTC).date()
            # the forecast's own next trading day with usable returns
            resolved = False
            for nxt in union_dates:
                if nxt <= f_date:
                    continue
                realised = eng_returns.single_day_return(
                    row.weights, day_maps.get(nxt, {}))
                if not realised.included:
                    continue                        # none of the book traded
                try:
                    self._repo.resolve_backtest_row(
                        row.forecast_ts, realised.value,
                        exception=(realised.value < -row.var99_pct),
                        resolved_ts=self._wallclock())
                except Exception:
                    log.exception("backtest resolve failed")
                resolved = True
                break
            if not resolved:
                continue                            # stays open until data lands
        # then today's forecast on the current book's as-if series
        weights, _value = self._current_weights_and_value()
        if not weights:
            return
        pr = eng_returns.portfolio_returns(weights, self._asset_returns,
                                           config.RISK_WINDOW)
        if pr.n == 0:
            return
        var99 = eng_rm.historical_var(list(pr.returns),
                                      config.BACKTEST_CONFIDENCE)
        if var99 is None:
            return
        last = list(pr.dates)[-1]
        last_ts = _dt.datetime(last.year, last.month, last.day,
                               tzinfo=_dt.UTC).timestamp()
        try:
            self._repo.upsert_backtest_forecast(last_ts, var99.value, weights)
        except Exception:
            log.exception("backtest forecast persist failed")
