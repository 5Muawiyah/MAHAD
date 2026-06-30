from __future__ import annotations

import time
from typing import cast
from pathlib import Path

# --- Polling / symbol / timeframe ---
POLL_INTERVAL_S: float = 5.0
DEFAULT_SYMBOL: str = "AAPL"
DEFAULT_TIMEFRAME: str = "1d"
VALID_CHART_TIMEFRAMES: tuple[str, ...] = ("1m", "1h", "1d", "3d", "1w", "1mo")  # chart display only
DEFAULT_WATCHLIST: tuple[str, ...] = ("AAPL", "BTC/USD")
WATCHLIST_CAP: int = 20                             # soft cap

# --- Indicator default periods (mirrored by IndicatorSettings) ---
SMA_PERIOD: int = 20
EMA_PERIOD: int = 12
RSI_PERIOD: int = 14

# --- Bounded caps ---
HISTORY_CAP: int = 500                              # bars retained in memory per symbol
RENDER_CAP: int = 300                               # bars in the rendered window / snapshot

# --- Networking ---
REQUEST_TIMEOUT_S: float = 10.0
BACKOFF_CAP_S: float = 60.0

# --- Crypto venue (Kraken is the FCA-registered default; swappable) ---
DEFAULT_CRYPTO_VENUE: str = "kraken"

# --- Persistence: local SQLite via SQLAlchemy, gitignored ---
DB_FILENAME: str = "mahad.db"
SQLITE_BUSY_TIMEOUT_MS: int = 5000                  # PRAGMA busy_timeout

# --- Staleness: stale when age > max(3 * poll_interval, 15s) ---
STALENESS_FLOOR_S: float = 15.0


def data_dir() -> Path:
    return Path.home() / ".mahad"


def default_db_url() -> str:
    d = data_dir()
    d.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{(d / DB_FILENAME).as_posix()}"


def staleness_window(poll_interval_s: float = POLL_INTERVAL_S) -> float:
    return max(3.0 * poll_interval_s, STALENESS_FLOOR_S)


def is_stale(ts: float | None, now: float | None = None,
             poll_interval_s: float = POLL_INTERVAL_S) -> bool:
    if ts is None:
        return True
    current = time.time() if now is None else now
    return (current - ts) > staleness_window(poll_interval_s)


# --- Simulated trading ---
STARTING_CASH: str = "100000"          # virtual USD starting cash

# --- Held-position polling ---
HELD_REQUEST_TIMEOUT_S: float = 3.0    # tighter timeout for held marks
HELD_POLL_BUDGET: int = 3              # held symbols refreshed per cycle


def default_order_qty(symbol: str | None) -> str:
    # a slash marks a crypto pair: smaller default lot than a stock share
    return "0.01" if "/" in (symbol or "") else "1"


# --- Risk panel ---
RISK_TIMEFRAME: str = "1d"                 # value-history sampling cadence (1m/1h/1d)
VOLATILITY_WINDOW: int = 30
VALUE_HISTORY_CAP: int = 1000
VALID_RISK_TIMEFRAMES: tuple[str, ...] = ("1m", "1h", "1d")

# Wall-clock seconds per risk_timeframe (the QTimer interval).
RISK_TIMEFRAME_SECONDS: dict[str, int] = {"1m": 60, "1h": 3600, "1d": 86400}


def risk_timeframe_seconds(tf: str) -> int:
    return RISK_TIMEFRAME_SECONDS.get(tf, RISK_TIMEFRAME_SECONDS["1d"])


def valid_risk_timeframe(tf: object) -> str:
    return cast(str, tf) if tf in VALID_RISK_TIMEFRAMES else RISK_TIMEFRAME


# --- Worker heartbeat + market-context refresh ---
HEARTBEAT_INTERVAL_S: float = 5.0          # drives the wall-clock due grids
CONTEXT_TIMEOUT_S: float = 4.0
CONTEXT_REFRESH_S: float = 12 * 3600.0     # per-source refresh cadence
CONTEXT_RETRY_S: float = 30 * 60.0         # earliest retry after a failure
FRED_KEY_ENV: str = "FRED_API_KEY"         # free key - the VIX tile

