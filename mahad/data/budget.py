from __future__ import annotations

import time
from collections import deque
from typing import Callable


class RateBudget:
    def __init__(self, per_minute: int,
                 monotonic: Callable[[], float] = time.monotonic,
                 window_s: float = 60.0) -> None:
        self._cap = max(1, int(per_minute))
        self._monotonic = monotonic
        self._window = float(window_s)
        self._stamps: deque[float] = deque()

    def try_acquire(self) -> bool:
        now = self._monotonic()
        cutoff = now - self._window
        while self._stamps and self._stamps[0] <= cutoff:
            self._stamps.popleft()
        if len(self._stamps) >= self._cap:
            return False
        self._stamps.append(now)
        return True

