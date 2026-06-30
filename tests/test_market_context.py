# No network: adapters take an injected _get, fixtures are real captured payloads
# (Fear & Greed body captured live 2026-06-10; FRED shape carries real June 2026
# VIX closes; Treasury CSV carries documented header with real CMT magnitudes).
from __future__ import annotations

import json
import logging
import urllib.error
from pathlib import Path

from mahad.data import context_sources as cs
from mahad.data.context_view import classify_health
from mahad.data.portfolio_view import (VALUE_HISTORY_CSV_HEADER,
                                       build_value_history_csv)
from mahad.engine.context import curve_reading, spread_bp, vix_band

FIX = Path(__file__).parent / "fixtures" / "context"


def test_spread_bp_hand_checked_vectors():
    assert spread_bp(4.05, 4.40) == 35.0
    assert spread_bp(3.91, 4.43) == 52.0
    assert spread_bp(4.10, 3.80) == -30.0         # inversion is NEGATIVE
    assert spread_bp(4.00, 4.00) == 0.0
    assert spread_bp(None, 4.40) is None and spread_bp(4.05, None) is None


def test_curve_reading_bands():
    assert curve_reading(-0.1) == "inverted"
    assert curve_reading(0.0) == "flat"
    assert curve_reading(24.9) == "flat"
    assert curve_reading(25.0) == "normal"
    assert curve_reading(None) == ""


def test_vix_band_edges():
    assert vix_band(14.99) == "calm"
    assert vix_band(15.0) == "normal"
    assert vix_band(24.99) == "normal"
    assert vix_band(25.0) == "elevated"
    assert vix_band(35.0) == "extreme"
    assert vix_band(None) == ""


def _treasury_text() -> str:
    return (FIX / "treasury_sample.csv").read_text(encoding="utf-8")


def test_treasury_picks_the_latest_row_regardless_of_order():
    res = cs.fetch_treasury_yields(_get=lambda u, t: _treasury_text())
    assert res.ok
    assert res.data["as_of"] == "2026-06-09"
    assert res.data == {"as_of": "2026-06-09", "y3m": 4.18, "y2y": 4.05,
                        "y10y": 4.40, "y30y": 4.85}


def test_treasury_tolerates_na_cells_and_requires_the_spread_legs():
    text = ('Date,"3 Mo","2 Yr","10 Yr","30 Yr"\n'
            '06/09/2026,N/A,4.05,4.40,\n')
    res = cs.fetch_treasury_yields(_get=lambda u, t: text)
    assert res.ok and res.data["y3m"] is None and res.data["y30y"] is None
    missing_legs = ('Date,"3 Mo","2 Yr","10 Yr","30 Yr"\n'
                    '06/09/2026,4.18,,4.40,4.85\n')
    res2 = cs.fetch_treasury_yields(_get=lambda u, t: missing_legs)
    assert not res2.ok and res2.error.kind.value == "empty"


def test_treasury_year_fallback_for_an_empty_fresh_january():
    calls: list[str] = []

    def per_year(url: str, _t: float) -> str:
        calls.append(url)
        return _treasury_text() if "/2025/" in url else 'Date,"2 Yr","10 Yr"\n'

    res = cs.fetch_treasury_yields(year=2026, _get=per_year)
    assert res.ok and len(calls) == 2
    assert "/2026/" in calls[0] and "/2025/" in calls[1]


def test_treasury_failures_are_values_never_raises():
    def timeout(_u: str, _t: float) -> str:
        raise TimeoutError("timed out")

    res = cs.fetch_treasury_yields(_get=timeout)
    assert not res.ok and res.error.kind.value == "timeout"

    def http500(_u: str, _t: float) -> str:
        raise urllib.error.HTTPError(_u, 500, "boom", None, None)

    res2 = cs.fetch_treasury_yields(_get=http500)
    assert not res2.ok and res2.error.kind.value == "network"
    assert "HTTP 500" in res2.error.message


def test_fng_parses_the_live_captured_payload():
    body = (FIX / "fng_live_2026-06-10.json").read_text(encoding="utf-8")
    res = cs.fetch_fear_greed(_get=lambda u, t: body)
    assert res.ok
    assert res.data == {"value": 9, "as_of": "2026-06-10",
                        "classification": "Extreme Fear"}


def test_fng_url_keeps_the_trailing_slash():
    # bare /fng redirects and strips the query parameters, so the slash is load-bearing
    assert "/fng/?" in cs.FNG_URL


def test_fng_rejects_out_of_range_and_malformed():
    bad = json.dumps({"data": [{"value": "777", "value_classification": "x",
                                "timestamp": "1781049600"}]})
    assert not cs.fetch_fear_greed(_get=lambda u, t: bad).ok
    assert not cs.fetch_fear_greed(_get=lambda u, t: "not json").ok
    assert not cs.fetch_fear_greed(_get=lambda u, t: "{}").ok


def test_vix_parses_the_fred_shape_and_skips_missing_dots():
    body = (FIX / "fred_vixcls_shape.json").read_text(encoding="utf-8")
    res = cs.fetch_vix("k", _get=lambda u, t: body)
    assert res.ok
    # the "." observation (2026-06-03) is skipped; change = 15.40 - 16.06
    assert res.data == {"value": 15.40, "as_of": "2026-06-04", "change": -0.66}


