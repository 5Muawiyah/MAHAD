from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Mapping, Optional, Sequence

from mahad.config import HISTORY_CAP, REQUEST_TIMEOUT_S
from mahad.data.models import Candle, Quote
from mahad.data.source import (FetchResult, SourceError, SourceErrorKind,
                               is_valid_price, normalize_ohlcv)

_UA = "MAHAD/2.0 (personal, non-commercial desktop app; simulated)"

# keyless public market data is all this adapter ever touches
KRAKEN_TICKER_URL = "https://api.kraken.com/0/public/Ticker?pair={pairs}"
KRAKEN_OHLC_URL = "https://api.kraken.com/0/public/OHLC?pair={pair}&interval={interval}"

_TF_INTERVAL = {"1m": 1, "1h": 60, "1d": 1440, "1w": 10080}  # 3d/1mo resample from 1d

# Kraken's old tickers for these two
_ALIASES = {"XBT": "BTC", "XDG": "DOGE"}
_REVERSE = {"BTC": "XBT", "DOGE": "XDG"}


def app_to_kraken_pair(symbol: str) -> str:
    base, _, quote = symbol.partition("/")
    return f"{_REVERSE.get(base.upper(), base.upper())}{quote.upper()}"


def _norm_asset(code: str) -> str:
    # strip Kraken's legacy X/Z class prefix, then de-alias
    code = code.upper()
    if len(code) == 4 and code[0] in ("X", "Z"):
        code = code[1:]
    return _ALIASES.get(code, code)


def kraken_key_to_app(key: str, requested: Mapping[str, str]) -> Optional[str]:
    # result keys glue base+quote with no delimiter, so try every split point
    k = key.upper()
    for i in range(2, len(k) - 1):
        cand = f"{_norm_asset(k[:i])}/{_norm_asset(k[i:])}"
        if cand in requested:
            return requested[cand]
    return None


