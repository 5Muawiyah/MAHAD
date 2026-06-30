from __future__ import annotations

import csv
import datetime as _dt
import io
import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Mapping, Optional

from mahad.config import CONTEXT_TIMEOUT_S, FRED_KEY_ENV
from mahad.data.source import SourceError, SourceErrorKind

_UA = "MAHAD/2.0 (personal, non-commercial desktop app; simulated)"

TREASURY_CSV_URL = ("https://home.treasury.gov/resource-center/data-chart-center/"
                    "interest-rates/daily-treasury-rates.csv/{year}/all"
                    "?type=daily_treasury_yield_curve"
                    "&field_tdr_date_value={year}&_format=csv")
FNG_URL = "https://api.alternative.me/fng/?limit=2&format=json"   # trailing slash required
FRED_OBS_URL = ("https://api.stlouisfed.org/fred/series/observations"
                "?series_id=VIXCLS&api_key={key}&file_type=json"
                "&sort_order=desc&limit=10")
# Frankfurter latest USD -> GBP, ECB provider.
FRANKFURTER_URL = ("https://api.frankfurter.dev/v2/latest"
                   "?base=USD&symbols=GBP&providers=ECB")
# Bank of England IADB CSV: SONIA + Bank Rate.
BOE_IADB_URL = ("https://www.bankofengland.co.uk/boeapps/database/"
                "_iadb-fromshowcolumns.asp?csv.x=yes"
                "&SeriesCodes=IUDSOIA,IUDBEDR&UsingCodes=Y&CSVF=TN"
                "&Datefrom={datefrom}&Dateto=now")


@dataclass(frozen=True, slots=True)
class ContextResult:
    source: str
    data: Mapping[str, object] = field(default_factory=dict)
    error: Optional[SourceError] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.data)


