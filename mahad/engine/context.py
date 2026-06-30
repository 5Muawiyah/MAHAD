from __future__ import annotations

from typing import Optional


def spread_bp(y2: Optional[float], y10: Optional[float]) -> Optional[float]:
    if y2 is None or y10 is None:
        return None
    return round((float(y10) - float(y2)) * 100.0, 1)


def curve_reading(spread: Optional[float]) -> str:
    # negative inverts, under 25bp is flat, else normal
    if spread is None:
        return ""
    if spread < 0.0:
        return "inverted"
    if spread < 25.0:
        return "flat"
    return "normal"


def vix_band(value: Optional[float]) -> str:
    if value is None:
        return ""
    v = float(value)
    if v < 15.0:
        return "calm"
    if v < 25.0:
        return "normal"
    if v < 35.0:
        return "elevated"
    return "extreme"
