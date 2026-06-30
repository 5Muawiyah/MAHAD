# These read the UI/worker source as text and pin wiring and copy that has no
# headless seam to assert against; they break loudly if a rename drifts.
from __future__ import annotations

import dataclasses
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_shortcuts_are_installed_with_tooltip_hints():
    src = _src("mahad/ui/main_window.py")
    assert "_install_shortcuts()" in src                  # wired in __init__
    for seq in ("Ctrl+N", "Ctrl+Shift+A", "Ctrl+K", "Ctrl+I",
                "Ctrl+E", "Ctrl+Shift+E", "Ctrl+,", "F1",
                "Ctrl+1", "Ctrl+2", "Ctrl+3"):
        assert f'"{seq}"' in src, seq
    assert "QShortcut(QKeySequence(" in src
    assert "(Ctrl+N)" in src                              # tooltip echoes the binding
    src_help = _src("mahad/ui/theme.py")
    assert "Shortcuts: Ctrl+N order" in src_help          # also discoverable in Help


def test_timeframe_shortcut_drives_the_same_intent_path():
    src = _src("mahad/ui/main_window.py")
    block = src.split("def _timeframe_shortcut", 1)[1].split("\n    def ", 1)[0]
    assert "_on_timeframe_intent" in block                # route through the intent, not a bypass


def test_health_chip_is_wired_from_the_snapshot():
    src = _src("mahad/ui/main_window.py")
    assert "_render_health(snap.health)" in src
    assert "_health_dot" in src and "_health_label" in src
    assert "Last error:" in src                           # tooltip carries the why


def test_db_notice_rides_a_discrete_signal_and_is_emitted_on_start():
    wsrc = _src("mahad/worker.py")
    assert "db_notice = Signal(str)" in wsrc
    start = wsrc.split("def start(", 1)[1].split("\n    @Slot()", 1)[0]
    assert "self.db_notice.emit(" in start                # surfaced on start, never silent
    msrc = _src("mahad/ui/main_window.py")
    assert "db_notice.connect(self._on_db_notice)" in msrc
    assert "NO SAVED DATA" in msrc


def test_chart_delta_names_its_basis():
    src = _src("mahad/ui/chart_view.py")
    assert '"vs prev close"' in src and '"vs prev bar"' in src
    assert 'snap.timeframe == "1d"' in src


def test_context_section_defaults_collapsed_with_a_live_summary():
    src = _src("mahad/ui/risk_panel.py")
    assert '"MARKET CONTEXT"' in src
    assert "self._ctx_collapsed = True" in src
    assert "self._ctx_body.hide()" in src
    assert "CtxSummary" in src                            # the collapsed live summary
    assert "Exogenous market data" in src                 # kept apart from the portfolio metrics


def test_context_tooltips_carry_source_and_interpretation():
    src = _src("mahad/ui/risk_panel.py")
    assert "inverted curve" in src                        # the 2s10s reading
    assert "Indicative bands: under 15 calm" in src
    assert "data from alternative.me" in src              # required attribution
    # literal wraps mid-sentence in source, so match a contiguous span
    assert "endorsed or certified by the Federal Reserve Bank of St." in src


def test_snapshot_carries_the_context_fields():
    from mahad.engine.snapshot import RenderSnapshot
    names = {f.name for f in dataclasses.fields(RenderSnapshot)}
    assert {"context", "health", "timeframe"} <= names


def test_cached_degraded_tiles_show_a_visible_as_of():
    # a stale-from-cache tile has to read as degraded at a glance, not only in the tooltip
    src = _src("mahad/ui/risk_panel.py")
    assert "def _degraded(" in src
    assert src.count("self._degraded(") >= 3              # all three tiles
    assert ' · as of {short}' in src


def test_value_history_export_exists_and_is_single_flight():
    src = _src("mahad/ui/risk_panel.py")
    assert "def export_value_history" in src
    assert "build_value_history_csv" in src
    assert 'setEnabled(False)                  # single-flight' in src
    assert "CsvChip" in src


def test_env_example_is_committed_and_env_is_ignored():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    assert "FRED_API_KEY=" in example and "NEVER commit" in example
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    lines = [ln.strip() for ln in gitignore.splitlines()]
    assert ".env" in lines and "!.env.example" in lines


def test_no_credential_kinds_beyond_the_one_free_data_key():
    src = _src("mahad/data/context_sources.py")
    assert "FRED_KEY_ENV" in src
    for forbidden in ("apiKey", "api_secret", "broker", "password"):
        assert forbidden not in src, forbidden
    # structural no-broker guardrail: Kraken stays keyless, only /0/public market
    # data, no private path, no auth header, no signing code anywhere
    kraken_src = _src("mahad/data/kraken_source.py")
    assert kraken_src.count("https://api.kraken.com/0/public/") == 2
    assert "/0/private" not in kraken_src
    assert "API-Sign" not in kraken_src and "API-Key" not in kraken_src
    assert '"Authorization"' not in kraken_src
    for keyed in ("mahad/data/finnhub_source.py", "mahad/data/tiingo_source.py"):
        src_k = _src(keyed)
        # read-only data keys, never logged: redaction has to be in place
        assert "read_env_key" in src_k and "redact" in src_k


def test_worker_never_stores_the_key_value():
    src = _src("mahad/worker.py")
    assert "_ctx_has_key" in src                          # presence only, not the value
    # key is read locally in the refresh and passed straight through; no attribute holds it
    assert "self._key" not in src and "self._api_key" not in src


def test_readme_carries_the_context_copy():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "in-app About" not in readme                   # the removed About stays gone
    assert "not endorsed or certified by the Federal Reserve Bank" in readme
    assert "FRED_API_KEY" in readme and ".env.example" in readme
    assert "Market context" in readme
    assert "Fear & Greed" in readme


def test_engine_documents_the_core_metrics():
    src = _src("mahad/engine/risk_metrics.py")
    for name in ("def historical_var", "def expected_shortfall", "def parametric_var",
                 "def kupiec_pof", "def basel_zone", "def sharpe", "def sortino",
                 "def ewma_volatility", "def concentration", "def component_var"):
        assert name in src, name


def test_the_full_note_stays_single_homed():
    # FULL tier and the Help out-of-scope note (HELP_OUT) both stay retired; the
    # simulated nature is conveyed by the methodology, not a standing note
    pkg = ROOT / "mahad"
    hits = []
    for py in pkg.rglob("*.py"):
        text = py.read_text(encoding="utf-8")
        for m in re.finditer(r"MAHAD \(FULL\)", text):
            hits.append((py.name, m.start()))
    assert hits == [], hits
    theme_src = (pkg / "ui" / "theme.py").read_text(encoding="utf-8")
    assert "HELP_OUT" not in theme_src and "Deliberately out" not in theme_src


def test_no_em_or_en_dashes_in_the_context_files():
    for rel in ("mahad/engine/market_session.py", "mahad/engine/context.py",
                "mahad/data/context_view.py", "mahad/data/context_sources.py",
                "mahad/ui/risk_panel.py", "tests/test_worker_context.py",
                "tests/test_market_context.py", ".env.example"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert "\u2014" not in text and "\u2013" not in text, rel
