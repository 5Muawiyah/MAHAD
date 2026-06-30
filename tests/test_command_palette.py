from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_command_palette_module_shape():
    src = _src("mahad/ui/command_palette.py")
    assert "class CommandPalette(GlassDialog)" in src
    assert "def _refilter" in src and "def _run_current" in src
    assert "def eventFilter" in src
    assert "Key_Down" in src and "Key_Up" in src
    assert "Key_Return" in src or "Key_Enter" in src
    assert "self.chosen" in src


def test_main_window_wires_the_palette():
    src = _src("mahad/ui/main_window.py")
    assert "def _open_command_palette" in src
    assert "def _command_registry" in src
    assert '("Ctrl+Shift+P", self._open_command_palette)' in src
    # handler runs after the palette closes, so we never stack modals
    assert "if dlg.chosen is not None:" in src


def test_registry_covers_core_commands():
    src = _src("mahad/ui/main_window.py")
    reg = src.split("def _command_registry", 1)[1].split("def _open_command_palette", 1)[0]
    for label in ("New simulated order", "New alert", "Add symbol to watchlist",
                  "Indicator overlays", "Settings", "Help", "Timeframe 1m",
                  "Export trades CSV", "Show Portfolio tab",
                  "Toggle Risk Analytics", "Toggle Market Context"):
        assert label in reg, label


def test_palette_is_discoverable_in_help():
    from mahad.ui import theme
    assert "Ctrl+Shift+P" in theme.HELP_TEXT
    assert "command palette" in theme.HELP_TEXT.lower()


def test_palette_has_clear_empty_state():
    # no match shows a non-selectable placeholder, not an empty list
    src = _src("mahad/ui/command_palette.py")
    assert "No commands match" in src
    assert "NoItemFlags" in src