def _requested_map(symbols: Sequence[str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sym in symbols:
        base, _, quote = sym.partition("/")
        out[f"{_ALIASES.get(base.upper(), base.upper())}/{quote.upper()}"] = sym
    return out


def mark_from_kraken_ticker(entry: Optional[Mapping[str, object]]) -> Optional[float]:
    # mark is c[0] (last trade), else bid/ask mid
    if not entry:
        return None
    last_arr = entry.get("c")
    if isinstance(last_arr, (list, tuple)) and last_arr and is_valid_price(last_arr[0]):
        return float(str(last_arr[0]))
    bid_arr, ask_arr = entry.get("b"), entry.get("a")
    bid = bid_arr[0] if isinstance(bid_arr, (list, tuple)) and bid_arr else None
    ask = ask_arr[0] if isinstance(ask_arr, (list, tuple)) and ask_arr else None
    if is_valid_price(bid) and is_valid_price(ask):
        return (float(str(bid)) + float(str(ask))) / 2.0
    return None


def _error_for(exc: Exception) -> SourceError:
    if isinstance(exc, urllib.error.HTTPError):
        return SourceError(SourceErrorKind.NETWORK, f"HTTP {exc.code}")
    msg = str(exc) or exc.__class__.__name__
    if "timed out" in msg.lower() or "timeout" in msg.lower():
        return SourceError(SourceErrorKind.TIMEOUT, msg)
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return SourceError(SourceErrorKind.NETWORK, msg)
    return SourceError(SourceErrorKind.BAD_DATA, msg)


def _payload_error(errors: object) -> Optional[SourceError]:
    # Kraken reports failures in the body's error list, not the HTTP status
    if not errors:
        return None
    text = "; ".join(str(e) for e in errors) if isinstance(errors, list) else str(errors)
    if "unknown asset pair" in text.lower():
        return SourceError(SourceErrorKind.EMPTY, text)
    return SourceError(SourceErrorKind.NETWORK, text)


class KrakenSource:
    source_name = "kraken"

    def __init__(self, request_timeout_s: float = REQUEST_TIMEOUT_S,
                 history_cap: int = HISTORY_CAP) -> None:
        self._timeout = request_timeout_s
        self._history_cap = history_cap

    # -- transport (read-only GET) ------ #
    def _get_json(self, url: str) -> dict[str, object]:
        req = urllib.request.Request(url, headers={"User-Agent": _UA})
        with urllib.request.urlopen(req, timeout=self._timeout) as resp:  # nosec B310 - fixed https URLs
            data = json.loads(resp.read().decode("utf-8", "replace"))
        return data if isinstance(data, dict) else {}

    # -- marks ---------------------------------------------------------------- #
    def fetch_mark_batch(self, symbols: Sequence[str]) -> dict[str, FetchResult]:
        # one Ticker call covers every pair
        syms = [s for s in dict.fromkeys(symbols) if s]
        if not syms:
            return {}
        pairs = ",".join(app_to_kraken_pair(s) for s in syms)
        try:
            payload = self._get_json(KRAKEN_TICKER_URL.format(pairs=pairs))
        except Exception as exc:
            err = _error_for(exc)
            return {s: FetchResult(s, "1d", error=err) for s in syms}
        perr = _payload_error(payload.get("error"))
        if perr is not None:
            return {s: FetchResult(s, "1d", error=perr) for s in syms}
        requested = _requested_map(syms)
        now = time.time()
        out: dict[str, FetchResult] = {}
        result = payload.get("result")
        if isinstance(result, dict):
            for key, entry in result.items():
                sym = kraken_key_to_app(str(key), requested)
                if sym is None:
                    continue
                mark = mark_from_kraken_ticker(entry if isinstance(entry, dict) else None)
                if mark is None:
                    out[sym] = FetchResult(sym, "1d", error=SourceError(
                        SourceErrorKind.EMPTY, "no usable mark"))
                else:
                    out[sym] = FetchResult(sym, "1d", quote=Quote(
                        symbol=sym, mark=mark, ts=now, source=self.source_name))
        for s in syms:
            out.setdefault(s, FetchResult(s, "1d", error=SourceError(
                SourceErrorKind.EMPTY, "pair missing from response")))
        return out

    def fetch_mark(self, symbol: str) -> FetchResult:
        return self.fetch_mark_batch([symbol]).get(
            symbol, FetchResult(symbol, "1d", error=SourceError(
                SourceErrorKind.UNKNOWN, "no result")))

    # -- candles -------------------------------------------------------------- #
    def fetch_ohlc(self, symbol: str, timeframe: str
                   ) -> tuple[tuple[Candle, ...], Optional[SourceError]]:
        # last row is the still-forming bar
        interval = _TF_INTERVAL.get(timeframe, 1440)
        pair = app_to_kraken_pair(symbol)
        try:
            payload = self._get_json(KRAKEN_OHLC_URL.format(pair=pair,
                                                            interval=interval))
        except Exception as exc:
            return (), _error_for(exc)
        err = _payload_error(payload.get("error"))
        if err is not None:
            return (), err
        result = payload.get("result")
        rows_raw: Optional[list[object]] = None
        if isinstance(result, dict):
            requested = _requested_map([symbol])
            for key, value in result.items():
                if key == "last":
                    continue
                if kraken_key_to_app(str(key), requested) == symbol and isinstance(value, list):
                    rows_raw = value
                    break
        if not rows_raw:
            return (), SourceError(SourceErrorKind.EMPTY, "no OHLC rows")
        rows = []
        for bar in rows_raw:
            if not isinstance(bar, (list, tuple)) or len(bar) < 7:
                continue
            try:
                # Kraken row: [time, open, high, low, close, vwap, volume, count]
                rows.append((float(str(bar[0])), bar[1], bar[2], bar[3], bar[4], bar[6]))
            except (TypeError, ValueError):
                continue
        candles = normalize_ohlcv(symbol, timeframe, rows, self._history_cap,
                                  last_is_forming=True)
        if not candles:
            return (), SourceError(SourceErrorKind.EMPTY, "no usable OHLC rows")
        return candles, None

    # -- protocol conformance -------------------------------------------------- #
    def fetch(self, symbol: str, timeframe: str) -> FetchResult:
        candles, cerr = self.fetch_ohlc(symbol, timeframe)
        mark_res = self.fetch_mark(symbol)
        if mark_res.ok and mark_res.quote is not None:
            return FetchResult(symbol, timeframe, quote=mark_res.quote,
                               candles=candles)
        if candles and is_valid_price(candles[-1].close):
            # fall back to last close when the venue gave bars but no mark
            quote = Quote(symbol=symbol, mark=float(candles[-1].close),
                          ts=time.time(), source=self.source_name)
            return FetchResult(symbol, timeframe, quote=quote, candles=candles)
        return FetchResult(symbol, timeframe, candles=candles,
                           error=(mark_res.error or cerr
                                  or SourceError(SourceErrorKind.EMPTY,
                                                 "no usable mark")))
