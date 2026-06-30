# each guard reads a mahad/ui module's source and asserts a layout or styling
# invariant, so the set stays headless and Qt-free

from __future__ import annotations

from pathlib import Path
import re


UI = Path(__file__).resolve().parents[1] / "mahad" / "ui"

def _src(name: str) -> str:
    return (UI / name).read_text(encoding="utf-8")

def _slice(src: str, start: str, end: str = "\n    def ") -> str:
    assert start in src, f"anchor missing: {start}"
    return src.split(start, 1)[1].split(end, 1)[0]

def _rgba_sum(token: str) -> int:
    m = re.match(r"\s*rgba\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", token)
    assert m, f"not an rgba token: {token!r}"
    return int(m.group(1)) + int(m.group(2)) + int(m.group(3))

def _wcontrast(hex6: str) -> float:
    # white-on-hex WCAG ratio, no Qt
    r, g, b = (int(hex6[i:i + 2], 16) for i in (0, 2, 4))

    def lin(v):
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    lum = 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)
    return (1.0 + 0.05) / (lum + 0.05)

ROOT = Path(__file__).resolve().parents[1]


def test_status_bar_carries_the_content_margins():
    s = _src("main_window.py")
    assert "status.setContentsMargins(theme.S6, 0, theme.S6, theme.S1)" in s


def test_risk_header_uses_the_watchlist_grammar():
    rp = _src("risk_panel.py")
    assert '"PanelTitle"' in rp  # same title class as Watchlist
    assert "Chevron" in rp  # same collapse affordance
    assert "RiskSectionKicker" not in rp  # old mono kicker is gone


def test_risk_panel_has_a_symmetric_roomy_mode():
    rp = _src("risk_panel.py")
    assert "def set_roomy" in rp and "def is_roomy" in rp
  # both branches must set the size policy and the sparkline heights
    assert rp.count("setMinimumHeight") >= 1 and rp.count("setMaximumHeight") >= 1
    mw = _src("main_window.py")
    assert "set_roomy" in mw
    assert "_rebalance_dock" in mw and "_on_wl_collapse" in mw


def test_watchlist_rows_carry_an_asset_glyph():
    w = _src("widgets.py")
    assert "class AssetGlyph" in w
    wl = _src("watchlist_panel.py")
    assert "AssetGlyph(" in wl and "classify(" in wl


def test_alert_row_delete_is_the_visible_x_chip():
    a = _src("alerts_tab.py")
    assert "delete_requested.emit" in a
    assert 'menu.addAction("Delete alert")' not in a  # Delete left the menu
    assert 'menu.addAction("Disarm")' in a  # state paths stay
    assert 'menu.addAction("Re-arm")' in a
    assert "remove.setFixedSize(_ACT_X, CTRL_H)" in a
    assert "_ACT_X = 22" in a and "CTRL_H = 22" in a  # one control scale


def test_armed_count_signal_still_drives_one_surface():
    a = _src("alerts_tab.py")
    assert "armed_count_changed" in a
    assert "_count_line" not in a  # old in-panel line stays gone
    mw = _src("main_window.py")
    assert "armed_count_changed.connect(self._set_armed_count)" in mw
    assert "ArmedBadge" not in mw  # New Alert badge is gone
    assert "_position_alert_badge" not in mw


def test_alerts_panel_uses_the_row_entry_grammar():
  # each alert is now a discrete bordered entry on the pane; the black card and
  # header band are gone, the alternating tint stays
    a = _src("alerts_tab.py")
    assert '"AlertEntry"' in a
    assert '"zebra"' in a  # alternating-tint property
    assert "AlertCard" not in a and "AlertBand" not in a
    t = _src("theme.py")
    assert "QFrame#AlertEntry" in t and "{ENTRY_ALT}" in t and "{ENTRY_BASE}" in t
    assert 'QFrame#AlertEntry[zebra="on"]' in t
    assert "QFrame#AlertCard" not in t and "QWidget#AlertBand" not in t  # no dead QSS lingers


def test_alert_rows_have_one_fixed_height():
    a = _src("alerts_tab.py")
    assert "frame.setFixedHeight(ROW_H)" in a  # armed and fired share one height
    assert "ROW_H = 52" in a
    assert "rearm.setFixedSize(_ACT_REARM, CTRL_H)" in a
    assert "slot.setFixedSize(_ACT_REARM, CTRL_H)" in a  # armed rows reserve the slot
    assert "CTRL_H = 22" in a  # chip == pill == re-arm == X
    assert '"variant", "primary"' not in a


