"""SQLi through the repository, JSON injection through the typed validators,
hostile CSV content, and the symbol-charset gate. Headless, tmp DBs only.
"""
from __future__ import annotations

import csv
import io
import json
from decimal import Decimal

import pytest
from sqlalchemy import text

from mahad.data.repository import MahadRepository
from mahad.data.symbols import normalize_symbol, validate_add
from mahad.engine.portfolio import TradeRecord, build_trade_csv
from mahad.engine.signals import canonical_params, validate_params

SQLI = [
    "AAPL'; DROP TABLE symbols;--",
    'X" OR "1"="1',
    "A); DELETE FROM watchlist;--",
    "B' UNION SELECT * FROM settings--",
    "С‘; PRAGMA writable_schema=ON;--",            # cyrillic lookalike + pragma
]


@pytest.fixture()
def repo(tmp_path):
    r = MahadRepository(f"sqlite:///{tmp_path / 'sec.db'}")
    yield r
    r.close()


def _tables(repo) -> set[str]:
    rows = repo._session.execute(
        text("SELECT name FROM sqlite_master WHERE type='table'")).scalars()
    return set(rows)


def test_sqli_symbols_stored_as_literals(repo):
    before = _tables(repo)
    for s in SQLI:
        repo.add(s, "stock", "USD", "finnhub")
    assert _tables(repo) == before                          # schema intact
    listed = {p.symbol for p in repo.list_watchlist()}
    for s in SQLI:
        assert s in listed
    for s in SQLI:
        repo.remove(s)
    assert _tables(repo) == before
    assert repo.list_watchlist() == []


def test_sqli_through_set_active_and_alerts(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    before = _tables(repo)
    repo.set_active(SQLI[0])                                # unknown symbol: no-op
    alert, reason = repo.add_alert(SQLI[0], "price_threshold", {"level": 1.0}, "up")
    assert alert is None
    assert _tables(repo) == before


def test_sqli_in_settings_values(repo):
    hostile = {"x": "'; DROP TABLE settings;--", "y": ["]];--", {"z": "qu'ote"}]}
    repo.set_setting("k", hostile)
    assert repo.get_setting("k") == json.loads(json.dumps(hostile))
    assert "settings" in _tables(repo)


def test_params_canonicalisation_defeats_smuggling():
    ok, params, _ = validate_params("price_threshold",
                                    {"level": "150.000000", "extra": "ignored",
                                     "__proto__": "x"})
    assert ok
    assert set(params) == {"level"}                          # whitelist, no passthrough
    assert canonical_params(params) == '{"level":150.0}'


@pytest.mark.parametrize("level", ["NaN", "Infinity", "-Infinity", "1e309"])
def test_params_reject_non_finite_tokens(level):
    ok, params, _ = validate_params("price_threshold", {"level": level})
    assert not ok and params is None


def test_params_nested_objects_rejected_or_coerced():
    ok, params, _ = validate_params("rsi_threshold",
                                    {"level": {"$gt": 0}, "rsi_period": [14]})
    assert not ok


def test_alert_params_round_trip_inert(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    ok, params, _ = validate_params("price_threshold", {"level": 123.45})
    alert, _ = repo.add_alert("AAPL", "price_threshold", params, "up")
    loaded = repo.list_alerts()[0]
    assert loaded.params == {"level": 123.45}


def _record(symbol: str) -> TradeRecord:
    one = Decimal("1")
    return TradeRecord(ts=1_700_000_000.0, symbol=symbol, side="buy", quantity=one,
                       fill_price=Decimal("10"), avg_cost_at_fill=Decimal("10"),
                       qty_before=Decimal("0"), qty_after=one,
                       realised_pnl=Decimal("0"))


def test_csv_hostile_symbols_are_data_only():
    hostile = ['=cmd|/c calc!A0', "+SUM(1)", "-2+3", "@evil", "../../x",
               'quo"te', "comma,comma", "new\nline"]
    out = build_trade_csv([_record(s) for s in hostile], "100000")
    rows = list(csv.reader(io.StringIO(out.split("\n", 1)[1])))
    _header, data = rows[0], rows[1:]
    assert len(data) == len(hostile)
    for s, row in zip(hostile, data):
        assert row[1] == s
    # formula-injection chars survive raw on purpose: the add-time charset gate
    # (test below) stops them ever reaching this path from the UI


def test_symbol_charset_gate_blocks_markup_and_traversal():
    # add-time charset (A-Z 0-9 . - and one / for pairs) is the only door symbols
    # enter by, so it has to shut out QLabel auto-rich-text and CSV formula injection
    bad = ["<b>AAPL</b>", "<img src=x>", "=2+2", "+SUM(A1)", "@cmd", "../../x",
           "AAPL;DROP", "A'B", 'A"B', "BTC//USDT", "/USDT", "BTC/", "A B"]
    for s in bad:
        out = validate_add(s, [])
        assert out.status == "rejected", f"{s!r} must be rejected at add-time"


def test_symbol_charset_gate_allows_real_tickers():
    good = ["AAPL", "BRK.B", "BTC/USD", "ETH/USD", "MSFT", "BT-A", "RDS.A"]
    for s in good:
        assert validate_add(s, []).ok, f"{s!r} must remain accepted"


def test_normalize_symbol_never_executes_anything():
    s = normalize_symbol("  btc/usdt‮  ")
    assert isinstance(s, str)
