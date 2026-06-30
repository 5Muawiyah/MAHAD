from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Union

import numpy as np
import numpy.typing as npt

from mahad.config import EMA_PERIOD, RSI_PERIOD, SMA_PERIOD

Closes = Union[Sequence[float], npt.NDArray[np.float64]]

SMA = "sma"
EMA = "ema"
RSI = "rsi"


MIN_PERIOD: int = 2
MAX_PERIOD: int = 400          # <= history_cap (500); a soft UI/stepper ceiling


def clamp_period(period: object) -> int:
    try:
        p: int = int(period)  # type: ignore[call-overload] # clamps arbitrary input
    except (TypeError, ValueError):
        return MIN_PERIOD
    return max(MIN_PERIOD, min(MAX_PERIOD, p))


def bars_needed(kind: str, period: int, n_closed: int) -> int:
    need = period + 1 if kind == RSI else period
    return max(0, need - int(n_closed))


@dataclass(frozen=True, slots=True)
class IndicatorSettings:
    sma_enabled: bool = False
    sma_period: int = SMA_PERIOD
    ema_enabled: bool = False
    ema_period: int = EMA_PERIOD
    rsi_enabled: bool = False
    rsi_period: int = RSI_PERIOD

    def to_dict(self) -> dict[str, object]:
        return {
            "sma_enabled": bool(self.sma_enabled), "sma_period": int(self.sma_period),
            "ema_enabled": bool(self.ema_enabled), "ema_period": int(self.ema_period),
            "rsi_enabled": bool(self.rsi_enabled), "rsi_period": int(self.rsi_period),
        }

    @classmethod
    def from_dict(cls, data: Optional[dict[str, object]]) -> IndicatorSettings:
        if not isinstance(data, dict):
            return cls()

        def flag(key: str) -> bool:
            v = data.get(key, False)
            return bool(v) if isinstance(v, (bool, int)) else False

        def period(key: str, default: int) -> int:
            return clamp_period(data.get(key, default))

        return cls(
            sma_enabled=flag("sma_enabled"), sma_period=period("sma_period", SMA_PERIOD),
            ema_enabled=flag("ema_enabled"), ema_period=period("ema_period", EMA_PERIOD),
            rsi_enabled=flag("rsi_enabled"), rsi_period=period("rsi_period", RSI_PERIOD),
        )


def _as_closes(closes: Closes) -> npt.NDArray[np.float64]:
    return np.asarray(closes, dtype=float)


def sma(closes: Closes, period: int) -> npt.NDArray[np.float64]:
    x = _as_closes(closes)
    n = x.size
    out = np.full(n, np.nan, dtype=float)
    if period < 1 or n < period:
        return out
    kernel = np.ones(period, dtype=float) / period
    out[period - 1:] = np.convolve(x, kernel, mode="valid")
    return out


def ema(closes: Closes, period: int) -> npt.NDArray[np.float64]:
    """seeded from the SMA at index period - 1, not from the first close"""
    x = _as_closes(closes)
    n = x.size
    out = np.full(n, np.nan, dtype=float)
    if period < 1 or n < period:
        return out
    alpha = 2.0 / (period + 1.0)
    out[period - 1] = x[:period].mean()                     # SMA seed
    for i in range(period, n):
        out[i] = alpha * x[i] + (1.0 - alpha) * out[i - 1]
    return out


def _rsi_from_avgs(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0.0:
        return 50.0 if avg_gain == 0.0 else 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def wilder_rsi(closes: Closes, period: int) -> npt.NDArray[np.float64]:
    """Wilder's 1978 smoothing, first average seeded from a plain SMA"""
    x = _as_closes(closes)
    n = x.size
    out = np.full(n, np.nan, dtype=float)
    if period < 1 or n < period + 1:
        return out
    deltas = np.diff(x)                                     # delta into close i is deltas[i-1]
    gains = np.where(deltas > 0.0, deltas, 0.0)
    losses = np.where(deltas < 0.0, -deltas, 0.0)
    # SMA seed: mean of the first `period` gains/losses
    avg_gain = float(gains[:period].mean())
    avg_loss = float(losses[:period].mean())
    out[period] = _rsi_from_avgs(avg_gain, avg_loss)
    for i in range(period + 1, n):
        g = float(gains[i - 1])
        l = float(losses[i - 1])
        avg_gain = (avg_gain * (period - 1) + g) / period   # Wilder smoothing
        avg_loss = (avg_loss * (period - 1) + l) / period
        out[i] = _rsi_from_avgs(avg_gain, avg_loss)
    return out


def compute(kind: str, closes: Closes, period: int) -> npt.NDArray[np.float64]:
    if kind == SMA:
        return sma(closes, period)
    if kind == EMA:
        return ema(closes, period)
    if kind == RSI:
        return wilder_rsi(closes, period)
    raise ValueError(f"unknown indicator kind: {kind!r}")