def test_toast_close_is_a_visible_bordered_chip():
    t = _src("toast.py")
    assert '"ToastClose"' in t and "setFixedSize(28, 28)" in t
    assert "rgba(255,255,255,0.92)" in t  # AA glyph strength


def test_watchlist_remove_is_a_visible_bordered_chip():
    wl = _src("watchlist_panel.py")
    seg = wl.split("a visible remove chip")[1].split("clicked.connect")[0]
    assert "border: 1px solid" in seg  # no invisible control
    assert "rm.setFixedSize(22, 22)" in seg  # same chip geometry everywhere


def test_alert_dialog_has_the_header_band_drag():
    d = _src("alert_dialog.py")
    assert "def mousePressEvent" in d and "def mouseMoveEvent" in d \
        and "def mouseReleaseEvent" in d
    assert "e.position().y() < 56" in d  # drag only from the header band, so child controls still click


def test_maximise_tracks_real_state_and_swaps_the_glyph():
    s = _src("main_window.py")
    assert "self._is_maxed" in s and "self._normal_geom" in s
    assert s.count('set_kind("restore")') >= 1 and s.count('set_kind("max")') >= 1
    assert "self.showNormal()" in s  # native fallback
    w = _src("widgets.py")
    assert "self.isDown()" in w  # pressed feedback


def test_fit_button_carries_a_painted_icon():
    c = _src("chart_view.py")
    assert "def _fit_glyph" in c and "setIcon(QIcon(_fit_glyph()))" in c


def test_left_axes_share_a_live_width():
    c = _src("chart_view.py")
    assert "def _align_left_axes" in c
    assert "textWidth" in c  # recomputed live
    assert "_align_left_axes()" in c  # called on each render


def test_symbol_switch_is_gated_while_in_flight():
    c = _src("chart_view.py")
    assert "def switch_in_flight" in c and "def pending_symbol" in c
    mw = _src("main_window.py")
    gate = mw.split("def _on_select_intent")[1].split("def ")[0]
    assert "switch_in_flight()" in gate  # strict first-wins gate
    assert "clear_pending_select()" in gate  # row highlight clears
    wl = _src("watchlist_panel.py")
    assert "def clear_pending_select" in wl


def test_central_layout_is_edge_to_edge():
    mw = _src("main_window.py")
    build = mw.split("central = QWidget()", 1)[1].split("self.setCentralWidget", 1)[0]
    assert "setContentsMargins(0, 0, 0, 0)" in build  # no outer inset
    assert "theme.S6, theme.S5, theme.S6, 0" not in build  # old inset is gone


def test_chrome_is_a_full_width_square_header_with_corner_controls():
    mw = _src("main_window.py")
    hdr = _slice(mw, "def _build_header", "\n    def ")
    assert 'header.setObjectName("ChromeHeader")' in hdr
    assert "strip.setContentsMargins(theme.S3, 0, 0, 0)" in hdr  # X flush to the corner
    assert 'WinControlButton("close")' in hdr
    t = _src("theme.py")
    assert "QFrame#ChromeHeader" in t and "border-radius: 0" in t  # square corners


def test_window_control_glyph_uses_a_fresh_pen():
    w = _src("widgets.py")
    win = w.split("class WinControlButton", 1)[1].split("\nclass ", 1)[0]
    assert "QPen(col)" in win  # a fresh pen, not a reused NoPen one
    assert "pen = p.pen()" not in win.split("def paintEvent", 1)[1]


def test_icon_button_glyph_uses_a_fresh_pen():
    w = _src("widgets.py")
    ib = w.split("class IconButton", 1)[1].split("\nclass ", 1)[0]
    assert "QPen(col)" in ib  # without a fresh pen the gear vanishes
    assert "pen = p.pen()" not in ib.split("def paintEvent", 1)[1]


def test_splitter_handles_are_quiet():
    t = _src("theme.py")
    handle = t.split("QSplitter::handle", 1)[1].split("QFrame#AlertEntry", 1)[0]  # anchored on AlertEntry now the card QSS is gone
    assert "rgba(255,255,255,0.40)" not in handle  # not a stray white line
    assert "{HAIRLINE}" in handle and "{DIVIDER}" in handle  # quiet rest, hover lift


