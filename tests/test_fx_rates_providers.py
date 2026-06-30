"""Frankfurter/BoE adapters, the gap check, GBP display, the risk-CSV
round-trip, integrity assembly, and the methodology token cross-check.
UI surfaces are checked by source-guard, so this stays Qt-free.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import urllib.error
from pathlib import Path

import pytest

from mahad.data import context_sources as cs
from mahad.data.portfolio_view import (RiskAnalyticsView, StressRow,
                                       build_risk_snapshot_csv)
from mahad.engine import returns as R

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "providers"


def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# Frankfurter (the GBP view's rate)
# --------------------------------------------------------------------------- #
def test_fx_parses_the_reference_rate():
    body = (FIX / "frankfurter_gbp.json").read_text(encoding="utf-8")
    res = cs.fetch_gbp_rate(_get=lambda u, t: body)
    assert res.ok and res.data["rate"] == pytest.approx(0.7902)
    assert res.data["as_of"] == "2026-06-10"


def test_fx_accepts_a_provider_keyed_v2_shape():
    body = ('{"base": "USD", "date": "2026-06-10", '
            '"rates": {"GBP": {"ECB": 0.79}}}')
    res = cs.fetch_gbp_rate(_get=lambda u, t: body)
    assert res.ok and res.data["rate"] == pytest.approx(0.79)


@pytest.mark.parametrize("exc,kind", [
    (urllib.error.HTTPError("u", 503, "down", {}, None), "network"),
    (OSError("timed out"), "timeout"),
    (urllib.error.URLError("unreachable"), "network"),
])
def test_fx_failures_are_values(exc, kind):
    def _raise(u, t):
        raise exc
    res = cs.fetch_gbp_rate(_get=_raise)
    assert not res.ok and res.error.kind.value == kind


def test_fx_malformed_and_out_of_range_rates_rejected():
    assert not cs.fetch_gbp_rate(_get=lambda u, t: "{}").ok
    bad = '{"date": "2026-06-10", "rates": {"GBP": 250.0}}'
    assert not cs.fetch_gbp_rate(_get=lambda u, t: bad).ok


# --------------------------------------------------------------------------- #
# Bank of England IADB (SONIA + Bank Rate)
# --------------------------------------------------------------------------- #
def test_boe_parses_latest_per_series():
    body = (FIX / "boe_iadb.csv").read_text(encoding="utf-8")
    res = cs.fetch_boe_rates(_get=lambda u, t: body)
    assert res.ok
    assert res.data["sonia"] == pytest.approx(4.4518)      # the 10 Jun row
    assert res.data["sonia_as_of"] == "2026-06-10"
    assert res.data["bank_rate"] == pytest.approx(4.5000)  # ".." skipped
    assert res.data["bank_rate_as_of"] == "2026-06-09"
    assert res.data["as_of"] == "2026-06-10"


def test_boe_date_variants_parse():
    for cell in ("09 Jun 2026", "09/Jun/2026", "09-Jun-2026",
                 "09/06/2026", "2026-06-09"):
        assert cs._parse_boe_date(cell) == dt.date(2026, 6, 9), cell
    assert cs._parse_boe_date("junk") is None


def test_boe_failure_paths_are_values():
    def _raise(u, t):
        raise OSError("timed out")
    assert cs.fetch_boe_rates(_get=_raise).error.kind.value == "timeout"
    assert cs.fetch_boe_rates(_get=lambda u, t: "DATE\n").error.kind.value == "empty"
    headerless = "DATE,WRONG\n09 Jun 2026,1.0\n"
    assert cs.fetch_boe_rates(_get=lambda u, t: headerless).error.kind.value == "bad_data"


# --------------------------------------------------------------------------- #
# The gap check
# --------------------------------------------------------------------------- #
def test_missing_trading_days_vectors():
    mon, tue, wed = (dt.date(2026, 6, 8), dt.date(2026, 6, 9),
                     dt.date(2026, 6, 10))
    fri, next_mon = dt.date(2026, 6, 5), mon
    present, missing, first, last = R.missing_trading_days([mon, tue, wed])
    assert (present, missing) == (3, 0) and (first, last) == (mon, wed)
    # a missing Tuesday is a gap; the weekend between Fri and Mon is NOT
    present, missing, _f, _l = R.missing_trading_days([fri, next_mon, wed])
    assert missing == 1                                    # only Tue 9th
    # a full-day holiday never counts as missing (Jan 1 2026)
    present, missing, _f, _l = R.missing_trading_days(
        [dt.date(2025, 12, 31), dt.date(2026, 1, 2)])
    assert missing == 0
    assert R.missing_trading_days([]) == (0, 0, None, None)


# --------------------------------------------------------------------------- #
# The risk-snapshot CSV - golden round-trip
# --------------------------------------------------------------------------- #
def _view():
    return RiskAnalyticsView(
        available=True, n=250, window=250, as_of="2026-06-10",
        portfolio_value=99728.54, var95_pct=0.0193, var99_pct=0.0275,
        es975_pct=0.0250, pvar95_pct=0.0188, pvar99_pct=0.0265,
        backtest_mode="backcast", backtest_exceptions=2,
        backtest_observations=209, backtest_zone="green", kupiec_p=0.42,
        beta_spy=0.51, sharpe_annual=0.88, sortino_annual=1.10,
        rf_annual_pct=4.18, rf_as_of="2026-06-10", ewma_vol_pct=0.80,
        hhi=0.38, effective_n=2.63, dd_depth_pct=-1.26,
        stress=(StressRow("COVID crash", "2020-02-19", "2020-03-23",
                          -19995.0, 1.0, constant_legs=("BTC/USD",)),))


def test_risk_snapshot_csv_round_trips():
    text = build_risk_snapshot_csv(_view(), None, now_iso="2026-06-11")
    rows = list(csv.reader(io.StringIO(text)))
    header, body = rows[0], rows[1:]
    assert header == ["metric", "value", "units", "convention", "as_of"]
    by_metric = {r[0]: r for r in body}
    assert float(by_metric["var95_hist"][1]) == pytest.approx(0.0193)
    assert "m=floor((1-c)T)+1" in by_metric["var95_hist"][3]
    assert "FRTB 97.5" in by_metric["es975_hist"][3]
    assert by_metric["backtest_zone"][1] == "green"
    assert "mode backcast" in by_metric["backtest_zone"][3]
    assert "3M par yield" in by_metric["sharpe_annual"][3]
    assert "lambda 0.94" in by_metric["ewma_vol_daily"][3]
    assert "cash excluded" in by_metric["hhi"][3]
    assert float(by_metric["stress_COVID_crash"][1]) == pytest.approx(-19995.0)
    assert "constant legs: BTC/USD" in by_metric["stress_COVID_crash"][3]
    assert all(r[4] == "2026-06-10" or r[4] == "2026-06-11" for r in body)


def test_risk_snapshot_csv_includes_the_locked_basis_when_given():
    from mahad.data.portfolio_view import RiskView
    locked = RiskView(empty=False, warming=False, any_stale=False,
                      returns_skipped_stale=False, timeframe="1d",
                      exp_defined=True, exp_abs=None, exp_pct=0.5341,
                      exp_out_of_range=False, exp_rows=(), vol_defined=True,
                      vol_period_pct=1.42, vol_annual_pct=22.56, vol_n=30,
                      dd_defined=True, dd_pct=-3.42, dd_peak_ts=None,
                      dd_trough_ts=None, spark=(), spark_trough_idx=None)
    text = build_risk_snapshot_csv(_view(), locked, now_iso="2026-06-11")
    assert "exposure_pct" in text and "365-basis" in text
    assert "wall-clock convention" in text           # the locked label rides along


# --------------------------------------------------------------------------- #
# Source invariants: the GBP toggle, the tile, the popover, the chip
# --------------------------------------------------------------------------- #
def test_portfolio_gbp_view_is_display_only():
    src = _src("mahad/ui/portfolio_panel.py")
    assert "ledger remains USD" in src
    assert "ECB reference rate" in src
    assert "_render_gbp_line" in src
    # the ledger fields are never multiplied - only the display product
    assert "view.gbp_rate" in src and "cash * " not in src


def test_ukrates_tile_renders_with_per_series_as_of():
    src = _src("mahad/ui/risk_panel.py")
    assert '"ukrates", "UK RATES", TIP_CTX_UKRATES' in src.replace("\n", "")\
        .replace(" ", "") or "UK RATES" in src
    assert "SONIA as of" in src and "Bank Rate as of" in src
    assert "IUDSOIA" in src                          # the tooltip names the series


def test_integrity_popover_and_chip_wiring():
    src = _src("mahad/ui/main_window.py")
    assert "_toggle_integrity_popover" in src
    assert "DATA INTEGRITY" in src and "HISTORY GAP CHECK" in src
    assert "no gaps" in src
    src_w = _src("mahad/worker.py")
    assert "_build_integrity_view" in src_w
    assert "missing_trading_days" in src_w


def test_risk_csv_chip_uses_the_export_idiom():
    src = _src("mahad/ui/risk_panel.py")
    assert "export_risk_snapshot" in src
    assert "build_risk_snapshot_csv" in src
    assert "mahad-risk-snapshot.csv" in src
    assert "single-flight" in src.split("def export_risk_snapshot", 1)[1][:900]


def test_worker_fx_boe_round_trip_and_fresh_provider_rows(tmp_path, monkeypatch):
    # provider rows refresh every snapshot, but the gap scan is dirty-gated
    from tests._qt_stub import install as _install
    _install()
    import mahad.worker as worker_mod
    from mahad.worker import PollWorker
    from mahad.data.context_sources import ContextResult
    from mahad.data.source import SourceError, SourceErrorKind
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'fx.db'}")
    w._open_repo()
    w._load_portfolio()
    w._wallclock = lambda: 5000.0
    monkeypatch.setattr(worker_mod, "fetch_gbp_rate",
                        lambda *_a, **_k: ContextResult(
                            "fx", data={"rate": 0.7902, "as_of": "2026-06-10"}))
    monkeypatch.setattr(worker_mod, "fetch_boe_rates",
                        lambda *_a, **_k: ContextResult(
                            "boe", data={"sonia": 4.4518,
                                         "sonia_as_of": "2026-06-10",
                                         "bank_rate": 4.50,
                                         "bank_rate_as_of": "2026-06-09",
                                         "as_of": "2026-06-10"}))
    w._refresh_context("fx", 5000.0)
    w._refresh_context("boe", 5000.0)
    assert w._ctx_fx.available and w._ctx_fx.rate == 0.7902
    assert w._ctx_ukrates.sonia == 4.4518
    cached = w._repo.get_setting("market_context")
    assert cached["fx"]["rate"] == 0.7902               # persisted
    assert cached["ukrates"]["bank_rate"] == 4.50
    # restore on a fresh worker (offline tiles)
    w2 = PollWorker(symbol="AAPL", timeframe="1d",
                    db_url=f"sqlite:///{tmp_path / 'fx.db'}")
    w2._open_repo()
    monkeypatch.setattr(worker_mod, "read_env_key", lambda *a, **k: None)
    w2._load_context_cache()
    assert w2._ctx_fx.available and w2._ctx_fx.rate == 0.7902
    assert w2._ctx_ukrates.available and w2._ctx_ukrates.bank_rate == 4.50
    # the view carries the GBP inputs (+ a degraded note when set)
    view = w._build_portfolio_view()
    assert view.gbp_rate == 0.7902 and view.gbp_as_of == "2026-06-10"
    from dataclasses import replace as _replace
    w._ctx_fx = _replace(w._ctx_fx, note="refresh failed - showing 2026-06-10")
    assert "refresh failed" in w._build_portfolio_view().gbp_note
    # fresh provider rows on EVERY snapshot, gaps only on the rebuild
    w._note_provider("kraken", SourceError(SourceErrorKind.TIMEOUT, "slow"))
    now_view = w._integrity_now()
    states = {r.provider: r.state for r in now_view.providers}
    assert states["kraken"].startswith("retrying")
    assert now_view.gaps == w._integrity.gaps           # the scan untouched


def test_integrity_view_assembly_contents(tmp_path):
    import datetime as _dt
    from tests._qt_stub import install as _install
    _install()
    from mahad.worker import PollWorker
    from mahad.data.source import SourceError, SourceErrorKind
    w = PollWorker(symbol="AAPL", timeframe="1d",
                   db_url=f"sqlite:///{tmp_path / 'iv.db'}")
    w._open_repo()
    w._load_portfolio()
    w._wallclock = lambda: 7000.0
    w._note_provider("finnhub", None)
    w._note_provider("tiingo", SourceError(SourceErrorKind.NEEDS_KEY, "x"))
    mon, tue, thu = (_dt.date(2026, 6, 8), _dt.date(2026, 6, 9),
                     _dt.date(2026, 6, 11))
    w._asset_closes = {"AAPL": [(mon, 100.0), (tue, 101.0), (thu, 103.0)]}
    view = w._build_integrity_view()
    rows = {r.provider: r.state for r in view.providers}
    assert rows == {"finnhub": "ok", "tiingo": "needs a free key"}
    gap = view.gaps[0]
    assert gap.symbol == "AAPL"
    assert (gap.cached_days, gap.missing_days) == (3, 1)   # Wed 10th missing
    assert (gap.first, gap.last) == ("2026-06-08", "2026-06-11")


def test_methodology_tokens_cross_check_the_engine():
    rm_src = _src("mahad/engine/risk_metrics.py")
    ret_src = _src("mahad/engine/returns.py")
    for token in ("m = floor((1-c)T) + 1", "tail inclusive", "ddof",
                  "3.8415", "bcbs22", "sqrt(252)", "lambda 0.94", "1/HHI"):
        assert token in rm_src, token
    assert "annual_pct/100/252" in ret_src or "annual/252" in ret_src
