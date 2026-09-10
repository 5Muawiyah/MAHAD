# the headless risk report: read-only database access, engine-equal figures, the no-data paths
from __future__ import annotations

import csv
import subprocess
import sys
from pathlib import Path

import pytest

from mahad import config, report
from mahad.data.repository import CONTEXT_KEY, MahadRepository
from mahad.engine import returns as R
from mahad.engine import risk_metrics as rm
from mahad.engine.risk import ValueSample, max_drawdown, simple_returns, volatility
from tests._book import AAPL, MSFT, SAMPLES, SPY, seed

ROOT = Path(__file__).resolve().parents[1]


def _expected():
    # the same engine calls on the same inputs the report reads
    marks = {"AAPL": AAPL[-1].close, "MSFT": MSFT[-1].close}
    cash = 97000.0
    weights = R.current_weights([("AAPL", 10.0, marks["AAPL"]), ("MSFT", 5.0, marks["MSFT"])], cash)
    value = cash + 10.0 * marks["AAPL"] + 5.0 * marks["MSFT"]
    rets = {}
    for sym, bars in (("AAPL", AAPL), ("MSFT", MSFT), ("SPY", SPY)):
        rets[sym] = R.simple_returns_by_date(R.align_daily_closes((b.ts, b.adj_close) for b in bars))
    pr = R.portfolio_returns(weights, rets, config.RISK_WINDOW)
    return weights, value, rets, pr


def test_rows_equal_the_engine_on_the_same_inputs(tmp_path):
    path = tmp_path / "book.db"
    seed(path)
    repo = report.open_read_only(path)
    try:
        rows = report.build_rows(repo, confidence=0.95, window=config.RISK_WINDOW)
    finally:
        repo.close()
    by = {r.metric: r for r in rows}
    weights, value, rets, pr = _expected()
    r = list(pr.returns)
    assert by["portfolio_value"].value == value
    assert by["cash"].value == 97000.0
    assert by["observations"].value == pr.n and pr.n > 2
    assert by["var_hist"].value == rm.historical_var(r, 0.95).value
    assert by["var_hist_usd"].value == rm.historical_var(r, 0.95).value * value
    assert by["var99_hist"].value == rm.historical_var(r, 0.99).value
    assert by["es975_hist"].value == rm.expected_shortfall(r, 0.975).value
    assert by["var_parametric"].value == rm.parametric_var(r, 0.95)
    assert by["ewma_vol_daily"].value == rm.ewma_volatility(r) * 100.0
    rf_daily = R.rf_daily_from_annual_pct(5.25)
    assert by["sharpe_annual"].value == rm.sharpe(r, rf_daily).annualised
    assert by["sortino_annual"].value == rm.sortino(r).annualised
    bench = dict(rets["SPY"])
    paired = [(x, bench[d]) for d, x in zip(pr.dates, pr.returns, strict=False) if d in bench]
    assert by["beta_spy"].value == rm.beta([p for p, _ in paired], [b for _, b in paired])
    conc = rm.concentration({"AAPL": 10.0 * AAPL[-1].close, "MSFT": 5.0 * MSFT[-1].close},
                            {"AAPL": "Technology", "MSFT": "Technology"})
    assert by["hhi"].value == conc.hhi and by["effective_n"].value == conc.effective_n
    comp = rm.component_var(weights, pr.aligned, 0.95)
    assert by["component_var"].value == comp.portfolio_var
    assert by["contrib_AAPL"].value == next(c.pct for c in comp.contributions if c.symbol == "AAPL")
    samples = [ValueSample(ts=ts, value=v) for ts, v in SAMPLES]
    vol = volatility(simple_returns(samples)[0], "1d", window=config.VOLATILITY_WINDOW)
    assert by["volatility_period_pct"].value == vol.per_period_pct
    assert by["max_drawdown_pct"].value == max_drawdown(samples).max_dd_pct
    assert by["value_samples"].value == len(SAMPLES)
    # the confidence flag moves the VaR rows and nothing fixed
    repo = report.open_read_only(path)
    try:
        by99 = {x.metric: x for x in report.build_rows(repo, confidence=0.99, window=config.RISK_WINDOW)}
    finally:
        repo.close()
    assert by99["var_hist"].value == rm.historical_var(r, 0.99).value
    assert by99["es975_hist"].value == by["es975_hist"].value


