"""Spam-click and rapid-input robustness.

Two layers: worker-side behavioural guards run for real under the Qt stub;
the UI-widget guards can't be instantiated headless, so we assert their source
instead and fail loudly if a future edit drops one.
"""
from __future__ import annotations

import time
from pathlib import Path

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.data.models import Candle, Quote
from mahad.engine.indicators import IndicatorSettings
from mahad.engine.signals import AlertSpec
from mahad.worker import PollWorker, _interrupted

REPO = Path(__file__).resolve().parents[1]


def _worker(tmp_path) -> PollWorker:
    w = PollWorker(symbol="AAPL", timeframe="1d", db_url=f"sqlite:///{tmp_path / 'w.db'}")
    w._open_repo()
    w._load_portfolio()
    return w


def _fresh_buy(w, qty="1", mark=100.0):
    w.place_order({"side": "buy", "qty": qty, "symbol": "AAPL",
                   "mark": mark, "ts": time.time()})


def test_indicator_settings_skip_unchanged(tmp_path):
    w = _worker(tmp_path)
    w._settings = IndicatorSettings(sma_enabled=True, sma_period=20)
    n = len(w.snapshot_ready.emissions)
    w.set_indicator_settings(IndicatorSettings(sma_enabled=True, sma_period=20))
    assert len(w.snapshot_ready.emissions) == n, "an identical settings object must not rebuild"
    w.set_indicator_settings(IndicatorSettings(sma_enabled=True, sma_period=21))
    assert len(w.snapshot_ready.emissions) == n + 1, "a real change must rebuild once"


def test_place_order_blocks_reentrant(tmp_path):
    w = _worker(tmp_path)
    w._order_in_flight = True                      # a fill already in progress
    _fresh_buy(w)
    res = w.order_result.emissions[-1][0]
    assert res["ok"] is False and "in progress" in res["reason"]
    assert len(w._trades) == 0, "no fill while one is in flight"


def test_single_buy_books_one_trade(tmp_path):
    w = _worker(tmp_path)
    _fresh_buy(w)
    assert len(w._trades) == 1 and w.order_result.emissions[-1][0]["ok"] is True


def test_clear_trade_log_count_guard(tmp_path):
    w = _worker(tmp_path)
    _fresh_buy(w)
    assert len(w._trades) == 1
    w.clear_trade_log(expected_count=999)          # log changed since export -> skip
    assert len(w._trades) == 1, "a count mismatch must NOT wipe the log"
    w.clear_trade_log(expected_count=1)
    assert len(w._trades) == 0
    w.clear_trade_log(expected_count=-1)           # legacy no-count path still clears
    assert len(w._trades) == 0


def test_reset_in_flight_drops_reentrant(tmp_path):
    w = _worker(tmp_path)
    w._reset_in_flight = True
    n = len(w.snapshot_ready.emissions)
    w.reset_portfolio({})
    assert len(w.snapshot_ready.emissions) == n, "a re-entrant reset is dropped"
    w._reset_in_flight = False
    w.reset_portfolio({})
    assert len(w.snapshot_ready.emissions) == n + 1, "a normal reset proceeds"


def test_intents_noop_after_stop(tmp_path):
    w = _worker(tmp_path)
    w._stop = True
    n_order = len(w.order_result.emissions)
    _fresh_buy(w)
    assert len(w.order_result.emissions) == n_order, "no order result after stop"
    assert len(w._trades) == 0
    # these must neither raise nor act
    w.add_symbol("ZZZZ")
    w.arm_alert({"condition_type": "price_threshold", "params": {"level": 1.0},
                 "direction": "up"})
    w.clear_trade_log(0)
    w.reset_portfolio({})
    assert _interrupted() is False, "the stub reports no interruption (defensive helper)"