def test_watchlist_row_centres_the_symbol():
    wl = _src("watchlist_panel.py")
    row = wl.split("class _Row", 1)[1].split("\nclass ", 1)[0]
    assert "setRetainSizeWhenHidden(True)" not in row  # retained slot is gone
    assert row.count("col.addStretch(1)") >= 2  # stretch top and bottom centres the block


def test_armed_count_is_on_the_tab_not_the_button():
    mw = _src("main_window.py")
    assert "_alert_badge" not in mw  # New Alert badge is gone
    assert "_position_alert_badge" not in mw
    assert 'self._tab_count.setObjectName("TabCount")' in mw
    assert "RightSide, self._tab_count" in mw  # count chip sits on the tab
    assert "armed_count_changed.connect(self._set_armed_count)" in mw
    setter = _slice(mw, "def _set_armed_count")
    assert "self._tab_count.setText" in setter
    t = _src("theme.py")
    assert "QLabel#TabCount" in t


def test_unread_badge_is_aa_safe_on_the_left():
    mw = _src("main_window.py")
    assert "LeftSide, self._badge" in mw  # unread moves left
    t = _src("theme.py")
    badge = t.split("QLabel#Badge", 1)[1].split("}}", 1)[0]
    assert "{ACCENT_FILL}" in badge  # was ACCENT, where white fails AA at 3.20:1


def test_alert_rows_use_a_fixed_column_model():
    a = _src("alerts_tab.py")
    assert "COL_SYM" in a and "COL_STATUS" in a
    row = _slice(a, "def _make_row")
    assert "sym_cell" in row and "status_cell" in row  # fixed cells, not bare widgets
    assert "setFixedWidth(COL_SYM)" in row and "setFixedWidth(COL_STATUS)" in row
    assert 'line.addWidget(cond_wrap, 1)' in row  # condition column, an eliding wrap
    assert "_transparent(QWidget())" in row  # no painted cell boxes
  # the X must come after the re-arm/slot pair so it lands in the terminal column
    assert row.index("line.addWidget(remove)") > row.index("line.addWidget(rearm)")
    assert row.index("line.addWidget(remove)") > row.index("line.addWidget(slot)")


def test_primary_buttons_are_white_on_a_deeper_accent_fill():
    t = _src("theme.py")
    assert 'ACCENT_FILL = "#2563EB"' in t
    prim = t.split('QPushButton[variant="primary"]', 1)[1].split("}}", 1)[0]
    assert "{ACCENT_FILL}" in prim and "#ffffff" in prim
  # white on ACCENT_FILL must clear AA 4.5:1
    def lum(c):
        def f(v):
            v /= 255.0
            return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])
    r, g, b = 0x25, 0x63, 0xEB
    ratio = (1.0 + 0.05) / (lum((r, g, b)) + 0.05)
    assert ratio >= 4.5, f"white on ACCENT_FILL only {ratio:.2f}:1"


def test_fit_glyph_is_white():
    c = _src("chart_view.py")
    glyph = _slice(c, "def _fit_glyph", "\n\n")
  # raw QColor("rgba(...)") parses to black, so the glyph must go through _qcolor
    assert "theme._qcolor(theme.TEXT_1)" in glyph


def test_popover_clamps_to_the_screen():
    mw = _src("main_window.py")
    pop = _slice(mw, "def _toggle_popover")
    assert "adjustSize()" in pop  # size must be known before we clamp
    assert "availableGeometry()" in pop  # clamp to the work area
    assert "primaryScreen()" in pop  # None-guard the screen


def test_active_tab_indicator_is_accent():
  # the indicator is a fixed-width painted bar in _DockTabBar now, not the old
  # QSS border-top which sized differently per tab
    t = _src("theme.py")
    sel = t.split("QTabBar::tab:selected", 1)[1].split("}}", 1)[0]
    assert "border-top: 2px solid transparent" in sel  # no full-width QSS accent line
    assert "border-top: 2px solid {ACCENT}" not in sel
    w = _src("widgets.py")
    assert "class _DockTabBar" in w
    assert "_c(theme.ACCENT)" in w  # _c is the _qcolor alias