# --- Data plane ---
FINNHUB_KEY_ENV: str = "FINNHUB_API_KEY"   # free key - live US stock quotes
TIINGO_KEY_ENV: str = "TIINGO_API_KEY"     # free key - stock daily history
FINNHUB_BUDGET_PER_MIN: int = 55           # worker-side cap under the free tier
TIINGO_DAILY_LOOKBACK_DAYS: int = 750      # calendar days fetched
NEEDS_KEY_STOCK_MSG: str = ("needs a free Finnhub key (finnhub.io) - see the "
                            "README to add it; crypto runs without a key")
NEEDS_KEY_HISTORY_MSG: str = ("needs history - add the free Tiingo key "
                              "(tiingo.com); see the README")
INVALID_KEY_STOCK_MSG: str = ("Finnhub key rejected (HTTP 401) - check the key "
                              "in .env (see .env.example); see the README")
INVALID_KEY_HISTORY_MSG: str = ("Tiingo key rejected (HTTP 401) - check the key "
                                "in .env (see .env.example); see the README")
INVALID_KEY_VIX_MSG: str = ("FRED key rejected (HTTP 401) - check the key in "
                            ".env (see .env.example); see the README")
BENCHMARK_SYMBOL: str = "SPY"  # beta benchmark
DAILY_REFRESH_S: float = 24 * 3600.0       # nightly daily-bar refresh cadence
DAILY_RETRY_S: float = 30 * 60.0           # earliest retry after a failure
DAILY_STAGGER_S: float = 10.0              # first uncovered-symbol fetch after start

# --- Risk-analytics suite ---
RISK_WINDOW: int = 250                     # the Basel one-year observation period
CORRELATION_WINDOW: int = 90
BACKTEST_CONFIDENCE: float = 0.99          # the Basel backtest confidence
ES_CONFIDENCE: float = 0.975               # the FRTB measure
COMPONENT_VAR_CONFIDENCE: float = 0.95  # component VaR (parametric Euler)
VAR_TREND_WINDOW: int = 60  # rolling-VaR history window (days)
VAR_TREND_POINTS: int = 40

# Dated stress scenarios - names + ISO windows shown on the card.
STRESS_SCENARIOS: tuple[tuple[str, str, str], ...] = (
    ("COVID crash", "2020-02-19", "2020-03-23"),
    ("2022 tightening", "2022-01-03", "2022-12-30"),
    ("FTX week", "2022-11-04", "2022-11-14"),
)

# Per-asset window-return constants used when the cache misses a window.
STRESS_CONSTANTS: dict[tuple[str, str], float] = {
    ("COVID crash", "SPY"): -0.34,
    ("COVID crash", "AAPL"): -0.31,
    ("COVID crash", "MSFT"): -0.27,
    ("COVID crash", "BTC/USD"): -0.32,
    ("COVID crash", "ETH/USD"): -0.52,
    ("2022 tightening", "SPY"): -0.20,
    ("2022 tightening", "AAPL"): -0.29,
    ("2022 tightening", "MSFT"): -0.28,
    ("2022 tightening", "BTC/USD"): -0.64,
    ("2022 tightening", "ETH/USD"): -0.68,
    ("FTX week", "SPY"): 0.05,
    ("FTX week", "AAPL"): 0.07,
    ("FTX week", "MSFT"): 0.09,
    ("FTX week", "BTC/USD"): -0.22,
    ("FTX week", "ETH/USD"): -0.24,
}

# Local sector fallback; seeds the defaults.
DEFAULT_SECTOR_MAP: dict[str, str] = {
    "AAPL": "Technology",
    "MSFT": "Technology",
    "NVDA": "Technology",
    "SPY": "Index",
}
