# alert evaluation, arming and the alerts view
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Optional, cast

from PySide6.QtCore import Slot

from mahad import config
from mahad.data.repository import ALERT_CAP, PersistedAlert
from mahad.data.symbols import AlertRowView, AlertsView
from mahad.engine.signals import AlertEvent, AlertRule, evaluate_alert, summary, validate_params
from mahad.worker.state import WorkerState

log = logging.getLogger("mahad.worker")


class AlertsMixin(WorkerState):
    def _evaluate_alerts(self) -> list[AlertEvent]:
        active = self._symbol
        quote = self._last_quote
        if active is None:
            self._alerts_paused = False
            return []
        if (quote is None or quote.stale or
                config.is_stale(quote.ts, poll_interval_s=self._poll_interval_s)):
            self._alerts_paused = True                             # "alerts paused"
            return []
        self._alerts_paused = False

        closed = [c for c in self._candles if c.is_closed]
        closed_closes = [c.close for c in closed]
        closed_ts = [c.ts for c in closed]
        mark = quote.mark
        if self._last_closed_ts is None:                          # baseline: no replay
            new_indices: list[int] = []
        else:
            new_indices = [i for i, t in enumerate(closed_ts) if t > self._last_closed_ts]

        now = self._wallclock()
        events: list[AlertEvent] = []
        for rule in list(self._alerts):                  # a copy, since the loop writes entries back by index
            if rule.symbol != active or not rule.armed:
                continue
            try:
                ev, new_rule = evaluate_alert(
                    rule, closed_closes=closed_closes, closed_ts=closed_ts, mark=mark,
                    timeframe=self._timeframe, new_indices=new_indices, now=now)
            except Exception:                                     # never crash on eval
                log.exception("alert eval failed (%s)", rule.condition_type)
                continue
            if ev is None:
                continue
            try:                                                  # persist before mutate
                if self._repo is not None and rule.id is not None:
                    self._repo.set_alert_state(rule.id, armed=False,
                                               fired_at=new_rule.fired_at)
            except Exception:
                log.exception("persist alert fire failed; keeping armed")
                continue                                          # no desync, drop the event
            for _j, _cur in enumerate(self._alerts):      # apply by identity (idx may be stale)
                if _cur is rule:
                    self._alerts[_j] = new_rule
                    break
            events.append(ev)

        if closed_ts:
            self._last_closed_ts = max(closed_ts)
        return events

    def _emit_alerts(self) -> None:
        active = self._symbol
        rows = tuple(
            AlertRowView(id=rule.id if rule.id is not None else -1, symbol=rule.symbol,
                         condition_type=rule.condition_type, direction=rule.direction,
                         summary=summary(rule), armed=rule.armed, fired_at=rule.fired_at,
                         not_active=(rule.symbol != active))
            for rule in self._alerts)
        self.alerts_ready.emit(AlertsView(rows=rows, paused=self._alerts_paused,
                                          active_symbol=active, count=len(rows),
                                          cap=ALERT_CAP))

    @Slot(object)
    def arm_alert(self, payload: object) -> None:
        if not isinstance(payload, dict) or self._repo is None or self._stop:
            return
        active = self._symbol
        if not active:
            self.alert_rejected.emit("add a symbol to the watchlist first")
            return
        condition_type = str(payload.get("condition_type") or "")
        direction = payload.get("direction")
        ok, params, reason = validate_params(condition_type,
                                             cast("Optional[dict[str, object]]",
                                                  payload.get("params")))
        if not ok:
            self.alert_rejected.emit(reason or "invalid parameters")
            return
        if direction not in ("up", "down"):
            self.alert_rejected.emit("choose a direction")
            return
        try:
            alert, reason = self._repo.add_alert(  # type: ignore[union-attr] # repo seam guarded by the except boundary
                active, condition_type,
                cast("dict[str, object]", params), direction)
        except Exception:
            log.exception("arm_alert failed")
            self.alert_rejected.emit("could not save - please retry")
            return
        if alert is None:
            self.alert_rejected.emit(reason)
            return
        self._alerts.append(self._rule_from_row(alert))
        self._emit_alerts()

    @Slot(int)
    def disarm_alert(self, alert_id: int) -> None:
        self._set_alert_state(alert_id, armed=False, fired_at=None)

    @Slot(int)
    def rearm_alert(self, alert_id: int) -> None:
        self._set_alert_state(alert_id, armed=True, fired_at=None)

    @Slot(int)
    def remove_alert(self, alert_id: int) -> None:
        if self._repo is not None:
            try:
                self._repo.remove_alert(alert_id)
            except Exception:
                log.exception("remove_alert failed")
                self.alert_rejected.emit("could not delete - please retry")
                return                                # no desync: the row is still on disk
        self._alerts = [s for s in self._alerts if s.id != alert_id]
        self._emit_alerts()

    def _load_alerts(self) -> None:
        try:
            rows = self._repo.list_alerts() if self._repo is not None else []
            self._alerts = [self._rule_from_row(r) for r in rows]
        except Exception:
            log.exception("alert load failed; continuing with no alerts")
            self._alerts = []

    @staticmethod
    def _rule_from_row(row: PersistedAlert) -> AlertRule:
        return AlertRule(id=row.id, symbol=row.symbol, condition_type=row.condition_type,
                         params=dict(row.params), direction=row.direction,
                         armed=row.armed, fired_at=row.fired_at)

    def _set_alert_state(self, alert_id: int, armed: bool,
                         fired_at: Optional[float]) -> None:
        if self._repo is not None:
            try:
                self._repo.set_alert_state(alert_id, armed=armed, fired_at=fired_at)
            except Exception:
                log.exception("set_alert_state failed")
                return
        self._alerts = [replace(s, armed=armed, fired_at=fired_at) if s.id == alert_id
                        else s for s in self._alerts]
        self._emit_alerts()
