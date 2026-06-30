# Tiingo history: daily EOD plus IEX intraday backfill
from __future__ import annotations

import datetime as _dt
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from mahad import config
from mahad.data.context_sources import read_env_key
from mahad.data.models import Candle
from mahad.data.source import (SourceError, SourceErrorKind, dedupe_sort_candles,
                               is_valid_price)

_UA = "MAHAD/2.0 (personal, non-commercial desktop app; simulated)"
TIINGO_DAILY_URL = ("https://api.tiingo.com/tiingo/daily/{symbol}/prices"
                    "?startDate={start}&format=json")
TIINGO_IEX_URL = ("https://api.tiingo.com/iex/{symbol}/prices"
                  "?startDate={start}&resampleFreq={freq}&format=json")

_IEX_FREQ = {"1m": "1min", "1h": "1hour"}
_IEX_LOOKBACK_DAYS = {"1m": 5, "1h": 60}


@dataclass(frozen=True, slots=True)
class DailyBarRow:
    ts: float                  # epoch seconds, UTC midnight
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


@dataclass(frozen=True, slots=True)
class DailyHistoryResult:
    symbol: str
    bars: tuple[DailyBarRow, ...] = ()
    error: Optional[SourceError] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.bars)


def _parse_tiingo_date(raw: object) -> Optional[float]:
    text = str(raw or "").strip().rstrip("Z").split(".")[0]
    if not text:
        return None
    try:
        dt = _dt.datetime.fromisoformat(text).replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None
    return dt.timestamp()


def _error_for(exc: Exception, redact: str = "") -> SourceError:
    msg = str(exc) or exc.__class__.__name__
    if redact:
        msg = msg.replace(redact, "***")
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:  # key present but rejected
            return SourceError(SourceErrorKind.INVALID_KEY, config.INVALID_KEY_HISTORY_MSG)
        return SourceError(SourceErrorKind.NETWORK, f"HTTP {exc.code}")
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return SourceError(SourceErrorKind.TIMEOUT, msg)
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return SourceError(SourceErrorKind.NETWORK, msg)
    return SourceError(SourceErrorKind.BAD_DATA, msg)


class TiingoSource:
    source_name = "tiingo"

    def __init__(self, request_timeout_s: float = config.REQUEST_TIMEOUT_S,
                 key: Optional[str] = None,
                 history_cap: int = config.HISTORY_CAP) -> None:
        self._timeout = request_timeout_s
        self._key = key if key is not None else (
            read_env_key(config.TIINGO_KEY_ENV) or "")
        self._history_cap = history_cap

    @property
    def needs_key(self) -> bool:
        return not self._key

    def _get_json(self, url: str) -> object:
        req = urllib.request.Request(url, headers={
            "User-Agent": _UA, "Authorization": f"Token {self._key}"})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310 - fixed https URLs
            return json.loads(resp.read().decode("utf-8", "replace"))

    def fetch_daily(self, symbol: str,
                    start_date: Optional[str] = None) -> DailyHistoryResult:
        if not self._key:
            return DailyHistoryResult(symbol, error=SourceError(
                SourceErrorKind.NEEDS_KEY, config.NEEDS_KEY_HISTORY_MSG))
        if start_date is None:
            start = (_dt.date.today()
                     - _dt.timedelta(days=config.TIINGO_DAILY_LOOKBACK_DAYS))
            start_date = start.isoformat()
        try:
            payload = self._get_json(TIINGO_DAILY_URL.format(symbol=symbol,
                                                             start=start_date))
        except Exception as exc:
            return DailyHistoryResult(symbol, error=_error_for(exc, self._key))
        if not isinstance(payload, list):
            return DailyHistoryResult(symbol, error=SourceError(
                SourceErrorKind.BAD_DATA, "unexpected payload shape"))
        bars: list[DailyBarRow] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            ts = _parse_tiingo_date(row.get("date"))
            o, h = row.get("open"), row.get("high")
            low, c = row.get("low"), row.get("close")
            adj = row.get("adjClose")
            if ts is None or not all(is_valid_price(x) for x in (o, h, low, c, adj)):
                continue
            try:
                vol = float(row.get("volume") or 0.0)
                div = float(row.get("divCash") or 0.0)
                split = float(row.get("splitFactor") or 1.0)
            except (TypeError, ValueError):
                vol, div, split = 0.0, 0.0, 1.0
            bars.append(DailyBarRow(ts=ts, open=float(str(o)), high=float(str(h)),
                                    low=float(str(low)), close=float(str(c)),
                                    adj_close=float(str(adj)), volume=vol,
                                    div_cash=div, split_factor=split))
        if not bars:
            return DailyHistoryResult(symbol, error=SourceError(
                SourceErrorKind.EMPTY, "no usable daily rows"))
        bars.sort(key=lambda b: b.ts)
        if len(bars) > self._history_cap:
            bars = bars[-self._history_cap:]
        return DailyHistoryResult(symbol, bars=tuple(bars))

    def fetch_intraday(self, symbol: str, timeframe: str
                       ) -> tuple[tuple[Candle, ...], Optional[SourceError]]:
        if not self._key:
            return (), SourceError(SourceErrorKind.NEEDS_KEY,
                                   config.NEEDS_KEY_HISTORY_MSG)
        freq = _IEX_FREQ.get(timeframe)
        if freq is None:
            return (), SourceError(SourceErrorKind.BAD_DATA,
                                   f"no IEX mapping for {timeframe}")
        start = (_dt.date.today()
                 - _dt.timedelta(days=_IEX_LOOKBACK_DAYS[timeframe])).isoformat()
        try:
            payload = self._get_json(TIINGO_IEX_URL.format(
                symbol=symbol, start=start, freq=freq))
        except Exception as exc:
            return (), _error_for(exc, self._key)
        if not isinstance(payload, list):
            return (), SourceError(SourceErrorKind.BAD_DATA,
                                   "unexpected payload shape")
        built: list[Candle] = []
        for row in payload:
            if not isinstance(row, dict):
                continue
            ts = _parse_tiingo_date(row.get("date"))
            o, h = row.get("open"), row.get("high")
            low, c = row.get("low"), row.get("close")
            if ts is None or not all(is_valid_price(x) for x in (o, h, low, c)):
                continue
            try:
                vol = float(row.get("volume") or 0.0)
            except (TypeError, ValueError):
                vol = 0.0
            built.append(Candle(symbol=symbol, timeframe=timeframe, ts=ts,
                                open=float(str(o)), high=float(str(h)),
                                low=float(str(low)), close=float(str(c)),
                                volume=vol, is_closed=True))
        if not built:
            return (), SourceError(SourceErrorKind.EMPTY, "no usable intraday rows")
        return dedupe_sort_candles(built, self._history_cap), None
