from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from typing import Optional, Sequence, SupportsFloat, cast

import numpy as np
import numpy.typing as npt

from mahad.engine.indicators import (EMA, RSI, SMA, Closes, bars_needed,
                                     clamp_period, ema, sma, wilder_rsi)

PRICE_SMA_CROSS = "price_sma_cross"
SMA_EMA_CROSS = "sma_ema_cross"
RSI_THRESHOLD = "rsi_threshold"
PRICE_THRESHOLD = "price_threshold"

CROSSOVER_TYPES = frozenset({PRICE_SMA_CROSS, SMA_EMA_CROSS})
THRESHOLD_TYPES = frozenset({RSI_THRESHOLD, PRICE_THRESHOLD})
CONDITION_TYPES = CROSSOVER_TYPES | THRESHOLD_TYPES

UP = "up"
DOWN = "down"

# bar spacing in seconds, used by the intraday adjacency guard
_TF_SECONDS = {"1m": 60.0, "1h": 3600.0, "1d": 86400.0,
               "3d": 259200.0, "1w": 604800.0, "1mo": 2629800.0}
INTRADAY_GAP_FACTOR = 1.5          # a missing intraday bar fails adjacency
_LEVEL_DP = 6


def timeframe_seconds(timeframe: str) -> float:
    return _TF_SECONDS.get(timeframe, 60.0)


@dataclass(frozen=True, slots=True)
class AlertSpec:
    symbol: str
    condition_type: str
    params: dict[str, object]
    direction: str
    id: Optional[int] = None
    armed: bool = True
    fired_at: Optional[float] = None


@dataclass(frozen=True, slots=True)
class AlertEvent:
    symbol: str
    condition_type: str
    direction: str
    params: dict[str, object]
    value: float
    fired_at: float
    message: str
    alert_id: Optional[int] = None


def _coerce_level(value: object) -> tuple[bool, float]:
    try:
        f = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False, 0.0
    if not math.isfinite(f):
        return False, 0.0
    return True, float(round(f, _LEVEL_DP))


def validate_params(
        condition_type: str, raw: Optional[dict[str, object]],
) -> tuple[bool, Optional[dict[str, object]], str]:
    if condition_type not in CONDITION_TYPES:
        return False, None, f"unknown condition: {condition_type}"
    raw = raw or {}
    if condition_type == PRICE_SMA_CROSS:
        return True, {"sma_period": clamp_period(raw.get("sma_period"))}, ""
    if condition_type == SMA_EMA_CROSS:
        return True, {"ema_period": clamp_period(raw.get("ema_period")),
                      "sma_period": clamp_period(raw.get("sma_period"))}, ""
    if condition_type == RSI_THRESHOLD:
        ok, level = _coerce_level(raw.get("level"))
        if not ok:
            return False, None, "RSI level must be a number"
        if not 0.0 <= level <= 100.0:
            return False, None, "RSI level must be in 0 - 100"
        return True, {"level": level, "rsi_period": clamp_period(raw.get("rsi_period"))}, ""
    # PRICE_THRESHOLD
    ok, level = _coerce_level(raw.get("level"))
    if not ok or level <= 0.0:
        return False, None, "price level must be a positive number"
    return True, {"level": level}, ""


def canonical_params(params: dict[str, object]) -> str:
    # sorted keys so the duplicate check and persisted form stay stable
    return json.dumps(params, sort_keys=True, separators=(",", ":"))


def bars_needed_for(condition_type: str, params: dict[str, object],
                    n_closed: int) -> int:
    if condition_type == PRICE_THRESHOLD:
        return 0
    if condition_type == PRICE_SMA_CROSS:
        return bars_needed(SMA, cast(int, params["sma_period"]), n_closed)
    if condition_type == RSI_THRESHOLD:
        return bars_needed(RSI, cast(int, params["rsi_period"]), n_closed)
    if condition_type == SMA_EMA_CROSS:
        return max(bars_needed(SMA, cast(int, params["sma_period"]), n_closed),
                   bars_needed(EMA, cast(int, params["ema_period"]), n_closed))
    return 0


def crossover_d(spec: AlertSpec, closed_closes: Closes) -> npt.NDArray[np.float64]:
    # fast minus slow, aligned to the closed series with a NaN warm-up
    closes = np.asarray(closed_closes, dtype=float)
    if spec.condition_type == PRICE_SMA_CROSS:
        return closes - sma(closes, cast(int, spec.params["sma_period"]))
    if spec.condition_type == SMA_EMA_CROSS:
        return (sma(closes, cast(int, spec.params["sma_period"]))
                - ema(closes, cast(int, spec.params["ema_period"])))
    raise ValueError(f"not a crossover condition: {spec.condition_type!r}")


def cross_fired(d_prev: Optional[SupportsFloat],
                d_curr: Optional[SupportsFloat], direction: str) -> bool:
    # strict sign change; any NaN counts as no cross
    if d_prev is None or d_curr is None:
        return False
    dp = float(d_prev)
    dc = float(d_curr)
    if math.isnan(dp) or math.isnan(dc):
        return False
    if direction == UP:
        return dp <= 0.0 and dc > 0.0
    if direction == DOWN:
        return dp >= 0.0 and dc < 0.0
    return False


