# market-context tiles, their cache, the health and data-integrity views
from __future__ import annotations

import logging
from dataclasses import replace
from typing import Mapping, Optional

from mahad import config
from mahad.data.context_sources import (fetch_boe_rates, fetch_fear_greed, fetch_gbp_rate,
                                        fetch_treasury_yields, fetch_vix, read_env_key)
from mahad.data.context_view import (DataIntegrityView, FxRateView, GapRow, HealthView,
                                     IntegrityRow, MarketContextView, SentimentTile, UkRatesTile,
                                     VixTile, YieldCurveTile, classify_health)
from mahad.data.repository import CONTEXT_KEY
from mahad.data.source import SourceErrorKind
from mahad.engine import returns as eng_returns
from mahad.engine.context import curve_reading, spread_bp, vix_band
from mahad.worker.state import WorkerState

log = logging.getLogger("mahad.worker")


class ContextMixin(WorkerState):
    def _load_context_cache(self) -> None:
        # restore cached tiles and stagger the first fetches so they don't all fire at once
        try:
            self._ctx_has_key = bool(read_env_key())
        except Exception:                              # loader never raises
            log.exception("env key check failed; treating as keyless")
            self._ctx_has_key = False
        cached = self._get_setting(CONTEXT_KEY)
        if isinstance(cached, dict):
            try:
                y = cached.get("yields")
                if isinstance(y, dict) and y.get("y10y") is not None:
                    self._ctx_yields = self._yields_tile(y, y.get("fetched_ts"))
                f = cached.get("sentiment")
                if isinstance(f, dict) and f.get("value") is not None:
                    self._ctx_sentiment = self._sentiment_tile(f, f.get("fetched_ts"))
                v = cached.get("vix")
                if (isinstance(v, dict) and v.get("value") is not None
                        and self._ctx_has_key):
                    self._ctx_vix = self._vix_tile(v, v.get("fetched_ts"))
            except Exception:
                log.exception("context cache restore failed; starting empty")
        if isinstance(cached, dict):
            try:
                u = cached.get("ukrates")
                if isinstance(u, dict) and (u.get("sonia") is not None
                                            or u.get("bank_rate") is not None):
                    self._ctx_ukrates = self._ukrates_tile(u, u.get("fetched_ts"))
                fxd = cached.get("fx")
                if isinstance(fxd, dict) and fxd.get("rate") is not None:
                    self._ctx_fx = self._fx_view(fxd, fxd.get("fetched_ts"))
            except Exception:
                log.exception("context cache restore failed; starting empty")
        if not self._ctx_has_key:
            self._ctx_vix = VixTile(needs_key=True, note="needs a free FRED key")
        now = self._wallclock()
        self._ctx_due = {"treasury": now + 4.0, "fng": now + 6.0, "vix": now + 8.0,
                         "boe": now + 10.0, "fx": now + 12.0}

    @staticmethod
    def _yields_tile(data: Mapping[str, object], fetched_ts: Optional[float] = None,
                     note: str = "") -> YieldCurveTile:
        def _f(key: str) -> Optional[float]:
            val = data.get(key)
            try:
                return None if val is None else float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
        sp = spread_bp(_f("y2y"), _f("y10y"))
        return YieldCurveTile(available=True, as_of=str(data.get("as_of") or ""),
                              fetched_ts=fetched_ts, y3m=_f("y3m"), y2y=_f("y2y"),
                              y10y=_f("y10y"), y30y=_f("y30y"), spread_bp=sp,
                              reading=curve_reading(sp), note=note)

    @staticmethod
    def _sentiment_tile(data: Mapping[str, object], fetched_ts: Optional[float] = None,
                        note: str = "") -> SentimentTile:
        try:
            value = int(data.get("value"))  # type: ignore[call-overload] # guarded by caller
        except (TypeError, ValueError):
            value = None
        return SentimentTile(available=(value is not None),
                             as_of=str(data.get("as_of") or ""), fetched_ts=fetched_ts,
                             value=value,
                             classification=str(data.get("classification") or ""),
                             note=note)

    @staticmethod
    def _vix_tile(data: Mapping[str, object], fetched_ts: Optional[float] = None,
                  note: str = "") -> VixTile:
        try:
            value = float(data.get("value"))  # type: ignore[arg-type] # guarded by caller
        except (TypeError, ValueError):
            value = None
        change = data.get("change")
        try:
            change = None if change is None else float(change)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            change = None
        return VixTile(available=(value is not None), needs_key=False,
                       as_of=str(data.get("as_of") or ""), fetched_ts=fetched_ts,
                       value=value, change=change, band=vix_band(value), note=note)

    @staticmethod
    def _ukrates_tile(data: Mapping[str, object], fetched_ts: Optional[float] = None,
                      note: str = "") -> UkRatesTile:
        def _f(key: str) -> Optional[float]:
            val = data.get(key)
            try:
                return None if val is None else float(val)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return None
        sonia, bank = _f("sonia"), _f("bank_rate")
        return UkRatesTile(available=(sonia is not None or bank is not None),
                           as_of=str(data.get("as_of") or ""),
                           fetched_ts=fetched_ts, sonia=sonia,
                           sonia_as_of=str(data.get("sonia_as_of") or ""),
                           bank_rate=bank,
                           bank_rate_as_of=str(data.get("bank_rate_as_of") or ""),
                           note=note)

    @staticmethod
    def _fx_view(data: Mapping[str, object], fetched_ts: Optional[float] = None,
                 note: str = "") -> FxRateView:
        try:
            rate = float(data.get("rate"))         # type: ignore[arg-type]
        except (TypeError, ValueError):
            rate = None
        return FxRateView(available=(rate is not None), rate=rate,
                          as_of=str(data.get("as_of") or ""),
                          fetched_ts=fetched_ts, note=note)

    def _refresh_context_if_due(self, now: float) -> bool:
        # one context refresh per tick at most; True when one ran
        for kind in ("treasury", "fng", "vix", "boe", "fx"):
            if now >= self._ctx_due.get(kind, float("inf")):
                self._refresh_context(kind, now)
                return True
        return False

    @staticmethod
    def _fail_note(tile: YieldCurveTile | SentimentTile | VixTile | UkRatesTile | FxRateView) -> str:
        if tile.available and tile.as_of:
            return f"refresh failed - showing {tile.as_of}"
        return "unavailable - retrying"

    def _refresh_context(self, kind: str, now: float) -> None:
        ok = False
        try:
            if kind == "treasury":
                res = fetch_treasury_yields(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_yields = self._yields_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (treasury): %s", res.error)
                    self._ctx_yields = replace(self._ctx_yields,
                                               note=self._fail_note(self._ctx_yields))
            elif kind == "fng":
                res = fetch_fear_greed(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_sentiment = self._sentiment_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (fng): %s", res.error)
                    self._ctx_sentiment = replace(self._ctx_sentiment,
                                                  note=self._fail_note(self._ctx_sentiment))
            elif kind == "boe":  # keyless
                res = fetch_boe_rates(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_ukrates = self._ukrates_tile(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (boe): %s", res.error)
                    self._ctx_ukrates = replace(self._ctx_ukrates,
                                                note=self._fail_note(self._ctx_ukrates))
            elif kind == "fx":  # keyless
                res = fetch_gbp_rate(config.CONTEXT_TIMEOUT_S)
                if res.ok:
                    self._ctx_fx = self._fx_view(res.data, fetched_ts=now)
                    ok = True
                else:
                    log.warning("context fetch failed (fx): %s", res.error)
                    self._ctx_fx = replace(self._ctx_fx,
                                           note=self._fail_note(self._ctx_fx))
            elif kind == "vix":
                try:
                    key = read_env_key()
                except Exception:
                    key = None
                self._ctx_has_key = bool(key)
                if not key:                            # the designed keyless state
                    self._ctx_vix = VixTile(needs_key=True,
                                            note="needs a free FRED key")
                else:
                    res = fetch_vix(key, config.CONTEXT_TIMEOUT_S)
                    if res.ok:
                        self._ctx_vix = self._vix_tile(res.data, fetched_ts=now)
                        ok = True
                    else:
                        log.warning("context fetch failed (vix): %s", res.error)
                        note = (config.INVALID_KEY_VIX_MSG
                                if res.error is not None
                                and res.error.kind == SourceErrorKind.INVALID_KEY
                                else self._fail_note(self._ctx_vix))
                        self._ctx_vix = replace(self._ctx_vix, note=note)
        except Exception:                              # structural never-raise
            log.exception("context refresh failed (%s)", kind)
        self._ctx_due[kind] = now + (config.CONTEXT_REFRESH_S if ok
                                     else config.CONTEXT_RETRY_S)
        if ok:
            self._persist_context_cache()
        self._emit_snapshot(None)

    def _persist_context_cache(self) -> None:
        try:
            payload: dict[str, dict[str, object]] = {}
            y = self._ctx_yields
            if y.available:
                payload["yields"] = {"as_of": y.as_of, "fetched_ts": y.fetched_ts,
                                     "y3m": y.y3m, "y2y": y.y2y,
                                     "y10y": y.y10y, "y30y": y.y30y}
            f = self._ctx_sentiment
            if f.available:
                payload["sentiment"] = {"as_of": f.as_of, "fetched_ts": f.fetched_ts,
                                        "value": f.value,
                                        "classification": f.classification}
            v = self._ctx_vix
            if v.available:
                payload["vix"] = {"as_of": v.as_of, "fetched_ts": v.fetched_ts,
                                  "value": v.value, "change": v.change}
            u = self._ctx_ukrates
            if u.available:
                payload["ukrates"] = {"as_of": u.as_of, "fetched_ts": u.fetched_ts,
                                      "sonia": u.sonia,
                                      "sonia_as_of": u.sonia_as_of,
                                      "bank_rate": u.bank_rate,
                                      "bank_rate_as_of": u.bank_rate_as_of}
            x = self._ctx_fx
            if x.available:
                payload["fx"] = {"rate": x.rate, "as_of": x.as_of,
                                 "fetched_ts": x.fetched_ts}
            self._set_setting(CONTEXT_KEY, payload)
        except Exception:
            log.exception("context cache persist failed; tiles stay in-memory")

    def _build_context_view(self) -> MarketContextView:
        y, v, f = self._ctx_yields, self._ctx_vix, self._ctx_sentiment
        parts = []
        parts.append(f"10Y {y.y10y:.2f}" if (y.available and y.y10y is not None)
                     else "10Y -")
        if v.needs_key:
            parts.append("VIX needs key")
        else:
            parts.append(f"VIX {v.value:.1f}" if (v.available and v.value is not None)
                         else "VIX -")
        parts.append(f"F&G {f.value}" if (f.available and f.value is not None)
                     else "F&G -")
        return MarketContextView(yields=y, sentiment=f, vix=v,
                                 ukrates=self._ctx_ukrates,
                                 summary=" · ".join(parts))

    def _build_health_view(self) -> HealthView:
        providers = self._provider_lines()
        if self._last_error is None:
            return HealthView(state="ok", reason="data ok", providers=providers)
        kind, msg, since = self._last_error
        state = classify_health(kind, msg)
        if kind == "invalid_key":
            reason = "key rejected - check it"
        elif state == "needs_key":
            reason = "needs a free key"
        elif state == "offline":
            reason = "offline - retrying"
        else:
            reason = f"retrying - {kind}"
        return HealthView(state=state, reason=reason, detail=str(msg),
                          since_ts=since, providers=providers)

    def _provider_integrity_rows(self) -> list[IntegrityRow]:
        rows = []
        for name, state in self._provider_lines():
            err = self._provider_errors.get(name)
            detail, since = "", None
            if isinstance(err, tuple):
                _kind, detail, since = err
            rows.append(IntegrityRow(provider=name, state=state,
                                     detail=str(detail), since_ts=since))
        return rows

    def _integrity_now(self) -> DataIntegrityView:
        # provider rows are recomputed each snapshot; gaps reuse the last rebuild
        providers = self._provider_integrity_rows()
        return DataIntegrityView(providers=tuple(providers),
                                 gaps=self._integrity.gaps,
                                 checked_ts=self._integrity.checked_ts)

    def _build_integrity_view(self) -> DataIntegrityView:
        # provider state plus a daily-history gap check against the NYSE calendar
        providers = self._provider_integrity_rows()
        gaps = []
        try:
            for sym in sorted(self._asset_closes):
                dates = [d for d, _ in self._asset_closes[sym]]
                present, missing, first, last = \
                    eng_returns.missing_trading_days(dates)
                gaps.append(GapRow(symbol=sym, cached_days=present,
                                   missing_days=missing,
                                   first=(first.isoformat() if first else ""),
                                   last=(last.isoformat() if last else "")))
        except Exception:
            log.exception("gap check failed")
        return DataIntegrityView(providers=tuple(providers), gaps=tuple(gaps),
                                 checked_ts=self._wallclock())