def _http_get_text(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # nosec B310 - fixed https URLs
        text: str = resp.read().decode("utf-8", "replace")
        return text


def _error_for(exc: Exception, redact: str = "") -> SourceError:
    # redact masks an API key before it can reach a log line
    msg = str(exc) or exc.__class__.__name__
    if redact:
        msg = msg.replace(redact, "***")
    low = msg.lower()
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return SourceError(SourceErrorKind.INVALID_KEY, "HTTP 401 (key rejected)")
        return SourceError(SourceErrorKind.NETWORK, f"HTTP {exc.code}")
    if "timed out" in low or "timeout" in low:
        return SourceError(SourceErrorKind.TIMEOUT, msg)
    if isinstance(exc, (urllib.error.URLError, OSError)):
        return SourceError(SourceErrorKind.NETWORK, msg)
    return SourceError(SourceErrorKind.BAD_DATA, msg)


# --------------------------------------------------------------------------- #
# .env key loading
# --------------------------------------------------------------------------- #
def _parse_env_text(text: str) -> dict[str, str]:
    # KEY=VALUE lines; honours surrounding quotes and trailing inline comments
    out: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip()
        if val[:1] in ('"', "'"):
            quote = val[0]
            end = val.find(quote, 1)
            val = val[1:end] if end != -1 else val[1:]
        else:
            for i, ch in enumerate(val):
                if ch == "#" and (i == 0 or val[i - 1] in " \t"):
                    val = val[:i]
                    break
            val = val.strip()
        if key:
            out[key] = val
    return out


def read_env_key(name: str = FRED_KEY_ENV,
                 paths: Optional[tuple[Path, ...]] = None) -> Optional[str]:
    # lookup order: repo-root .env, then cwd .env, then the process environment
    if paths is None:
        repo_root = Path(__file__).resolve().parents[2]
        candidates = [repo_root / ".env", Path.cwd() / ".env"]
    else:
        candidates = [Path(p) for p in paths]
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            if path.is_file():
                val = _parse_env_text(path.read_text(encoding="utf-8")).get(name, "")
                if val:
                    return val
        except Exception:  # nosec B112 - unreadable .env degrades to next source
            continue
    val = os.environ.get(name, "").strip()
    return val or None


# --------------------------------------------------------------------------- #
# US Treasury daily par yield curve (keyless CSV)
# --------------------------------------------------------------------------- #
def _parse_treasury_csv(text: str) -> Optional[dict[str, object]]:
    reader = csv.reader(io.StringIO(text))
    rows = [r for r in reader if r and any(c.strip() for c in r)]
    if len(rows) < 2:
        return None
    header = [c.strip().lower() for c in rows[0]]

    def col(label: str) -> Optional[int]:
        lab = label.lower()
        for i, name in enumerate(header):
            if name == lab:
                return i
        return None

    c_date = col("date")
    cols = {"y3m": col("3 mo"), "y2y": col("2 yr"),
            "y10y": col("10 yr"), "y30y": col("30 yr")}
    if c_date is None or cols["y2y"] is None or cols["y10y"] is None:
        return None

    def num(row: list[str], idx: Optional[int]) -> Optional[float]:
        if idx is None or idx >= len(row):
            return None
        cell = row[idx].strip()
        if not cell or cell.upper() in {"N/A", "NA"}:
            return None
        try:
            return float(cell)
        except ValueError:
            return None

    best: Optional[tuple[_dt.date, dict[str, object]]] = None
    for row in rows[1:]:
        if c_date >= len(row):
            continue
        try:
            d = _dt.datetime.strptime(row[c_date].strip(), "%m/%d/%Y").date()
        except ValueError:
            continue
        vals = {k: num(row, idx) for k, idx in cols.items()}
        if vals["y2y"] is None or vals["y10y"] is None:
            continue
        if best is None or d > best[0]:
            best = (d, {"as_of": d.isoformat(), **vals})
    return best[1] if best else None


def fetch_treasury_yields(timeout: float = CONTEXT_TIMEOUT_S,
                          year: Optional[int] = None,
                          _get: Callable[[str, float], str] = _http_get_text
                          ) -> ContextResult:
    # fall back to last year early in January before this year's file fills
    source = "treasury"
    y = year or _dt.date.today().year
    last_error: Optional[SourceError] = None
    for candidate in (y, y - 1):
        try:
            text = _get(TREASURY_CSV_URL.format(year=candidate), timeout)
        except Exception as exc:
            last_error = _error_for(exc)
            continue
        try:
            data = _parse_treasury_csv(text)
        except Exception as exc:                      # defensive
            return ContextResult(source, error=_error_for(exc))
        if data:
            return ContextResult(source, data=data)
        last_error = SourceError(SourceErrorKind.EMPTY, f"no usable rows ({candidate})")
    return ContextResult(source, error=last_error
                         or SourceError(SourceErrorKind.EMPTY, "no data"))


# --------------------------------------------------------------------------- #
# Crypto Fear & Greed (keyless JSON)
# --------------------------------------------------------------------------- #
def fetch_fear_greed(timeout: float = CONTEXT_TIMEOUT_S,
                     _get: Callable[[str, float], str] = _http_get_text
                     ) -> ContextResult:
    source = "fng"
    try:
        payload = json.loads(_get(FNG_URL, timeout))
        rows = payload.get("data") or []
        first = rows[0] if rows else {}
        value = int(str(first.get("value")))
        classification = str(first.get("value_classification") or "").strip()
        ts = float(str(first.get("timestamp")))
        as_of = _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).date().isoformat()
        if not 0 <= value <= 100:
            raise ValueError(f"value out of range: {value}")
        return ContextResult(source, data={"value": value, "as_of": as_of,
                                           "classification": classification})
    except Exception as exc:
        return ContextResult(source, error=_error_for(exc))


# --------------------------------------------------------------------------- #
# VIX via the FRED API (free key; the caller holds the key decision)
# --------------------------------------------------------------------------- #
def fetch_vix(api_key: str, timeout: float = CONTEXT_TIMEOUT_S,
              _get: Callable[[str, float], str] = _http_get_text
              ) -> ContextResult:
    source = "vix"
    if not api_key:
        return ContextResult(source, error=SourceError(SourceErrorKind.UNKNOWN,
                                                       "no API key configured"))
    try:
        payload = json.loads(_get(FRED_OBS_URL.format(key=api_key), timeout))
        obs = payload.get("observations") or []
        values: list[tuple[str, float]] = []
        for o in obs:                                  # desc order; "." = missing
            raw = str(o.get("value", ".")).strip()
            if raw in {".", ""}:
                continue
            try:
                values.append((str(o.get("date") or ""), float(raw)))
            except ValueError:
                continue
            if len(values) >= 2:
                break
        if not values:
            return ContextResult(source, error=SourceError(SourceErrorKind.EMPTY,
                                                           "no usable observations"))
        as_of, latest = values[0]
        change = round(latest - values[1][1], 2) if len(values) > 1 else None
        return ContextResult(source, data={"value": latest, "as_of": as_of,
                                           "change": change})
    except Exception as exc:
        return ContextResult(source, error=_error_for(exc, redact=api_key))