def test_vix_requires_a_key_and_redacts_it_from_errors():
    assert not cs.fetch_vix("").ok

    def boom(_u: str, _t: float) -> str:
        raise OSError("connect to SECRETKEY.example timed out")

    res = cs.fetch_vix("SECRETKEY", _get=boom)
    assert not res.ok
    assert "SECRETKEY" not in str(res.error)
    assert "***" in res.error.message


def test_vix_key_lands_in_the_url_but_never_in_results():
    seen: list[str] = []
    body = (FIX / "fred_vixcls_shape.json").read_text(encoding="utf-8")

    def spy(url: str, _t: float) -> str:
        seen.append(url)
        return body

    res = cs.fetch_vix("TOPSECRET", _get=spy)
    assert res.ok and "TOPSECRET" in seen[0]
    assert "TOPSECRET" not in str(res.data)


def test_env_parser_handles_quotes_comments_and_export():
    text = ('# comment\n\nexport FRED_API_KEY="abc123"\nOTHER=\'q\'\nBAD\n')
    parsed = cs._parse_env_text(text)
    assert parsed["FRED_API_KEY"] == "abc123" and parsed["OTHER"] == "q"
    assert "BAD" not in parsed


def test_env_parser_inline_comment_template_form():
    # .env.example writes keys as `KEY= # where to get it`: blank+inline-comment
    # reads absent, embedded unquoted `#` survives, quotes keep the closing-quote run
    text = ("FINNHUB_API_KEY=   # free key: finnhub.io/register (email only)\n"
            "TIINGO_API_KEY=abc123 # free key: tiingo.com signup\n"
            "WEIRD=ab#cd\n"
            "QUOTED=\"se cret # not a comment\"\n")
    parsed = cs._parse_env_text(text)
    assert parsed["FINNHUB_API_KEY"] == ""
    assert parsed["TIINGO_API_KEY"] == "abc123"
    assert parsed["WEIRD"] == "ab#cd"
    assert parsed["QUOTED"] == "se cret # not a comment"


def test_read_env_key_blank_with_inline_comment_is_absent(tmp_path, monkeypatch):
    monkeypatch.delenv(cs.FRED_KEY_ENV, raising=False)
    envfile = tmp_path / ".env"
    envfile.write_text("FRED_API_KEY=   # free key: fred.stlouisfed.org\n",
                       encoding="utf-8")
    assert cs.read_env_key(paths=(envfile,)) is None


def test_read_env_key_file_then_environment(tmp_path, monkeypatch):
    monkeypatch.delenv(cs.FRED_KEY_ENV, raising=False)
    envfile = tmp_path / ".env"
    assert cs.read_env_key(paths=(envfile,)) is None
    envfile.write_text("FRED_API_KEY=fromfile\n", encoding="utf-8")
    assert cs.read_env_key(paths=(envfile,)) == "fromfile"
    monkeypatch.setenv(cs.FRED_KEY_ENV, "fromenv")
    assert cs.read_env_key(paths=(envfile,)) == "fromfile"    # file wins
    envfile.write_text("FRED_API_KEY=\n", encoding="utf-8")
    assert cs.read_env_key(paths=(envfile,)) == "fromenv"     # blank -> env


def test_read_env_key_never_logs_the_value(tmp_path, caplog):
    envfile = tmp_path / ".env"
    envfile.write_text("FRED_API_KEY=SUPERSECRETVALUE\n", encoding="utf-8")
    with caplog.at_level(logging.DEBUG):
        assert cs.read_env_key(paths=(envfile,)) == "SUPERSECRETVALUE"
    assert "SUPERSECRETVALUE" not in caplog.text


def test_classify_health_mapping():
    assert classify_health(None) == "ok"
    assert classify_health("network",
                           "urlopen error [Errno -2] Name or service not known"
                           ) == "offline"
    assert classify_health("network", "Tunnel connection failed: 403") == "offline"
    assert classify_health("network", "HTTP 429") == "retrying"
    assert classify_health("timeout", "timed out") == "retrying"
    assert classify_health("empty", "no usable mark") == "retrying"
    assert classify_health("invalid_key") == "needs_key"


def test_fetch_vix_invalid_key_is_invalid_key():
    from mahad.data.source import SourceErrorKind
    def boom(url, timeout):
        raise urllib.error.HTTPError(url, 401, "unauthorized", {}, None)
    res = cs.fetch_vix("BADKEY", _get=boom)
    assert not res.ok and res.error.kind == SourceErrorKind.INVALID_KEY
    assert "BADKEY" not in str(res.error.message)   # key must never leak into errors


def test_value_history_csv_round_trip():
    rows = ((1781049600.0, 100000.0, False), (1781136000.0, 100123.45, True))
    text = build_value_history_csv(rows)
    lines = text.strip().split("\n")
    assert lines[0] == VALUE_HISTORY_CSV_HEADER
    assert lines[1] == "2026-06-10T00:00:00+00:00,1781049600.000,100000.0,false"
    assert lines[2].endswith(",true") and "100123.45" in lines[2]
    assert text.endswith("\n")


def test_value_history_csv_empty_is_header_only():
    assert build_value_history_csv(()) == VALUE_HISTORY_CSV_HEADER + "\n"
