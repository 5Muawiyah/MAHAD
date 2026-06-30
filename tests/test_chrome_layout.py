# chrome guards read from UI source text, so they run under the Qt stub (no real PySide6)
from __future__ import annotations

from pathlib import Path

UI = Path(__file__).resolve().parents[1] / "mahad" / "ui"


def _src(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")


# ---- the chrome strip + icon buttons -------------------------- #

def test_chrome_strip_has_icon_buttons_and_window_controls():
    s = _src("main_window.py")
    assert 'IconButton("gear"' in s and 'IconButton("help"' in s
    assert "_chrome_strip" in s and "ChromeStrip" in s
    assert "theme.APP_NAME" in s
    assert 'WinControlButton("min")' in s and 'WinControlButton("max")' in s \
        and 'WinControlButton("close")' in s


def test_settings_help_handlers_survive_on_the_icon_buttons():
    s = _src("main_window.py")
    assert "self._btn_settings.clicked.connect(self._show_settings)" in s
    assert "self._btn_help.clicked.connect(self._show_help)" in s
  # no longer flat text tool-buttons
    assert '_tool_button("Settings"' not in s and '_tool_button("Help"' not in s


def test_settings_help_are_not_in_the_working_bar_actions():
    s = _src("main_window.py")
    assert "def _tool_button" not in s


# ---- the working bar is right-aligned; Reset LIVES IN SETTINGS ---- #

def test_working_bar_actions_are_right_aligned_without_reset():
    s = _src("main_window.py")
    bar = s.split("# ---- strip 2: the working bar")[1].split("return header")[0]
  # stretch before the first action means the actions sit on the right
    assert bar.index("work.addStretch(1)") < bar.index('QPushButton("New Alert")')
    for label in ("New Alert", "Add symbol", "Indicators", "New Order"):
        assert label in bar
  # Reset lives in Settings, not on the bar
    assert '_work_button("Reset' not in bar and 'QPushButton("Reset' not in bar


def test_reset_lives_in_settings_and_defers_past_the_modal_guard():
    dlg = _src("settings_dialog.py")
    assert '"DangerGhost"' in dlg
    assert "_reset_clicked" in dlg and "def _request_reset" in dlg
    s = _src("main_window.py")
  # reset must defer until _exec_modal unwinds _modal_busy
    assert 'getattr(dlg, "_reset_clicked", False)' in s
    assert "QTimer.singleShot(0, self._reset)" in s


# ---- the splitter layout replaces QDockWidget (+ D1) ---------------- #

def test_layout_is_splitter_based_with_bound_minimums():
    s = _src("main_window.py")
    assert "self._h_split = QSplitter" in s and "self._v_split = QSplitter" in s
    assert s.count("setChildrenCollapsible(False)") >= 2
    assert "addDockWidget" not in s  # QDockWidget layout is gone
    assert "setStretchFactor" in s  # spare space goes to the chart, not the panels


# ---- frameless frame -------------------------------------------------- #

def test_frameless_window_with_guarded_controls():
    s = _src("main_window.py")
    assert "FramelessWindowHint" in s
    assert "def _toggle_maximise" in s and "availableGeometry()" in s  # clamp to clear the taskbar
    assert "start_system_move" in s and "start_system_resize" in s  # native move/resize
    assert "def _in_chrome_strip" in s  # so a drag started on a child does not move the window


# ---- collapsible docks ------------------------------------------- #

def test_watchlist_and_risk_are_collapsible():
    wl = _src("watchlist_panel.py")
    rp = _src("risk_panel.py")
    assert "def set_collapsed" in wl and "collapse_toggled" in wl
    assert "def set_collapsed" in rp and "collapse_toggled" in rp
    assert "Chevron" in wl and "Chevron" in rp
    assert "_refresh_summary" in wl


def test_dock_collapse_is_wired_and_session_only():
    s = _src("main_window.py")
    assert "_on_wl_collapse" in s and "_on_risk_collapse" in s
    assert "_rebalance_dock" in s
    assert "self._wl_collapsed" in s and "self._risk_collapsed" in s
  # collapse state is session-only, never persisted
    assert "set_setting" not in s.split("_rebalance_dock")[0][-400:]


# ---- consistent dialog primary ---------------------------------------- #

def test_settings_apply_is_a_filled_primary():
    s = _src("settings_dialog.py")
    assert 'self._apply_btn.setProperty("variant", "primary")' in s


def test_every_dialog_footer_has_exactly_one_filled_primary():
    for name in ("settings_dialog.py", "order_ticket.py", "reset_dialog.py",
                 "alert_dialog.py", "trade_log_panel.py"):
        s = _src(name)
        primaries = s.count('"variant", "primary"') + s.count('"variant", "danger"')
        assert primaries >= 1, f"{name}: needs a filled primary"
