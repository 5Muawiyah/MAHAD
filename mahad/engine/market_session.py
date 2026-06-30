from __future__ import annotations

import datetime as _dt
from functools import lru_cache
from typing import Literal

SessionState = Literal["open", "closed", "open24"]

_NY = "America/New_York"

# regular session bounds (ET)
OPEN_T = _dt.time(9, 30)
CLOSE_T = _dt.time(16, 0)
EARLY_CLOSE_T = _dt.time(13, 0)


def easter_sunday(year: int) -> _dt.date:
    # anonymous Gregorian algorithm
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return _dt.date(year, month, day + 1)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> _dt.date:
    first = _dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + _dt.timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> _dt.date:
    if month == 12:
        last = _dt.date(year, 12, 31)
    else:
        last = _dt.date(year, month + 1, 1) - _dt.timedelta(days=1)
    return last - _dt.timedelta(days=(last.weekday() - weekday) % 7)


def _observed(d: _dt.date) -> _dt.date:
    # NYSE weekend rule: Sat -> prior Friday, Sun -> next Monday
    if d.weekday() == 5:
        return d - _dt.timedelta(days=1)
    if d.weekday() == 6:
        return d + _dt.timedelta(days=1)
    return d


@lru_cache(maxsize=16)
def holidays_full(year: int) -> frozenset[_dt.date]:
    days: set[_dt.date] = set()
    new_year = _dt.date(year, 1, 1)
    if new_year.weekday() == 6:                       # Sun -> observed Monday
        days.add(_dt.date(year, 1, 2))
    elif new_year.weekday() != 5:                     # Sat -> NOT observed (NYSE rule)
        days.add(new_year)
    days.add(_nth_weekday(year, 1, 0, 3))             # Martin Luther King Jr. Day
    days.add(_nth_weekday(year, 2, 0, 3))             # Washington's Birthday
    days.add(easter_sunday(year) - _dt.timedelta(days=2))   # Good Friday
    days.add(_last_weekday(year, 5, 0))               # Memorial Day
    if year >= 2022:                                  # Juneteenth (NYSE from 2022)
        days.add(_observed(_dt.date(year, 6, 19)))
    days.add(_observed(_dt.date(year, 7, 4)))         # Independence Day
    days.add(_nth_weekday(year, 9, 0, 1))             # Labor Day
    days.add(_nth_weekday(year, 11, 3, 4))            # Thanksgiving
    days.add(_observed(_dt.date(year, 12, 25)))       # Christmas
    return frozenset(days)


@lru_cache(maxsize=16)
def early_closes(year: int) -> dict[_dt.date, _dt.time]:
    # 13:00 ET half-days: Jul 3 and Christmas Eve when Mon-Thu, plus the day after Thanksgiving
    closes: dict[_dt.date, _dt.time] = {}
    jul3 = _dt.date(year, 7, 3)
    if jul3.weekday() <= 3:                           # Mon-Thu only
        closes[jul3] = EARLY_CLOSE_T
    closes[_nth_weekday(year, 11, 3, 4) + _dt.timedelta(days=1)] = EARLY_CLOSE_T
    dec24 = _dt.date(year, 12, 24)
    if dec24.weekday() <= 3:                          # Mon-Thu only
        closes[dec24] = EARLY_CLOSE_T
    return dict(closes)


def _new_york(now_utc: _dt.datetime) -> _dt.datetime:
    # falls back to the US DST rule of thumb when IANA tz data is missing
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=_dt.timezone.utc)
    try:
        from zoneinfo import ZoneInfo
        return now_utc.astimezone(ZoneInfo(_NY))
    except Exception:  # noqa: BLE001 - the documented degrade boundary
        year = now_utc.year
        # second Sunday of March
        d = _dt.date(year, 3, 8)
        dst_start = d + _dt.timedelta(days=(6 - d.weekday()) % 7)
        # first Sunday of November
        d = _dt.date(year, 11, 1)
        dst_end = d + _dt.timedelta(days=(6 - d.weekday()) % 7)
        probe = now_utc.astimezone(_dt.timezone(_dt.timedelta(hours=-5)))
        offset = -4 if dst_start <= probe.date() < dst_end else -5
        return now_utc.astimezone(_dt.timezone(_dt.timedelta(hours=offset)))


def session_state(asset_class: str,
                  now_utc: _dt.datetime | float | None = None) -> SessionState:
    if asset_class == "crypto":
        return "open24"
    if now_utc is None:
        now = _dt.datetime.now(_dt.timezone.utc)
    elif isinstance(now_utc, (int, float)):
        now = _dt.datetime.fromtimestamp(float(now_utc), _dt.timezone.utc)
    else:
        now = now_utc
    local = _new_york(now)
    day = local.date()
    if local.weekday() >= 5:                     # Saturday / Sunday
        return "closed"
    if day in holidays_full(day.year):
        return "closed"
    close_t = early_closes(day.year).get(day, CLOSE_T)
    if OPEN_T <= local.time() < close_t:
        return "open"
    return "closed"


def _is_trading_day(d: _dt.date) -> bool:
    # half-days still count as trading days
    return d.weekday() < 5 and d not in holidays_full(d.year)


def _as_utc(now_utc: _dt.datetime | float | None) -> _dt.datetime:
    if now_utc is None:
        return _dt.datetime.now(_dt.timezone.utc)
    if isinstance(now_utc, (int, float)):
        return _dt.datetime.fromtimestamp(float(now_utc), _dt.timezone.utc)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=_dt.timezone.utc)
    return now_utc


def next_session_open(now_utc: _dt.datetime | float | None = None) -> _dt.datetime:
    now = _as_utc(now_utc)
    local = _new_york(now)
    tz = local.tzinfo
    day = local.date()
    open_today = _dt.datetime.combine(day, OPEN_T, tzinfo=tz)
    if _is_trading_day(day) and local < open_today:
        return open_today
    d = day + _dt.timedelta(days=1)
    while not _is_trading_day(d):
        d += _dt.timedelta(days=1)
    return _dt.datetime.combine(d, OPEN_T, tzinfo=tz)


def _coarse_relative(seconds: float) -> str:
    seconds = max(0.0, seconds)
    if seconds < 3600:                                   # under an hour -> minutes
        m = max(1, round(seconds / 60.0))
        if m < 60:
            return f"in ~{m}m"
        return "in ~1h"                                  # 59.5-60 min rounds up cleanly
    if seconds < 86400:                                  # under a day -> hours
        h = max(1, round(seconds / 3600.0))
        if h < 24:
            return f"in ~{h}h"
        return "in ~1d"                                  # 23.5-24 h rounds up cleanly
    return f"in ~{max(1, int(seconds // 86400))}d"


def next_open_label(now_utc: _dt.datetime | float | None = None) -> str:
    now = _as_utc(now_utc)
    nxt = next_session_open(now)
    delta = (nxt - now).total_seconds()
    return f"Opens {nxt.strftime('%a %H:%M')} ET ({_coarse_relative(delta)})"


def session_line(asset_class: str,
                 now_utc: _dt.datetime | float | None = None) -> tuple[SessionState, str]:
    state = session_state(asset_class, now_utc)
    if state == "open24":
        return state, "Market open · 24/7"
    if state == "open":
        return state, "Market open"
    return state, next_open_label(now_utc)
