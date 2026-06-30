# the context menu is pure UI, so we exercise the worker slot it calls
# (remove_alert) and the unread helper it feeds, not the menu itself
from __future__ import annotations

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad.data.symbols import unread_after_delete
from mahad.engine.signals import AlertSpec
from mahad.worker import PollWorker


def _worker(tmp_path) -> PollWorker:
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'a.db'}")
    w._open_repo()
    w._repo.add("AAPL", "stock", "USD", "finnhub")
    return w


def _arm(w, level: float):
    alert, _ = w._repo.add_alert("AAPL", "price_threshold", {"level": level}, "up")
    w._alerts.append(AlertSpec(id=alert.id, symbol="AAPL",
                               condition_type="price_threshold",
                               params={"level": level}, direction="up"))
    return alert.id


def test_remove_alert_deletes_from_db_and_memory(tmp_path):
    w = _worker(tmp_path)
    a1 = _arm(w, 10.0)
    a2 = _arm(w, 20.0)
    assert {s.id for s in w._alerts} == {a1, a2}
    w.remove_alert(a1)
    assert [s.id for s in w._alerts] == [a2]
    assert {a.id for a in w._repo.list_alerts()} == {a2}
    assert w.alerts_ready.emissions, "the alerts view is re-emitted after delete"
    w.stop()


def test_remove_fired_alert_keeps_others_one_shot(tmp_path):
    w = _worker(tmp_path)
    a1 = _arm(w, 10.0)
    a2 = _arm(w, 20.0)
    from dataclasses import replace
    w._repo.set_alert_state(a1, armed=False, fired_at=123.0)
    w._alerts = [replace(s, armed=False, fired_at=123.0) if s.id == a1 else s
                 for s in w._alerts]
    w.remove_alert(a1)
    remaining = w._repo.list_alerts()
    assert {a.id for a in remaining} == {a2}
    assert remaining[0].armed is True                         # deleting a fired one must not disarm the others
    w.stop()


def test_remove_alert_missing_id_is_safe(tmp_path):
    w = _worker(tmp_path)
    a1 = _arm(w, 10.0)
    w.remove_alert(999999)                                    # unknown id must not raise
    assert [s.id for s in w._alerts] == [a1]
    w.stop()


def test_unread_after_delete_decrements_only_unseen_fired():
    # deleting a fired alert off the Alerts tab clears one unseen fire
    assert unread_after_delete(3, fired=True, on_alerts_tab=False) == 2
    assert unread_after_delete(0, fired=True, on_alerts_tab=False) == 0
    assert unread_after_delete(3, fired=False, on_alerts_tab=False) == 3
    # on the Alerts tab the unread is already cleared, so don't double-decrement
    assert unread_after_delete(3, fired=True, on_alerts_tab=True) == 3
    assert unread_after_delete(1, fired=True, on_alerts_tab=False) == 0