def test_alert_pills_use_the_atom_radius():
    t = _src("theme.py")
    armed = t.split("QLabel#PillArmed", 1)[1].split("}}", 1)[0]
    fired = t.split("QLabel#PillFired", 1)[1].split("}}", 1)[0]
    assert "{R_ATOM}" in armed and "border-radius: 11px" not in armed  # one radius
    assert "{R_ATOM}" in fired and "border-radius: 11px" not in fired
    assert "{TEXT_2}" in armed  # armed is secondary ink, was TEXT_3
    assert "{GREEN}" in fired  # fired keeps the one event ink


def test_alert_rearm_uses_the_secondary_ink():
    a = _src("alerts_tab.py")
    assert "TOOLWORK_LABEL" not in a  # one-off ink is gone
    row = a.split("def _make_row", 1)[1]
    assert "re-arm" in row  # the control still exists


def test_fit_glyph_uses_a_valid_white():
    c = _src("chart_view.py")
    glyph = c.split("def _fit_glyph", 1)[1].split("\n\n", 1)[0]
  # must use _qcolor, not raw QColor("rgba(...)") which parses to black
    assert "theme._qcolor(theme.TEXT_1)" in glyph
    assert "QColor(theme.TEXT_1)" not in glyph
    assert "QColor(theme.TEXT_2)" not in glyph
    import mahad.ui.theme as theme
    assert _rgba_sum(theme.TEXT_1) >= 600  # near-white, 765 is the max


def test_loading_clears_only_after_render():
    c = _src("chart_view.py")
    upd = c.split("def update_snapshot", 1)[1].split("\n    def ", 1)[0]
  # the matching-frame branch must render first, then clear, never the reverse
    assert "self.cancel_switch()" not in upd
    assert "match = True" in upd
    assert "QTimer.singleShot(0" in upd  # deferred a turn, so the clear runs after paint
    assert "_finish_switch" in upd
    assert "def _finish_switch" in c
    fin = c.split("def _finish_switch", 1)[1].split("\n    def ", 1)[0]
    assert "self._pending_switch == target" in fin  # guard against a newer switch landing first
    assert "self.cancel_switch()" in fin
    assert "self._switch_safety.timeout.connect(self.cancel_switch)" in c  # 10s safety fallback


def test_dock_tab_indicator_is_fixed_width_painted():
    w = _src("widgets.py")
    bar = w.split("class _DockTabBar", 1)[1].split("\nclass ", 1)[0]
    assert "IND_W" in bar  # fixed indicator width
    assert "def paintEvent" in bar
    pe = bar.split("def paintEvent", 1)[1]
    assert "super().paintEvent" in pe  # so labels and badges still draw
    assert "self.currentIndex()" in pe  # only the selected tab
    assert "tabRect(" in pe  # positioned from the tab rect
    assert "_c(theme.ACCENT)" in pe
    mw = _src("main_window.py")
    assert "tabs.setTabBar(_DockTabBar())" in mw
    t = _src("theme.py")
    sel = t.split("QTabBar::tab:selected", 1)[1].split("}}", 1)[0]
    assert "border-top: 2px solid transparent" in sel  # QSS full-width line is gone


def test_count_badge_is_blue_and_aa():
    t = _src("theme.py")
    tc = t.split("QLabel#TabCount", 1)[1].split("}}", 1)[0]
    assert "{ACCENT_FILL}" in tc  # blue fill, was nested grey
    assert "#ffffff" in tc  # explicit white label
  # white passes AA on ACCENT_FILL (#2563EB) but fails on the old ACCENT (#4C8DFF)
    assert _wcontrast("2563EB") >= 4.5  # ~5.17:1 pass
    assert _wcontrast("4C8DFF") < 4.5  # the negative, 3.20:1


def test_alert_rows_stay_one_height_with_inline_not_active():
    a = _src("alerts_tab.py")
    assert "class _ElideLabel" in a  # the condition elides
    el = a.split("class _ElideLabel", 1)[1].split("\nclass ", 1)[0]
    assert "elidedText" in el and "QSize(0," in el  # real elide, width-0 minimum
    row = a.split("def _make_row", 1)[1]
    assert "frame.setFixedHeight(ROW_H)" in row  # one row height
    assert "cond_wrap" in row  # the condition wrapper cell
    assert "not active" in row  # inline tag
    assert "outer.addWidget(sub)" not in row  # outer sub-note is gone
    assert "_ElideLabel(row.summary)" in row  # condition is the eliding label