# a torn _alerts list must still fire against the right spec by identity, not index
def test_evaluate_alerts_applies_by_identity(tmp_path):
    w = _worker(tmp_path)
    w._symbol = "AAPL"
    now = time.time()
    w._last_quote = Quote("AAPL", 100.0, now, "fake", False)     # fresh, not stale
    w._candles = (Candle("AAPL", "1d", now - 7200, 99, 101, 98, 100, 10.0, True),
                  Candle("AAPL", "1d", now - 3600, 100, 102, 99, 101, 10.0, True))
    keep = AlertSpec(id=11, symbol="AAPL", condition_type="rsi_threshold",
                     params={"rsi_period": 14, "level": 99.0}, direction="up", armed=True)
    fires = AlertSpec(id=12, symbol="AAPL", condition_type="price_threshold",
                      params={"level": 50.0}, direction="up", armed=True)   # mark 100 >= 50
    w._alerts = [keep, fires]
    events = w._evaluate_alerts()
    assert len(events) == 1, "the price threshold fires once"
    by_id = {s.id: s for s in w._alerts}
    assert by_id[12].armed is False, "the fired spec is disarmed (matched by identity)"
    assert by_id[11].armed is True, "the unrelated spec is untouched"


# UI-widget guards can't run under the stub, so the tests below pin their source
def _src(rel: str) -> str:
    return (REPO / rel).read_text(encoding="utf-8")


def test_order_ticket_single_flight_guard_present():
    s = _src("mahad/ui/order_ticket.py")
    assert "if self._pending or self._done:" in s, "re-entry guard on _on_confirm"
    assert "def reject(self)" in s and "self._pending and not self._done" in s, \
        "close-while-pending guard"


def test_reset_dialog_single_flight_guard_present():
    s = _src("mahad/ui/reset_dialog.py")
    assert '_submitted' in s and "self._confirm.setEnabled(False)" in s, "single-flight guard present"


def test_settings_dialog_single_flight_guard_present():
    s = _src("mahad/ui/settings_dialog.py")
    assert '_applied' in s and "self._apply_btn.setEnabled(False)" in s, "single-flight guard present"


def test_alert_dialog_single_flight_guard_present():
    s = _src("mahad/ui/alert_dialog.py")
    assert '_arming' in s, "single-flight arm guard present"


def test_alert_delete_is_queued_not_direct():
    s = _src("mahad/ui/main_window.py")
    assert "_alert_remove = Signal(int)" in s, "queued alert-delete signal declared"
    assert "self._alert_remove.connect(self._worker.remove_alert)" in s, "connected before start"
    handler = s.split("def _on_alert_delete")[1].split("\n    def ")[0]
    assert "self._alert_remove.emit(alert_id)" in handler, "delete emits the queued intent"
    assert "self._worker.remove_alert" not in handler, \
        "the UI must not call the worker slot directly (single writer)"


def test_single_modal_guard_present():
    s = _src("mahad/ui/main_window.py")
    assert "self._modal_busy = True" in s and "self._modal_busy = False" in s, "modal flag set and reset"
    # 5 openers: New Alert / New Order / Reset / Help / Settings (About was removed)
    assert s.count("if self._modal_busy:") >= 5, "every dialog opener refuses a stacked open"


def test_timeframe_redundant_select_guarded():
    s = _src("mahad/ui/main_window.py")
    h = s.split("def _on_timeframe_changed")[1].split("\n    def ")[0]
    assert "if tf == self._timeframe:" in h, "a redundant re-select keeps the view"


def test_indicator_popover_keyboardtracking_off_and_debounced():
    s = _src("mahad/ui/indicator_popover.py")
    assert "setKeyboardTracking(False)" in s, "no per-digit storm"
    assert "_debounce" in s and "_flush_settings" in s, "burst coalescer present"


def test_watchlist_in_place_update_present():
    s = _src("mahad/ui/watchlist_panel.py")
    assert "def update_row(" in s, "in-place row update (no per-poll teardown)"


def test_chart_bounds_menu_disabled():
    s = _src("mahad/ui/chart_view.py")
    assert s.count("setMenuEnabled(False)") >= 2, "bounds-bypass menu disabled on both plots"


def test_closeevent_requests_interruption():
    s = _src("mahad/ui/main_window.py")
    assert "self._thread.requestInterruption()" in s, "prompt cooperative shutdown"