# --------------------------------------------------------------------------- #
# The GBP reference rate (Frankfurter, keyless)
# --------------------------------------------------------------------------- #
def fetch_gbp_rate(timeout: float = CONTEXT_TIMEOUT_S,
                   _get: Callable[[str, float], str] = _http_get_text
                   ) -> ContextResult:
    # ECB USD->GBP reference rate, display only
    source = "fx"
    try:
        payload = json.loads(_get(FRANKFURTER_URL, timeout))
        rates = payload.get("rates") or {}
        raw = rates.get("GBP")
        if isinstance(raw, dict):                 # v2 provider-keyed shape
            raw = raw.get("ECB")                   # ECB only
        rate = float(raw)                          # type: ignore[arg-type]
        as_of = str(payload.get("date") or "").strip()
        if not (0.01 < rate < 100.0) or not as_of:
            raise ValueError(f"unusable rate payload ({raw!r}, {as_of!r})")
        return ContextResult(source, data={"rate": rate, "as_of": as_of})
    except Exception as exc:
        return ContextResult(source, error=_error_for(exc))


# --------------------------------------------------------------------------- #
# SONIA + Bank Rate (Bank of England IADB, keyless)
# --------------------------------------------------------------------------- #
def _parse_boe_date(text: str) -> Optional[_dt.date]:
    cell = (text or "").strip().strip('"')
    for fmt in ("%d %b %Y", "%d/%b/%Y", "%d %B %Y", "%d-%b-%Y",
                "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return _dt.datetime.strptime(cell, fmt).date()
        except ValueError:
            continue
    return None


def fetch_boe_rates(timeout: float = CONTEXT_TIMEOUT_S,
                    _get: Callable[[str, float], str] = _http_get_text
                    ) -> ContextResult:
    source = "boe"
    datefrom = (_dt.date.today() - _dt.timedelta(days=45)).strftime("%d/%b/%Y")
    try:
        text = _get(BOE_IADB_URL.format(datefrom=datefrom), timeout)
        reader = csv.reader(io.StringIO(text))
        rows = [r for r in reader if r and any(c.strip() for c in r)]
        if len(rows) < 2:
            return ContextResult(source, error=SourceError(
                SourceErrorKind.EMPTY, "no usable rows"))
        header = [c.strip().upper().strip('"') for c in rows[0]]

        def col(code: str) -> Optional[int]:
            for i, name in enumerate(header):
                if code in name:
                    return i
            return None

        c_date = 0
        c_sonia, c_bank = col("IUDSOIA"), col("IUDBEDR")
        if c_sonia is None and c_bank is None:
            return ContextResult(source, error=SourceError(
                SourceErrorKind.BAD_DATA, "series columns missing"))
        latest: dict[str, tuple[_dt.date, float]] = {}
        for row in rows[1:]:
            d = _parse_boe_date(row[c_date]) if c_date < len(row) else None
            if d is None:
                continue
            for key, idx in (("sonia", c_sonia), ("bank_rate", c_bank)):
                if idx is None or idx >= len(row):
                    continue
                cell = row[idx].strip().strip('"')
                if not cell or cell.upper() in {"N/A", "NA", ".."}:
                    continue
                try:
                    val = float(cell)
                except ValueError:
                    continue
                if key not in latest or d > latest[key][0]:
                    latest[key] = (d, val)
        if not latest:
            return ContextResult(source, error=SourceError(
                SourceErrorKind.EMPTY, "no usable observations"))
        data: dict[str, object] = {}
        for key, (d, val) in latest.items():
            data[key] = val
            data[f"{key}_as_of"] = d.isoformat()
        data["as_of"] = max(d for d, _ in latest.values()).isoformat()
        return ContextResult(source, data=data)
    except Exception as exc:
        return ContextResult(source, error=_error_for(exc))