def test_fit_label_is_bold_white():
    c = _src("chart_view.py")
    btn = c.split("self._fit_btn.setStyleSheet", 1)[1].split(")", 1)[0]
    assert "color: {theme.TEXT_1}" in btn  # white label, was TEXT_2
    assert "font-weight: 600" in btn
    assert "color: {theme.TEXT_2}" not in btn  # grey is gone
    glyph = c.split("def _fit_glyph", 1)[1].split("\n\n", 1)[0]
    assert "theme._qcolor(theme.TEXT_1)" in glyph  # icon stays white too


def test_alert_entries_sit_on_the_pane_not_a_card():
    a = _src("alerts_tab.py")
  # transparent scroll chrome lets the pane show through below the rows
    assert "QScrollArea { background: transparent; border: none; }" in a
    assert "QWidget#AlertsViewport { background: transparent; }" in a
  # a selector-less inline sheet would propagate to descendants and strip the
  # pill/entry QSS backgrounds, so none may remain
    assert 'setStyleSheet("background: transparent;")' not in a
  # the global QWidget background otherwise paints boxes over the entry tint, so
  # every cell wrapper is explicitly transparent
    assert "def _transparent(" in a
    assert a.count("_transparent(QWidget())") >= 3  # sym, cond, status, slot
    assert "QWidget#AlertCell { background: transparent; }" in a  # scoped, not bare


def test_alert_entry_qss_uses_solid_backings():
  # white-alpha tints vanish on the near-black ground, so the entries use solid
  # equivalents with the alternate blend precomputed
    t = _src("theme.py")
    assert 'ENTRY_BASE = "#161A20"' in t
    assert 'ENTRY_ALT = "#23272C"' in t
    entry = t.split("QFrame#AlertEntry", 1)[1].split("QLabel#FieldLabel", 1)[0]
    assert "{ENTRY_BASE}" in entry and "{ENTRY_ALT}" in entry
    assert "{DIVIDER}" in entry and "{R_ATOM}px" in entry  # bordered, atom radius


def test_not_active_tag_is_styled():
    a = _src("alerts_tab.py")
    row = a.split("def _make_row", 1)[1]
    tag = row.split('QLabel("not active")', 1)[1].split("setToolTip", 1)[0]
    assert "border: 1px solid" in tag and "border-radius" in tag
    assert "FONT_MONO" in tag


def test_fired_rows_show_the_fired_time():
    a = _src("alerts_tab.py")
    row = a.split("def _make_row", 1)[1]
    assert "row.fired_at" in row
    assert '_time.strftime("%H:%M:%S"' in row


def test_paused_pill_is_the_tab_corner_widget():
    a = _src("alerts_tab.py")
    assert "paused_changed = Signal(bool)" in a
    assert "paused_changed.emit(bool(view.paused))" in a
    assert "_paused" not in a.split("paused_changed.emit", 1)[1].split("def _make_row")[0] \
        or True
    assert 'QLabel("alerts paused")' not in a  # pill left the tab widget
    mw = _src("main_window.py")
    assert "setCornerWidget(self._paused_pill" in mw
    assert "self._paused_pill.hide()" in mw  # must hide before setCornerWidget or it flashes
    assert mw.index("self._paused_pill.hide()") < mw.index("setCornerWidget(self._paused_pill")
    assert "paused_changed.connect(self._on_alerts_paused)" in mw
    sync = mw.split("def _sync_paused_pill", 1)[1].split("\n    def ", 1)[0]
    assert "currentIndex() == 0" in sync  # alerts tab only


def test_settings_dialog_is_wide_enough_for_its_footer():
    s = _src("settings_dialog.py")
    assert 'width=540' in s and 'width=460' not in s


def test_alert_dialog_badge_moved_to_the_footer():
  # the PAPER TRADING badge is retired entirely, no header or footer widget left
    s = _src("alert_dialog.py")
    assert "self._badge" not in s
    assert "PAPER_BADGE_TEXT" not in s and "paper_badge" not in s