def bars_adjacent(ts_prev: float, ts_curr: float, timeframe: str) -> bool:
    # reject a cross that straddles a data gap rather than two real bars
    dt = float(ts_curr) - float(ts_prev)
    if dt <= 0.0:
        return False
    if timeframe == "1d":
        return True
    return dt <= INTRADAY_GAP_FACTOR * timeframe_seconds(timeframe)


def threshold_value(spec: AlertSpec, closed_closes: Closes,
                    mark: Optional[float]) -> Optional[float]:
    # RSI reads off closed bars; price uses the live mark
    if spec.condition_type == PRICE_THRESHOLD:
        return float(mark) if mark is not None else None
    if spec.condition_type == RSI_THRESHOLD:
        vals = wilder_rsi(closed_closes, cast(int, spec.params["rsi_period"]))
        for v in reversed(np.asarray(vals, dtype=float)):
            if not math.isnan(v):
                return float(v)
        return None
    raise ValueError(f"not a threshold condition: {spec.condition_type!r}")


def threshold_fired(value: Optional[float], level: SupportsFloat,
                    direction: str) -> bool:
    # up fires at value >= level, down at value <= level
    if value is None:
        return False
    if direction == UP:
        return float(value) >= float(level)
    if direction == DOWN:
        return float(value) <= float(level)
    return False


def _fmt(x: float) -> str:
    return f"{float(x):g}"


def summary(spec: AlertSpec) -> str:
    # plain wording, never phrased as advice
    p, d = spec.params, spec.direction
    if spec.condition_type == PRICE_THRESHOLD:
        return f"price {'>=' if d == UP else '<='} {_fmt(cast(float, p['level']))}"
    if spec.condition_type == RSI_THRESHOLD:
        return (f"RSI({cast(int, p['rsi_period'])}) "
                f"{'>=' if d == UP else '<='} {_fmt(cast(float, p['level']))}")
    arrow = "crosses above" if d == UP else "crosses below"
    if spec.condition_type == PRICE_SMA_CROSS:
        return f"price {arrow} SMA({cast(int, p['sma_period'])})"
    if spec.condition_type == SMA_EMA_CROSS:
        return (f"SMA({cast(int, p['sma_period'])}) {arrow} "
                f"EMA({cast(int, p['ema_period'])})")
    return spec.condition_type


def _event(spec: AlertSpec, value: float, now: float) -> AlertEvent:
    return AlertEvent(symbol=spec.symbol, condition_type=spec.condition_type,
                      direction=spec.direction, params=dict(spec.params),
                      value=float(value), fired_at=float(now),
                      message=f"{spec.symbol} · {summary(spec)} - fired",
                      alert_id=spec.id)


def evaluate_threshold(spec: AlertSpec, closed_closes: Closes,
                       mark: Optional[float], now: float) -> Optional[AlertEvent]:
    value = threshold_value(spec, closed_closes, mark)
    if value is None:
        return None
    if threshold_fired(value, cast(float, spec.params["level"]), spec.direction):
        return _event(spec, value, now)
    return None


def cross_at(spec: AlertSpec, d: Closes, ts: Sequence[float], j: int,
             timeframe: str, now: float) -> Optional[AlertEvent]:
    if j < 1 or j >= len(d):
        return None
    if not bars_adjacent(ts[j - 1], ts[j], timeframe):
        return None
    if cross_fired(d[j - 1], d[j], spec.direction):
        return _event(spec, float(d[j]), now)
    return None


def scan_crossover(spec: AlertSpec, d: Closes, ts: Sequence[float],
                   new_indices: Sequence[int], timeframe: str,
                   now: float) -> Optional[AlertEvent]:
    # one-shot: first cross among the newly-closed bars wins
    for j in sorted(new_indices):
        ev = cross_at(spec, d, ts, j, timeframe, now)
        if ev is not None:
            return ev
    return None


def evaluate_crossover(spec: AlertSpec, closed_closes: Closes,
                       closed_ts: Sequence[float], timeframe: str,
                       now: float = 0.0) -> Optional[AlertEvent]:
    # convenience path: just the last closed pair, handy for tests
    n = len(closed_closes)
    if n < 2:
        return None
    d = crossover_d(spec, closed_closes)
    return cross_at(spec, d, list(closed_ts), n - 1, timeframe, now)


def evaluate_alert(spec: AlertSpec, *, closed_closes: Closes,
                   closed_ts: Sequence[float], mark: Optional[float], timeframe: str,
                   new_indices: Sequence[int], now: float,
                   ) -> tuple[Optional[AlertEvent], AlertSpec]:
    # fires at most once, then hands back a disarmed spec
    if not spec.armed:
        return None, spec
    ev: Optional[AlertEvent] = None
    if spec.condition_type in THRESHOLD_TYPES:
        ev = evaluate_threshold(spec, closed_closes, mark, now)
    elif spec.condition_type in CROSSOVER_TYPES:
        if len(closed_closes) >= 2 and new_indices:
            d = crossover_d(spec, closed_closes)
            ev = scan_crossover(spec, d, list(closed_ts), new_indices, timeframe, now)
    if ev is not None:
        return ev, replace(spec, armed=False, fired_at=now)
    return None, spec
