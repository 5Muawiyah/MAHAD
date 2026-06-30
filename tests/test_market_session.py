"""Pins the NYSE session contract: 09:30-16:00 America/New_York Mon-Fri, the
2026 holiday and early-close calendar, DST, and crypto 24/7."""
from __future__ import annotations

import datetime as dt

from mahad.engine.market_session import (CLOSE_T, OPEN_T, _coarse_relative,
                                         early_closes, easter_sunday,
                                         holidays_full, next_open_label,
                                         next_session_open, session_line,
                                         session_state)

HOLIDAYS_FULL = holidays_full(2026)  # computed per-year, not a hand-typed constant
EARLY_CLOSES = early_closes(2026)

UTC = dt.timezone.utc


def at(y, m, d, hh, mm):
    return dt.datetime(y, m, d, hh, mm, tzinfo=UTC)


def test_crypto_is_always_open24():
    assert session_state("crypto", at(2026, 6, 6, 3, 0)) == "open24"      # Sat night
    assert session_state("crypto", at(2026, 12, 25, 12, 0)) == "open24"   # Christmas
    assert session_state("crypto", None) == "open24"                       # now


# June dates are EDT (UTC-4), so subtract 4 to read the ET wall clock
def test_stock_open_midweek_midsession():
    assert session_state("stock", at(2026, 6, 3, 18, 0)) == "open"         # Wed 14:00 ET

def test_stock_closed_weekend():
    assert session_state("stock", at(2026, 6, 6, 18, 0)) == "closed"       # Sat
    assert session_state("stock", at(2026, 6, 7, 18, 0)) == "closed"       # Sun

def test_stock_closed_before_open_and_after_close():
    assert session_state("stock", at(2026, 6, 3, 13, 29)) == "closed"      # 09:29 ET
    assert session_state("stock", at(2026, 6, 3, 13, 30)) == "open"        # 09:30 ET boundary
    assert session_state("stock", at(2026, 6, 3, 19, 59)) == "open"        # 15:59 ET
    assert session_state("stock", at(2026, 6, 3, 20, 0)) == "closed"       # 16:00 ET boundary
    assert session_state("stock", at(2026, 6, 3, 20, 1)) == "closed"


def test_stock_closed_on_a_full_holiday():
    assert dt.date(2026, 7, 3) in HOLIDAYS_FULL                            # observed July 4th
    assert session_state("stock", at(2026, 7, 3, 15, 0)) == "closed"       # Fri 11:00 ET

def test_stock_early_close_half_day():
    assert EARLY_CLOSES[dt.date(2026, 11, 27)] == dt.time(13, 0)
    assert session_state("stock", at(2026, 11, 27, 17, 30)) == "open"      # 12:30 ET
    assert session_state("stock", at(2026, 11, 27, 18, 30)) == "closed"    # 13:30 ET

def test_calendar_constant_is_well_formed():
    assert OPEN_T.hour == 9 and OPEN_T.minute == 30
    assert CLOSE_T.hour == 16 and CLOSE_T.minute == 0
    assert all(isinstance(d, dt.date) for d in HOLIDAYS_FULL)
    assert all(t < CLOSE_T for t in EARLY_CLOSES.values())                  # an early close is earlier
    assert not (set(EARLY_CLOSES) & HOLIDAYS_FULL)                          # disjoint sets


def test_dst_winter_vs_summer_same_utc_hour():
    # 20:30 UTC splits the seasons: Jan 15:30 ET (EST) open, Jun 16:30 ET (EDT) closed
    assert session_state("stock", at(2026, 1, 14, 20, 30)) == "open"
    assert session_state("stock", at(2026, 6, 3, 20, 30)) == "closed"

def test_accepts_posix_timestamp_and_naive_utc():
    wed = at(2026, 6, 3, 18, 0)
    assert session_state("stock", wed.timestamp()) == "open"
    assert session_state("stock", wed.replace(tzinfo=None)) == "open"


# cross-check the computed calendar against hand-checked 2026 and the published NYSE 2027 list
def test_computed_2026_equals_the_retired_hand_checked_constant():
    retired = frozenset({
        dt.date(2026, 1, 1), dt.date(2026, 1, 19), dt.date(2026, 2, 16),
        dt.date(2026, 4, 3), dt.date(2026, 5, 25), dt.date(2026, 6, 19),
        dt.date(2026, 7, 3), dt.date(2026, 9, 7), dt.date(2026, 11, 26),
        dt.date(2026, 12, 25)})
    assert holidays_full(2026) == retired
    assert early_closes(2026) == {dt.date(2026, 11, 27): dt.time(13, 0),
                                  dt.date(2026, 12, 24): dt.time(13, 0)}


def test_computed_2027_matches_the_published_nyse_list():
    published = frozenset({
        dt.date(2027, 1, 1),    # New Year's Day (Friday)
        dt.date(2027, 1, 18),   # Martin Luther King Jr. Day
        dt.date(2027, 2, 15),   # Washington's Birthday
        dt.date(2027, 3, 26),   # Good Friday (Easter 2027-03-28)
        dt.date(2027, 5, 31),   # Memorial Day
        dt.date(2027, 6, 18),   # Juneteenth observed (Jun 19 = Saturday)
        dt.date(2027, 7, 5),    # Independence Day observed (Jul 4 = Sunday)
        dt.date(2027, 9, 6),    # Labor Day
        dt.date(2027, 11, 25),  # Thanksgiving
        dt.date(2027, 12, 24)})  # Christmas observed (Dec 25 = Saturday)
    assert holidays_full(2027) == published
    # Christmas Eve IS the observed full holiday in 2027 -> no half-day; the
    # day after Thanksgiving is the only early close. July 3 2027 is a
    # Saturday -> no July half-day.
    assert early_closes(2027) == {dt.date(2027, 11, 26): dt.time(13, 0)}


