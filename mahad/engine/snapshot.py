from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence

from mahad.config import POLL_INTERVAL_S, RENDER_CAP, is_stale
from mahad.data.models import Candle, Quote
from mahad.data.portfolio_view import (PortfolioView, RiskAnalyticsView,
                                       RiskView)
from mahad.data.context_view import (DataIntegrityView, HealthView,
                                     MarketContextView)
from mahad.engine.indicators import (EMA, RSI, SMA, IndicatorSettings,
                                     bars_needed, compute)


@dataclass(frozen=True, slots=True)
class IndicatorLine:
    points: tuple[tuple[float, float], ...]
    period: int
    needs_more: int = 0

    @property
    def has_data(self) -> bool:
        return len(self.points) > 0


@dataclass(frozen=True, slots=True)
class RenderSnapshot:
    symbol: str
    points: tuple[tuple[float, float], ...]      # (ts_seconds, price), oldest -> newest
    quote: Optional[Quote]
    live: bool
    last_update_ts: Optional[float]
    error: Optional[str] = None
    settings: Optional[IndicatorSettings] = None
    sma: Optional[IndicatorLine] = None
    ema: Optional[IndicatorLine] = None
    rsi: Optional[IndicatorLine] = None
    closed_count: int = 0
    portfolio: Optional[PortfolioView] = None
    risk: Optional[RiskView] = None
    timeframe: str = ""
    context: Optional[MarketContextView] = None
    health: Optional[HealthView] = None
    analytics: Optional[RiskAnalyticsView] = None
    integrity: Optional[DataIntegrityView] = None
    session_state: str = ""
    session_summary: str = ""

    @property
    def has_data(self) -> bool:
        return len(self.points) > 0


def _indicator_line(kind: str, closed_closes: Sequence[float],
                    closed_ts: Sequence[float], period: int,
                    render_cap: Optional[int]) -> IndicatorLine:
    values = compute(kind, closed_closes, period)            # aligned to closed series
    ts_window = list(closed_ts)
    val_window = list(values)
    if render_cap is not None and len(ts_window) > render_cap:
        ts_window = ts_window[-render_cap:]
        val_window = val_window[-render_cap:]
    pts = tuple((float(t), float(v)) for t, v in zip(ts_window, val_window, strict=False)
                if not math.isnan(v))
    return IndicatorLine(points=pts, period=period,
                         needs_more=bars_needed(kind, period, len(closed_closes)))


def build_render_snapshot(candles: Sequence[Candle],
                          quote: Optional[Quote],
                          render_cap: int = RENDER_CAP,
                          *,
                          symbol: Optional[str] = None,
                          error: Optional[str] = None,
                          settings: Optional[IndicatorSettings] = None,
                          now: Optional[float] = None,
                          poll_interval_s: float = POLL_INTERVAL_S) -> RenderSnapshot:
    closed = [c for c in candles if c.is_closed]
    closed_ts = [c.ts for c in closed]
    closed_closes = [c.close for c in closed]
    closed_count = len(closed)

    pts: list[tuple[float, float]] = list(zip(closed_ts, closed_closes, strict=False))
    if quote is not None:
        if pts and pts[-1][0] == quote.ts:
            pts[-1] = (quote.ts, quote.mark)
        else:
            pts.append((quote.ts, quote.mark))
    if render_cap is not None and len(pts) > render_cap:
        pts = pts[-render_cap:]

    sma_line = ema_line = rsi_line = None
    if settings is not None:
        if settings.sma_enabled:
            sma_line = _indicator_line(SMA, closed_closes, closed_ts,
                                       settings.sma_period, render_cap)
        if settings.ema_enabled:
            ema_line = _indicator_line(EMA, closed_closes, closed_ts,
                                       settings.ema_period, render_cap)
        if settings.rsi_enabled:
            rsi_line = _indicator_line(RSI, closed_closes, closed_ts,
                                       settings.rsi_period, render_cap)

    live = (quote is not None and not quote.stale
            and not is_stale(quote.ts, now=now, poll_interval_s=poll_interval_s))
    last_update_ts = quote.ts if quote is not None else None
    sym = symbol or (quote.symbol if quote is not None
                     else (candles[0].symbol if candles else ""))
    return RenderSnapshot(symbol=sym, points=tuple(pts), quote=quote, live=live,
                          last_update_ts=last_update_ts, error=error,
                          settings=settings, sma=sma_line, ema=ema_line,
                          rsi=rsi_line, closed_count=closed_count)
