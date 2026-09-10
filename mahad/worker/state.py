# the state one PollWorker carries, declared once so each part of the package type-checks alone
from __future__ import annotations

import datetime as _dt
from collections import deque
from decimal import Decimal
from typing import TYPE_CHECKING, Callable, ClassVar, Optional

from PySide6.QtCore import QTimer, Signal

from mahad.data.context_view import (DataIntegrityView, FxRateView, HealthView,
                                     MarketContextView, SentimentTile, UkRatesTile,
                                     VixTile, YieldCurveTile)
from mahad.data.models import Candle, Quote
from mahad.data.portfolio_view import PortfolioView, RiskAnalyticsView, RiskView
from mahad.data.repository import MahadRepository, PersistedSymbol, PersistedTrade
from mahad.data.source import MarketDataSource
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.portfolio import PortfolioState
from mahad.engine.risk import ValueSample
from mahad.engine.signals import AlertEvent, AlertRule


if TYPE_CHECKING:
    # a QObject only for the type checker, so signal access in the parts resolves;
    # at runtime the parts stay plain classes and PollWorker alone derives from QObject
    from PySide6.QtCore import QObject as _StateBase
else:
    _StateBase = object


class WorkerState(_StateBase):
    # every attribute is assigned in PollWorker.__init__; every method below is defined by
    # PollWorker or one of its parts, so the bodies here never run
    snapshot_ready: ClassVar[Signal]
    watchlist_ready: ClassVar[Signal]
    indicator_settings_ready: ClassVar[Signal]
    add_rejected: ClassVar[Signal]
    remove_rejected: ClassVar[Signal]
    alert_events: ClassVar[Signal]
    alerts_ready: ClassVar[Signal]
    alert_rejected: ClassVar[Signal]
    order_result: ClassVar[Signal]
    settings_applied: ClassVar[Signal]
    db_notice: ClassVar[Signal]

    _symbol: Optional[str]
    _timeframe: str
    _poll_interval_s: float
    _render_cap: int
    _request_timeout_s: float
    _venue: str
    _db_url: Optional[str]
    _stop: bool
    _timer: Optional[QTimer]
    _source: Optional[MarketDataSource]
    _repo: Optional[MahadRepository]
    _candles: tuple[Candle, ...]
    _last_quote: Optional[Quote]
    _marks: dict[str, Quote]
    _persisted: list[PersistedSymbol]
    _settings: IndicatorSettings
    _alerts: list[AlertRule]
    _last_closed_ts: Optional[float]
    _alerts_paused: bool
    _portfolio: PortfolioState
    _starting_cash: Decimal
    _trades: list[PersistedTrade]
    _order_in_flight: bool
    _reset_in_flight: bool
    _held_cursor: int
    _risk_timeframe: str
    _value_history: deque[ValueSample]
    _peak_value: Optional[Decimal]
    _peak_ts: Optional[float]
    _adapters: dict[str, MarketDataSource]
    _history: dict[tuple[str, str], tuple[Candle, ...]]
    _fail_streak: int
    _backoff_until: float
    _monotonic: Callable[[], float]
    _jitter: Callable[[float, float], float]
    _wallclock: Callable[[], float]
    _heartbeat: Optional[QTimer]
    _next_sample_due: Optional[float]
    _db_degraded: bool
    _last_error: Optional[tuple[str, str, float]]
    _ctx_yields: YieldCurveTile
    _ctx_sentiment: SentimentTile
    _ctx_vix: VixTile
    _ctx_ukrates: UkRatesTile
    _ctx_fx: FxRateView
    _integrity: DataIntegrityView
    _ctx_due: dict[str, float]
    _ctx_has_key: bool
    _daily_series: dict[str, tuple[Candle, ...]]
    _provider_errors: dict[str, Optional[tuple[str, str, float]]]
    _daily_due: dict[str, float]
    _risk_dirty: bool
    _asset_returns: dict[str, list[tuple[_dt.date, float]]]
    _asset_closes: dict[str, list[tuple[_dt.date, float]]]
    _analytics: Optional[RiskAnalyticsView]
    _sectors: dict[str, str]

    def _build_context_view(self) -> MarketContextView:
        raise NotImplementedError

    def _build_health_view(self) -> HealthView:
        raise NotImplementedError

    def _build_integrity_view(self) -> DataIntegrityView:
        raise NotImplementedError

    def _build_portfolio_view(self) -> PortfolioView:
        raise NotImplementedError

    def _build_risk_view(self) -> RiskView:
        raise NotImplementedError

    def _chart_candles(self, symbol: str, timeframe: str,
                       fetched: tuple[Candle, ...]) -> tuple[Candle, ...]:
        raise NotImplementedError

    def _daily_coverage_symbols(self) -> list[str]:
        raise NotImplementedError

    def _emit_alerts(self) -> None:
        raise NotImplementedError

    def _emit_snapshot(self, error_reason: Optional[str] = None) -> None:
        raise NotImplementedError

    def _ensure_stock_history(self, symbol: Optional[str]) -> None:
        raise NotImplementedError

    def _evaluate_alerts(self) -> list[AlertEvent]:
        raise NotImplementedError

    def _fetch_sector_once(self, symbol: str) -> None:
        raise NotImplementedError

    def _get_setting(self, key: str) -> object:
        raise NotImplementedError

    def _get_source(self, symbol: str, held: bool = False) -> MarketDataSource:
        raise NotImplementedError

    def _integrity_now(self) -> DataIntegrityView:
        raise NotImplementedError

    def _load_alerts(self) -> None:
        raise NotImplementedError

    def _load_context_cache(self) -> None:
        raise NotImplementedError

    def _load_portfolio(self) -> None:
        raise NotImplementedError

    def _load_sectors(self) -> None:
        raise NotImplementedError

    def _load_value_history(self) -> None:
        raise NotImplementedError

    def _mark_decimal(self, symbol: str) -> tuple[Optional[Decimal], bool]:
        raise NotImplementedError

    def _note_provider(self, provider: str, error: Optional[object]) -> None:
        raise NotImplementedError

    def _provider_lines(self) -> tuple[tuple[str, str], ...]:
        raise NotImplementedError

    def _rebuild_risk_analytics(self) -> None:
        raise NotImplementedError

    def _refresh_analytics_view(self) -> None:
        raise NotImplementedError

    def _refresh_context_if_due(self, now: float) -> bool:
        raise NotImplementedError

    def _refresh_daily_if_due(self, now: float) -> None:
        raise NotImplementedError

    def _run_data_migration(self) -> None:
        raise NotImplementedError

    def _sample_value_history(self) -> None:
        raise NotImplementedError

    def _set_setting(self, key: str, value: object) -> None:
        raise NotImplementedError

    def _value_now(self) -> tuple[Decimal, Decimal, Decimal, bool]:
        raise NotImplementedError