def test_easter_against_published_dates():
    for year, (m, d) in [(2024, (3, 31)), (2025, (4, 20)), (2026, (4, 5)),
                         (2027, (3, 28)), (2028, (4, 16))]:
        assert easter_sunday(year) == dt.date(year, m, d)


def test_weekend_observation_rules():
    # New Year's on a Saturday is NOT observed early (2022: no Dec 31 2021 close)
    assert dt.date(2021, 12, 31) not in holidays_full(2021)
    assert dt.date(2022, 1, 1) not in holidays_full(2022)
    # New Year's on a Sunday observes Monday (2023-01-02)
    assert dt.date(2023, 1, 2) in holidays_full(2023)
    # July 4 2026 = Saturday -> observed Friday July 3 (and NO July half-day)
    assert dt.date(2026, 7, 3) in holidays_full(2026)
    assert dt.date(2026, 7, 2) not in early_closes(2026)
    # Christmas 2027 = Saturday -> observed Friday Dec 24
    assert dt.date(2027, 12, 24) in holidays_full(2027)


def test_holidays_and_early_closes_stay_disjoint_across_years():
    for year in range(2022, 2031):
        full = holidays_full(year)
        halves = early_closes(year)
        assert not (set(halves) & full), year
        assert all(t < CLOSE_T for t in halves.values())
        assert 9 <= len(full) <= 11, (year, sorted(full))


def test_session_state_uses_the_computed_year_2027():
    def at(y, mo, d, h, mi=0):
        return dt.datetime(y, mo, d, h, mi, tzinfo=dt.timezone.utc)
    # MLK Day 2027 (Jan 18): 11:00 ET = 16:00 UTC - closed despite a weekday
    assert session_state("stock", at(2027, 1, 18, 16, 0)) == "closed"
    # next day, same wall-clock instant, is a regular open Tuesday
    assert session_state("stock", at(2027, 1, 19, 16, 0)) == "open"


def test_next_open_before_today_open_is_today_0930():
    nxt = next_session_open(at(2026, 6, 3, 13, 0))     # Wed 09:00 ET pre-market
    assert (nxt.year, nxt.month, nxt.day) == (2026, 6, 3)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_friday_after_close_is_monday():
    nxt = next_session_open(at(2026, 6, 5, 21, 0))     # Fri 17:00 ET, after close
    assert (nxt.year, nxt.month, nxt.day) == (2026, 6, 8)
    assert nxt.weekday() == 0
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_saturday_is_monday():
    nxt = next_session_open(at(2026, 6, 6, 12, 0))
    assert (nxt.year, nxt.month, nxt.day) == (2026, 6, 8)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_skips_a_full_holiday():
    assert dt.date(2026, 7, 3) in holidays_full(2026)
    nxt = next_session_open(at(2026, 7, 2, 21, 0))     # Thu after close; Fri Jul 3 holiday
    assert (nxt.year, nxt.month, nxt.day) == (2026, 7, 6)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_after_a_half_day_is_the_next_regular_open():
    assert dt.date(2026, 11, 27) in early_closes(2026)
    nxt = next_session_open(at(2026, 11, 27, 19, 0))   # 14:00 ET, after the early close
    assert (nxt.year, nxt.month, nxt.day) == (2026, 11, 30)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_next_open_on_a_half_day_morning_is_that_day_0930():
    nxt = next_session_open(at(2026, 11, 27, 13, 0))   # 08:00 ET on the half-day
    assert (nxt.year, nxt.month, nxt.day) == (2026, 11, 27)
    assert (nxt.hour, nxt.minute) == (9, 30)


def test_coarse_relative_buckets():
    assert _coarse_relative(35 * 60) == "in ~35m"
    assert _coarse_relative(6 * 3600) == "in ~6h"
    assert _coarse_relative(2.5 * 86400) == "in ~2d"
    assert _coarse_relative(0) == "in ~1m"
    assert _coarse_relative(23.4 * 3600) == "in ~23h"
    assert _coarse_relative(90) == "in ~2m"
    assert _coarse_relative(59.7 * 60) == "in ~1h"     # rolls up, never "~60m"
    assert _coarse_relative(23.7 * 3600) == "in ~1d"   # rolls up, never "~24h"


def test_next_open_label_format():
    label = next_open_label(at(2026, 6, 6, 12, 0))
    assert label.startswith("Opens ")
    assert "09:30 ET (in ~" in label
    assert label.endswith(")")


def test_session_line_text_by_state():
    assert session_line("crypto", at(2026, 6, 6, 3, 0)) == ("open24", "Market open · 24/7")
    assert session_line("stock", at(2026, 6, 3, 18, 0)) == ("open", "Market open")
    state, text = session_line("stock", at(2026, 6, 6, 18, 0))
    assert state == "closed"
    assert text.startswith("Opens ")
