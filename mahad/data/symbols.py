from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Sequence

from mahad.config import WATCHLIST_CAP

# crypto must quote in native USD
USD_PROXY_QUOTES = frozenset({"USD"})

# user-facing copy: hyphen, never a dash
USD_REJECT_MSG = "Base currency is USD - no FX in v1."
EMPTY_MSG = "Enter a symbol."

# Ticker grammar: letters / digits / . / - per part, one optional /QUOTE pair.
_TICKER_PART = r"[A-Z0-9.\-]{1,15}"
_TICKER_RE = re.compile(rf"^{_TICKER_PART}(?:/{_TICKER_PART})?$")
CHARSET_MSG = "Use letters, digits, . or - (and one / for a crypto pair)."


def normalize_symbol(text: Optional[str]) -> str:
    return (text or "").strip().upper()


def is_crypto(symbol: str) -> bool:
    # crypto is written BASE/QUOTE; bare tickers are stocks
    return "/" in symbol


def classify(symbol: str) -> tuple[str, str]:
    if is_crypto(symbol):
        return "crypto", symbol.split("/")[-1].strip()
    return "stock", "USD"


def is_usd_quoted(symbol: str) -> bool:
    asset_class, quote = classify(symbol)
    if asset_class == "crypto":
        return quote in USD_PROXY_QUOTES
    return True                                   # US equities are USD


def provider_for(asset_class: str, venue: str) -> str:
    return venue if asset_class == "crypto" else "finnhub"


@dataclass(frozen=True, slots=True)
class AddOutcome:
    status: str                 # "ok" | "duplicate" | "rejected"
    symbol: str = ""
    asset_class: str = ""
    quote_currency: str = ""
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


def validate_add(text: Optional[str], existing: Sequence[str],
                 cap: int = WATCHLIST_CAP) -> AddOutcome:
    # USD rule, then dedupe, then soft cap
    sym = normalize_symbol(text)
    if not sym:
        return AddOutcome("rejected", reason=EMPTY_MSG)
    if not _TICKER_RE.fullmatch(sym) or not any(ch.isalnum() for ch in sym):
        return AddOutcome("rejected", symbol=sym, reason=CHARSET_MSG)
    if not is_usd_quoted(sym):
        return AddOutcome("rejected", symbol=sym, reason=USD_REJECT_MSG)
    existing_norm = {normalize_symbol(s) for s in existing}
    if sym in existing_norm:
        return AddOutcome("duplicate", symbol=sym)        # ignored, not an error
    if len(existing_norm) >= cap:
        return AddOutcome("rejected", symbol=sym,
                          reason=f"Watchlist is full (max {cap}).")
    asset_class, quote = classify(sym)
    return AddOutcome("ok", symbol=sym, asset_class=asset_class, quote_currency=quote)


# --------------------------------------------------------------------------- #
# watchlist render carriers, worker -> UI
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class WatchlistRow:
    symbol: str
    asset_class: str
    mark: Optional[float] = None
    stale: bool = False
    has_quote: bool = False
    active: bool = False
    # stock row with no key configured
    needs_key: bool = False

    @property
    def dot(self) -> str:
        # UI token: 'live' | 'stale' | 'warm'
        if not self.has_quote:
            return "warm"
        return "stale" if self.stale else "live"


def effective_active(pending: Optional[str], state_active: Optional[str],
                     row_symbols: Sequence[str]) -> Optional[str]:
    if pending is not None and pending in row_symbols:
        return pending
    return state_active


def unread_after_delete(unread: int, fired: bool, on_alerts_tab: bool) -> int:
    if fired and not on_alerts_tab:
        return max(0, int(unread) - 1)
    return int(unread)


@dataclass(frozen=True, slots=True)
class WatchlistState:
    rows: tuple[WatchlistRow, ...] = ()
    active: Optional[str] = None

    @property
    def is_empty(self) -> bool:
        return len(self.rows) == 0


# --------------------------------------------------------------------------- #
# alert render carriers, worker -> UI
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class AlertRowView:
    id: int
    symbol: str
    condition_type: str
    direction: str
    summary: str
    armed: bool
    fired_at: Optional[float] = None
    not_active: bool = False

    @property
    def status(self) -> str:
        # pill token: 'armed' | 'fired'
        return "armed" if self.armed else "fired"


@dataclass(frozen=True, slots=True)
class AlertsView:
    rows: tuple[AlertRowView, ...] = ()
    paused: bool = False
    active_symbol: Optional[str] = None
    count: int = 0
    cap: int = 20            # one-shot alert cap

    @property
    def is_empty(self) -> bool:
        return len(self.rows) == 0
