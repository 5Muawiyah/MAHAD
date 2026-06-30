# asserts against mahad source text, so it stays in step with the canonical
# strings in mahad.ui.theme without importing the Qt layers
from __future__ import annotations

from pathlib import Path

from mahad.ui import theme

UI_DIR = Path(__file__).resolve().parents[1] / "mahad"


def _source_text() -> str:
    out = []
    for p in sorted(UI_DIR.rglob("*.py")):
        out.append(p.read_text(encoding="utf-8"))
    return "\n".join(out)


def _main_window_text() -> str:
    return (UI_DIR / "ui" / "main_window.py").read_text(encoding="utf-8")


def test_paper_trading_badge_is_retired():
    assert not hasattr(theme, "PAPER_BADGE_TEXT")
    assert not hasattr(theme, "BADGE_TOOLTIP")
    assert "PAPER TRADING" not in _source_text()          # no badge string on any surface


def test_no_paper_badge_widget_in_the_dialogs_or_status_bar():
    gd = (UI_DIR / "ui" / "glass_dialog.py").read_text(encoding="utf-8")
    assert "def paper_badge" not in gd
    for f in ("main_window.py", "order_ticket.py", "reset_dialog.py",
              "alert_dialog.py", "settings_dialog.py"):
        src = (UI_DIR / "ui" / f).read_text(encoding="utf-8")
        assert "paper_badge(" not in src, f


def test_app_name_reflects_stripped():
    assert theme.APP_NAME == "MAHAD"


# ---- About is removed; Help owns the identity line --------------- #

def test_about_is_fully_removed():
    assert not hasattr(theme, "ABOUT_WHAT")
    assert not hasattr(theme, "ABOUT_FULL_NOTE")
    assert not hasattr(theme, "ABOUT_TAGLINE")
    src = _main_window_text()
    assert "_show_about" not in src
    assert '_tool_button("About"' not in src and '"About"' not in src


def test_no_tier_or_out_of_scope_note():
    assert not hasattr(theme, "HELP_OUT")
    src = _source_text()
    assert "MAHAD (FULL)" not in src
    assert "STRIPPED" not in src
    assert "Deliberately out" not in src
    assert "HELP_OUT" not in _main_window_text()           # Help no longer renders it


def test_no_demo_token_anywhere():
    # word-boundary match, so "demotes"/"demonstrate" stay legal
    import re
    for p in sorted(UI_DIR.rglob("*.py")):
        text = p.read_text(encoding="utf-8")
        for m in re.finditer(r"\bdemo\b", text, re.I):
            raise AssertionError(f"{p.name}: demo token at offset {m.start()}")


def test_help_keeps_first_steps_and_the_identity_line():
    assert "Add a symbol" in theme.HELP_TEXT
    assert "BTC/USD" in theme.HELP_TEXT
    assert "arm a one-shot alert." in theme.HELP_TEXT
    low = theme.HELP_TEXT.lower()
    assert "advice" not in low and "virtual money" not in low
    assert "desktop market-risk workstation" in theme.HELP_IDENTITY
    assert "paper trading only" not in theme.HELP_IDENTITY
    assert "HELP_IDENTITY" in _main_window_text()


def test_no_old_warning_copy_anywhere_in_the_app_source():
    src = _source_text()
    assert "virtual money" not in src
    assert "Not financial advice" not in src
    assert "connects to no broker" not in src


# ---- the session line replaced "Live" ----------- #

def _market_session_text() -> str:
    return (UI_DIR / "engine" / "market_session.py").read_text(encoding="utf-8")


def test_live_line_is_replaced_by_the_market_session():
    mw = _main_window_text()
    assert 'f"Live · last update' not in mw
    assert 'f"Stale · last update' not in mw
    # summary is built worker-side in the calendar and only displayed by the window
    ms = _market_session_text()
    assert "def session_line" in ms
    assert '"Market open · 24/7"' in ms
    assert '"Market open"' in ms
    assert "session_state" in ms
    assert "Opens " in ms and " ET (" in ms        # closed-session next-open text
    assert "session_summary" in mw


def test_staleness_stays_internal():
    # chart badge/dim and the ticket confirm gate still read snap.live; only
    # the headline surface changed
    cv = (UI_DIR / "ui" / "chart_view.py").read_text(encoding="utf-8")
    assert "STALE - last good price" in cv
    assert "snap.live" in cv
    ot = (UI_DIR / "ui" / "order_ticket.py").read_text(encoding="utf-8")
    assert "stale" in ot.lower()


def test_status_bar_is_state_not_config():
    src = _main_window_text()
    assert "polling every" not in src  # config echo died
    assert "USD · last poll" in src


# ---- structural guards, read from source ---------------- #

def test_switch_coalescer_exists_with_named_constant():
    src = _main_window_text()
    assert "SWITCH_DEBOUNCE_MS = 250" in src
    assert "begin_switch" in src and "cancel_switch" in src


def test_chart_loading_treatment_and_discard_guard():
    cv = (UI_DIR / "ui" / "chart_view.py").read_text(encoding="utf-8")
    assert "def begin_switch" in cv and "def cancel_switch" in cv
    assert "_pending_switch" in cv
    assert 'setLabel("left", "Price (USD)")' not in cv      # rotated label deleted
    assert "RSI {" in cv or "RSI 14" in cv                  # horizontal corner tag


def test_watchlist_selection_is_tonal_and_noclip():
    wl = (UI_DIR / "ui" / "watchlist_panel.py").read_text(encoding="utf-8")
    assert "border-left: 3px solid" not in wl               # accent bar is gone
    assert "theme.NESTED" in wl and "theme.DIVIDER" in wl   # tonal treatment instead
    assert "setFixedHeight(52)" in wl
    assert "setMinimumWidth(72)" in wl                      # column floor
    assert '"warming up"' in wl and '"last known"' in wl


def test_dialog_headers_have_no_icon_tiles():
    gd = (UI_DIR / "ui" / "glass_dialog.py").read_text(encoding="utf-8")
    assert "DialogIcon" not in gd  # tiles deleted
    assert "DialogTitleWarn" in gd                          # warn rides the title now


def test_alerts_panel_quieting():
    at = (UI_DIR / "ui" / "alerts_tab.py").read_text(encoding="utf-8")
    assert 'QLabel("Alerts")' not in at                     # echo heading died
    assert "armed" in at                                    # count line lives