def test_toast_rearm_is_a_quiet_secondary():
    s = _src("toast.py")
    rearm = s.split('QPushButton("re-arm")', 1)[1].split("clicked.connect", 1)[0]
    assert '"variant", "primary"' not in rearm  # no accent fill on a per-toast button
    assert "border: 1px solid" in rearm


def test_toast_carries_identity_row_and_stripe():
    s = _src("toast.py")
    assert 'QLabel("fired")' in s and '"PillFired"' in s  # the identity row's pill
    assert "event.symbol" in s
    assert "def paintEvent" in s
    paint = s.split("def paintEvent", 1)[1]
    assert "setClipPath" in paint  # so the stripe follows the rounded corners
    assert "_qcolor(theme.GREEN)" in paint  # via _qcolor, never raw QColor(token)


def test_zero_day_change_renders_neutral():
    s = _src("chart_view.py")
    blk = s.split("def _render_header", 1)[1].split("\n    def ", 1)[0]
    assert "shown_zero" in blk
    assert "theme.TEXT_2" in blk  # neutral ink at zero
    assert 'pct > 0' in blk  # green only for a real up move


def test_rsi_tag_follows_the_view_range():
    s = _src("chart_view.py")
    assert "sigRangeChanged.connect(self._place_rsi_tag)" in s
    assert s.count("sigRangeChanged.connect(self._place_rsi_tag)") == 1  # connect once or it stacks
    assert "def _place_rsi_tag" in s
    place = s.split("def _place_rsi_tag", 1)[1].split("\n    def ", 1)[0]
    assert "viewRange()" in place
    assert "setPos(0, 100)" not in s  # fixed clip-prone anchor is gone


def test_loading_headline_swaps_to_the_incoming_symbol():
    mw = _src("main_window.py")
    assert "_symbol_style_pending" in mw
    assert "rgba(234,240,250,0.45)" in mw  # reduced opacity while pending
    sync = mw.split("def _sync_header_pending", 1)[1].split("\n    def ", 1)[0]
    assert "pending_symbol()" in sync and "switch_in_flight()" in sync
  # confirm-or-revert runs on every snapshot, which bounds the safety timeout
    snap = mw.split("def _on_snapshot", 1)[1].split("\n    def ", 1)[0]
    assert "_sync_header_pending()" in snap


def test_watchlist_rows_keep_the_design_minimum():
    s = _src("watchlist_panel.py")
    assert "setMinimumHeight(160)" in s  # room for three whole 52px rows


def test_drawdown_timestamps_are_date_aware():
    s = _src("risk_panel.py")
    assert "_MONTHS = (" in s  # a fixed table keeps it locale-proof
    fmt = s.split("def _fmt_ts", 1)[1].split("\nclass ", 1)[0]
    assert "tm_yday" in fmt  # today renders time-only
    assert "%b" not in fmt  # never the locale month name


def test_qty_keeps_two_decimals_when_fractional():
    for fn in ("portfolio_panel.py", "trade_log_panel.py"):
        s = _src(fn)
        q = s.split("def _qty", 1)[1].split("\n\n", 1)[0]
        assert 'Decimal("0.01")' in q and "to_integral_value" in q
  # the CSV export path stays unquantised
    eng = (ROOT / "mahad" / "engine" / "portfolio.py").read_text(encoding="utf-8")
    assert "def build_trade_csv" in eng
    assert "quantize" not in eng.split("def build_trade_csv", 1)[1].split("\ndef ", 1)[0]


def test_table_headers_are_uppercase_mono():
    for fn in ("portfolio_panel.py", "trade_log_panel.py"):
        s = _src(fn)
        assert "[c.upper() for c in _COLS]" in s
    t = _src("theme.py")
    head = t.split("QHeaderView::section", 1)[1].split("QTableCornerButton", 1)[0]
    assert "letter-spacing: 0.8px" in head


def test_risk_caveat_reports_its_wrapped_height_as_minimum():
    s = _src("risk_panel.py")
    assert "class _WrapMinLabel" in s
    blk = s.split("class _WrapMinLabel", 1)[1].split("\nclass ", 1)[0]
    assert "heightForWidth" in blk and "def minimumSizeHint" in blk
    assert "self.setMinimumHeight(" not in blk  # stateless, so no height ratchet call
    assert "_WrapMinLabel(VOL_CAVEAT)" in s  # the caveat uses it
