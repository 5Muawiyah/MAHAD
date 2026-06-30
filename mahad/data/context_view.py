from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True, slots=True)
class YieldCurveTile:
    available: bool = False
    as_of: str = ""                       # provider data date
    fetched_ts: Optional[float] = None    # last OK fetch
    y3m: Optional[float] = None
    y2y: Optional[float] = None
    y10y: Optional[float] = None
    y30y: Optional[float] = None
    spread_bp: Optional[float] = None     # 10Y - 2Y
    reading: str = ""                     # inverted / flat / normal
    note: str = ""


@dataclass(frozen=True, slots=True)
class SentimentTile:
    available: bool = False
    as_of: str = ""
    fetched_ts: Optional[float] = None
    value: Optional[int] = None
    classification: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class VixTile:
    available: bool = False
    needs_key: bool = False
    as_of: str = ""
    fetched_ts: Optional[float] = None
    value: Optional[float] = None
    change: Optional[float] = None        # vs previous close
    band: str = ""                        # calm / normal / elevated / extreme
    note: str = ""


@dataclass(frozen=True, slots=True)
class UkRatesTile:
    available: bool = False
    as_of: str = ""
    fetched_ts: Optional[float] = None
    sonia: Optional[float] = None
    sonia_as_of: str = ""
    bank_rate: Optional[float] = None
    bank_rate_as_of: str = ""
    note: str = ""


@dataclass(frozen=True, slots=True)
class FxRateView:
    # USD->GBP ECB reference rate, for the display-only GBP view
    available: bool = False
    rate: Optional[float] = None
    as_of: str = ""
    fetched_ts: Optional[float] = None
    note: str = ""


@dataclass(frozen=True, slots=True)
class IntegrityRow:
    provider: str
    state: str                   # ok / retrying / needs a free key
    detail: str = ""             # last raw error
    since_ts: Optional[float] = None


@dataclass(frozen=True, slots=True)
class GapRow:
    symbol: str
    cached_days: int
    missing_days: int
    first: str = ""              # ISO range edges
    last: str = ""


@dataclass(frozen=True, slots=True)
class DataIntegrityView:
    providers: tuple[IntegrityRow, ...] = ()
    gaps: tuple[GapRow, ...] = ()
    checked_ts: Optional[float] = None


@dataclass(frozen=True, slots=True)
class MarketContextView:
    yields: YieldCurveTile = field(default_factory=YieldCurveTile)
    sentiment: SentimentTile = field(default_factory=SentimentTile)
    vix: VixTile = field(default_factory=VixTile)
    ukrates: UkRatesTile = field(default_factory=UkRatesTile)
    summary: str = ""


@dataclass(frozen=True, slots=True)
class HealthView:
    state: str = "ok"
    reason: str = ""
    detail: str = ""
    since_ts: Optional[float] = None
    # per-provider tooltip lines
    providers: tuple[tuple[str, str], ...] = ()


_OFFLINE_MARKERS = ("getaddrinfo", "name or service not known", "nodename",
                    "temporary failure in name resolution", "no route to host",
                    "network is unreachable", "connection refused",
                    "tunnel connection failed", "newconnectionerror",
                    "failed to establish a new connection", "max retries exceeded")


def classify_health(error_kind: Optional[str], message: str = "") -> str:
    if not error_kind:
        return "ok"
    if str(error_kind).lower() in ("needs_key", "invalid_key"):
        return "needs_key"                  # configuration, not an outage
    if str(error_kind).lower() == "network":
        low = (message or "").lower()
        if any(m in low for m in _OFFLINE_MARKERS):
            return "offline"
    return "retrying"