def test_rows_say_when_data_is_missing(tmp_path):
    path = tmp_path / "book.db"
    seed(path)
    repo = MahadRepository(f"sqlite:///{path.as_posix()}")
    repo.set_setting(CONTEXT_KEY, {})                 # no cached Treasury yield
    repo.close()
    repo = report.open_read_only(path)
    try:
        by = {r.metric: r for r in report.build_rows(repo)}
    finally:
        repo.close()
    assert by["sharpe_annual"].value is None and "Treasury" in by["sharpe_annual"].note
    assert by["backtest_zone"].value is None and "no observations" in by["backtest_zone"].note
    assert by["stress_COVID_crash"].note.startswith("constant legs")


def test_csv_has_the_columns_and_the_summary_prints(tmp_path, capsys):
    path = tmp_path / "book.db"
    seed(path)
    out = tmp_path / "report.csv"
    assert report.main(["--db", str(path), "--out", str(out)]) == 0
    with out.open(encoding="utf-8", newline="") as fh:
        table = list(csv.reader(fh))
    assert table[0] == list(report.COLUMNS)
    by = {row[0]: row for row in table[1:]}
    _weights, value, _rets, pr = _expected()
    assert by["var_hist"][1] == f"{rm.historical_var(list(pr.returns), 0.95).value:.6f}"
    assert by["portfolio_value"][1] == f"{value:.6f}"
    assert by["sharpe_annual"][6] == ""                # a present figure carries no note
    assert all(len(row) == len(report.COLUMNS) for row in table)
    printed = capsys.readouterr().out
    assert "portfolio value" in printed and "one-day VaR" in printed


def test_no_data_gives_a_message_and_exit_one(tmp_path, capsys):
    missing = tmp_path / "missing.db"
    assert report.main(["--db", str(missing)]) == 1
    assert "no database" in capsys.readouterr().err
    assert not missing.exists()                        # read-only means never created
    empty = tmp_path / "empty.db"
    seed(empty, with_positions=False)
    assert report.main(["--db", str(empty), "--out", str(tmp_path / "x.csv")]) == 1
    assert "no positions" in capsys.readouterr().err
    with pytest.raises(SystemExit):
        report.main(["--db", str(empty), "--confidence", "1.5"])


def test_the_report_opens_a_path_holding_hash_and_percent(tmp_path):
    folder = tmp_path / "hash#1 pct%20x"
    folder.mkdir()
    path = folder / "book.db"
    seed(path)
    repo = report.open_read_only(path)
    try:
        assert report.build_rows(repo)[0].metric == "portfolio_value"
    finally:
        repo.close()


def test_the_report_opens_a_database_that_is_not_in_wal_mode(tmp_path):
    import sqlite3
    path = tmp_path / "book.db"
    seed(path)
    sqlite3.connect(path).execute("PRAGMA journal_mode=delete").close()   # a plain-journal copy
    repo = report.open_read_only(path)
    try:
        rows = report.build_rows(repo, confidence=0.95, window=config.RISK_WINDOW)
    finally:
        repo.close()
    assert {r.metric for r in rows} >= {"portfolio_value", "var_hist"}


def test_a_database_that_is_not_mahads_gives_a_plain_message(tmp_path):
    import sqlite3
    other = tmp_path / "other.db"
    con = sqlite3.connect(other)
    con.execute("CREATE TABLE unrelated (id INTEGER)")            # a table, but not the schema row
    con.close()
    with pytest.raises(report.ReportError) as exc:
        report.open_read_only(other)
    assert str(exc.value) == f"{other} is not a MAHAD database"

    empty = tmp_path / "empty.db"
    empty.write_bytes(b"")                                        # no tables at all
    with pytest.raises(report.ReportError) as exc:
        report.open_read_only(empty)
    assert str(exc.value) == f"{empty} is not a MAHAD database"


def test_the_report_connection_cannot_write(tmp_path):
    path = tmp_path / "book.db"
    seed(path)
    assert "mode=ro" in report.read_only_url(path)
    repo = report.open_read_only(path)
    try:
        with pytest.raises(Exception, match="readonly"):
            repo.set_setting("probe", 1)
    finally:
        repo.close()


def test_importing_the_report_pulls_in_no_qt():
    code = ("import sys, mahad.report; "
            "bad = [m for m in sys.modules if m.startswith(('PySide6', 'pyqtgraph'))]; "
            "sys.exit(1 if bad else 0)")
    proc = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    src = (ROOT / "mahad" / "report.py").read_text(encoding="utf-8")
    assert "PySide6" not in src and "pyqtgraph" not in src
