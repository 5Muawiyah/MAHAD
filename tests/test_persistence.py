# repository tests run on in-memory SQLite so CI never touches a file
from __future__ import annotations

import pytest

from mahad.data.repository import (INDICATORS_KEY, MahadRepository, SchemaVersion)
from mahad.data.symbols import (USD_REJECT_MSG, WatchlistRow, classify,
                                is_usd_quoted, normalize_symbol, validate_add)
from mahad.engine.indicators import IndicatorSettings


# --------------------------------------------------------------------------- #
# Pure symbol logic
# --------------------------------------------------------------------------- #
def test_normalize_and_classify():
    assert normalize_symbol("  aapl ") == "AAPL"
    assert normalize_symbol(" btc/usd ") == "BTC/USD"
    assert classify("AAPL") == ("stock", "USD")
    assert classify("BTC/USD") == ("crypto", "USD")
    assert classify("BTC/USDT") == ("crypto", "USDT")    # mechanical split


def test_usd_quoted_rules():
    assert is_usd_quoted("AAPL") is True                 # US equity
    assert is_usd_quoted("BTC/USDT") is False    # the proxy retired
    assert is_usd_quoted("ETH/USDC") is False
    assert is_usd_quoted("BTC/USD") is True       # native USD only
    assert is_usd_quoted("ETH/USD") is True
    assert is_usd_quoted("BTC/EUR") is False             # non-USD -> rejected
    assert is_usd_quoted("BTC/GBP") is False


def test_validate_add_outcomes():
    assert validate_add("aapl", []).status == "ok"
    assert validate_add("aapl", []).symbol == "AAPL"
    assert validate_add("BTC/USD", []).asset_class == "crypto"

    rej = validate_add("BTC/EUR", [])
    assert rej.status == "rejected" and rej.reason == USD_REJECT_MSG

    assert validate_add("", []).status == "rejected"
    assert validate_add("AAPL", ["AAPL"]).status == "duplicate"
    assert validate_add("aapl", ["AAPL"]).status == "duplicate"   # case-insensitive dupe

    full = [str(i) for i in range(20)]
    assert validate_add("AAPL", full).status == "rejected"        # soft cap 20
    assert validate_add("AAPL", full, cap=25).status == "ok"      # higher cap ok


def test_watchlist_row_dot_states():
    assert WatchlistRow("AAPL", "stock").dot == "warm"            # no quote yet
    assert WatchlistRow("AAPL", "stock", has_quote=True).dot == "live"
    assert WatchlistRow("AAPL", "stock", has_quote=True, stale=True).dot == "stale"


# --------------------------------------------------------------------------- #
# Repository (in-memory SQLite)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def repo():
    r = MahadRepository("sqlite:///:memory:")
    yield r
    r.close()


def test_schema_version_row_created(repo):
    assert repo._session.get(SchemaVersion, 1).version == 1


def test_seed_default_watchlist_first_is_active(repo):
    assert repo.seed_if_empty(("AAPL", "BTC/USD"), "kraken") is True
    assert repo.watchlist_symbols() == ["AAPL", "BTC/USD"]
    assert repo.active_symbol() == "AAPL"
    assert repo.seed_if_empty(("X",), "kraken") is False         # no double-seed


def test_add_is_idempotent(repo):
    assert repo.add("AAPL", "stock", "USD", "finnhub") is True
    assert repo.add("AAPL", "stock", "USD", "finnhub") is False  # dupe -> no new row
    assert repo.watchlist_symbols() == ["AAPL"]
    assert repo.active_symbol() == "AAPL"                         # first -> active


def test_set_active_switches_exactly_one(repo):
    repo.seed_if_empty(("AAPL", "BTC/USD"), "kraken")
    assert repo.set_active("BTC/USD") == "BTC/USD"
    assert repo.active_symbol() == "BTC/USD"
    actives = [p.symbol for p in repo.list_watchlist() if p.active]
    assert actives == ["BTC/USD"]                               # exactly one active


def test_remove_active_falls_back_to_next(repo):
    repo.seed_if_empty(("AAPL", "BTC/USD"), "kraken")           # AAPL active
    assert repo.remove("AAPL") == "BTC/USD"                     # falls back to next
    assert repo.watchlist_symbols() == ["BTC/USD"]
    assert repo.active_symbol() == "BTC/USD"


def test_remove_last_symbol_empties_and_clears_active(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    assert repo.remove("AAPL") is None                           # empty -> no active
    assert repo.watchlist_symbols() == []
    assert repo.active_symbol() is None


def test_remove_non_active_keeps_active(repo):
    repo.seed_if_empty(("AAPL", "BTC/USD"), "kraken")           # AAPL active
    assert repo.remove("BTC/USD") == "AAPL"                     # active unchanged
    assert repo.active_symbol() == "AAPL"


def test_indicator_settings_roundtrip_and_defensive(repo):
    s = IndicatorSettings(sma_enabled=True, ema_enabled=True, rsi_period=21)
    repo.set_setting(INDICATORS_KEY, s.to_dict())
    assert IndicatorSettings.from_dict(repo.get_setting(INDICATORS_KEY)) == s
    assert repo.get_setting("never-set") is None                 # missing -> None
    # a missing settings row degrades to committed defaults, never crashes
    assert IndicatorSettings.from_dict(repo.get_setting("never-set")) == IndicatorSettings()


# --------------------------------------------------------------------------- #
# Alert persistence - cap 20, identical-duplicate, one-shot state
# --------------------------------------------------------------------------- #
from mahad.engine.signals import PRICE_THRESHOLD, UP, validate_params  # noqa: E402


def _armed_level(level):
    # canonicalise through the engine so tests see the same params the worker stores
    ok, params, _ = validate_params(PRICE_THRESHOLD, {"level": level})
    assert ok
    return params


def test_add_alert_persists_and_lists(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    alert, reason = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150), UP)
    assert reason == "" and alert is not None and alert.id is not None
    rows = repo.list_alerts()
    assert len(rows) == 1
    assert rows[0].symbol == "AAPL" and rows[0].armed is True
    assert rows[0].params == {"level": 150.0} and rows[0].fired_at is None


def test_add_alert_requires_a_watchlist_symbol(repo):
    alert, reason = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150), UP)
    assert alert is None and "add a symbol" in reason          # no polled symbol


def test_add_alert_identical_duplicate_blocked_incl_150_vs_150_0(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    a1, _ = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150), UP)      # 150 (int)
    assert a1 is not None
    a2, reason = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150.0), UP)  # 150.0
    assert a2 is None and "identical" in reason                # canonical form collides
    assert repo.count_alerts() == 1


def test_add_alert_cap_20(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    for i in range(20):                                        # 20 distinct alerts fill the cap
        a, _ = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(100 + i), UP)
        assert a is not None
    assert repo.count_alerts() == 20
    blocked, reason = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(999), UP)
    assert blocked is None and "capped at 20" in reason        # cap


def test_set_alert_state_fire_then_rearm_roundtrip(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    alert, _ = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150), UP)
    assert repo.set_alert_state(alert.id, armed=False, fired_at=1234.5) is True   # fire
    fired = repo.list_alerts()[0]
    assert fired.armed is False and fired.fired_at == 1234.5
    assert repo.set_alert_state(alert.id, armed=True, fired_at=None) is True       # re-arm
    rearmed = repo.list_alerts()[0]
    assert rearmed.armed is True and rearmed.fired_at is None
    assert repo.set_alert_state(99999, armed=True, fired_at=None) is False         # gone


def test_remove_alert_and_cascade_on_symbol_removal(repo):
    repo.add("AAPL", "stock", "USD", "finnhub")
    repo.add("BTC/USD", "crypto", "USD", "kraken")
    a, _ = repo.add_alert("AAPL", PRICE_THRESHOLD, _armed_level(150), UP)
    b, _ = repo.add_alert("BTC/USD", PRICE_THRESHOLD, _armed_level(70000), UP)
    assert repo.remove_alert(a.id) is True                     # explicit remove
    assert repo.count_alerts() == 1
    repo.remove("BTC/USD")                                    # removing the symbol cascades
    assert repo.count_alerts() == 0                            # FK ON DELETE CASCADE


def test_alerts_table_added_to_existing_db_without_data_loss(tmp_path):
    # opening a pre-alerts DB should just create the table, not bump schema or rebuild
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session as SASession

    from mahad.data.repository import (SCHEMA_VERSION, Base, SchemaVersion, Symbol,
                                       WatchlistEntry)
    url = f"sqlite:///{(tmp_path / 'mahad.db').as_posix()}"
    eng = create_engine(url, future=True)
    base_tables = [t for n, t in Base.metadata.tables.items() if n != "alerts"]
    Base.metadata.create_all(eng, tables=base_tables)
    assert "alerts" not in inspect(eng).get_table_names()  # genuinely pre-alerts
    with SASession(eng, future=True) as s:
        s.add(SchemaVersion(id=1, version=SCHEMA_VERSION))
        sym = Symbol(ticker="AAPL", asset_class="stock", provider="finnhub",
                     quote_currency="USD", display_name="AAPL", active=True, created_at=1.0)
        s.add(sym)
        s.flush()
        s.add(WatchlistEntry(symbol_id=sym.id, added_at=1.0))
        s.commit()
    eng.dispose()

    repo = MahadRepository(url)
    try:
        assert "alerts" in inspect(repo._engine).get_table_names()   # additive table created
        assert repo.watchlist_symbols() == ["AAPL"]                  # watchlist intact
        assert repo.active_symbol() == "AAPL"
        assert repo.count_alerts() == 0                              # empty + queryable
        assert repo._session.get(SchemaVersion, 1).version == 1     # no bump
    finally:
        repo.close()


# ============================================================================ #
# paper-trade persistence (Portfolio / Position / Trade; DecimalText) #
# ============================================================================ #
from decimal import Decimal as _Dec                                  # noqa: E402
from mahad.data.repository import (MahadRepository as _Repo,         # noqa: E402
                                   PersistedTrade as _PT)


def _repo4():
    r = _Repo("sqlite:///:memory:")
    r.add("AAPL", "stock", "USD", "finnhub")
    r.load_or_create_portfolio("100000")          # worker creates this on start
    return r


def test_decimaltext_roundtrips_exact_decimal():
    # we store the ledger as TEXT because SQLAlchemy Numeric is float-lossy on SQLite
    r = _repo4()
    exact = _Dec("100.66666666666666666666666667")
    r.record_fill(cash=_Dec("1.00"), realised_pnl=_Dec("0"), symbol="AAPL",
                  new_quantity=_Dec("3"), new_avg_cost=exact,
                  trade=_PT(1.0, "AAPL", "buy", _Dec("3"), _Dec("0.005"), exact,
                            _Dec("0"), _Dec("3"), _Dec("0.00")))
    pos = r.get_positions()[0]
    assert isinstance(pos.avg_cost, _Dec)
    assert pos.avg_cost == exact                       # not almost-equal - exact


def test_position_upsert_then_delete_at_zero():
    r = _repo4()
    r.record_fill(cash=_Dec("90000"), realised_pnl=_Dec("0"), symbol="AAPL",
                  new_quantity=_Dec("10"), new_avg_cost=_Dec("100"),
                  trade=_PT(1.0, "AAPL", "buy", _Dec("10"), _Dec("100"), _Dec("100"),
                            _Dec("0"), _Dec("10"), _Dec("0.00")))
    assert r.get_positions()[0].quantity == _Dec("10")
    r.record_fill(cash=_Dec("91000"), realised_pnl=_Dec("0"), symbol="AAPL",
                  new_quantity=_Dec("0"), new_avg_cost=None,           # reduce to 0 -> delete
                  trade=_PT(2.0, "AAPL", "sell", _Dec("10"), _Dec("110"), _Dec("100"),
                            _Dec("10"), _Dec("0"), _Dec("100.00")))
    assert r.get_positions() == []
    assert r.count_trades() == 2                        # append-only (both fills kept)


def test_reset_clears_positions_cash_realised_retains_trades():
    r = _repo4()
    r.load_or_create_portfolio("100000")
    r.record_fill(cash=_Dec("50000"), realised_pnl=_Dec("-25.00"), symbol="AAPL",
                  new_quantity=_Dec("5"), new_avg_cost=_Dec("100"),
                  trade=_PT(1.0, "AAPL", "buy", _Dec("5"), _Dec("100"), _Dec("100"),
                            _Dec("0"), _Dec("5"), _Dec("0.00")))
    rp = r.reset_portfolio("100000")
    assert rp.cash == _Dec("100000") and rp.realised_pnl == _Dec("0")  # cash and pnl reset
    assert r.get_positions() == []                      # positions cleared
    assert r.count_trades() == 1                        # trade log retained
    r.clear_trades()
    assert r.count_trades() == 0                        # export-gated clear (logic in UI)


# ============================================================================ #
# value-history + persisted all-time peak #
# ============================================================================ #
from mahad.data.repository import RISK_TIMEFRAME_KEY                 # noqa: E402


def test_portfolio_creation_seeds_inception_peak():
    r = _repo4()                                          # creates AAPL + portfolio (cash 100000)
    peak = r.get_peak()
    assert peak.peak_value == _Dec("100000")             # peak seeded to starting cash
    assert peak.peak_ts is not None


def test_value_history_append_list_and_stale_flag_roundtrip():
    r = _repo4()
    r.append_value_history(ts=1.0, portfolio_value=_Dec("100000"), cash=_Dec("100000"),
                           positions_value=_Dec("0"), stale=False, cap=1000)
    r.append_value_history(ts=2.0, portfolio_value=_Dec("100500"), cash=_Dec("50000"),
                           positions_value=_Dec("50500"), stale=True, cap=1000)
    rows = r.list_value_history()
    assert [v.ts for v in rows] == [1.0, 2.0]            # ordered by ts
    assert rows[0].portfolio_value == _Dec("100000") and rows[0].stale is False
    assert rows[1].positions_value == _Dec("50500") and rows[1].stale is True   # stale persists


def test_value_history_capped_prune_drops_oldest():
    r = _repo4()
    for i in range(5):                                   # cap 3 -> only the newest 3 survive
        r.append_value_history(ts=float(i), portfolio_value=_Dec("100000"),
                               cash=_Dec("100000"), positions_value=_Dec("0"),
                               stale=False, cap=3)
    rows = r.list_value_history()
    assert [v.ts for v in rows] == [2.0, 3.0, 4.0]       # oldest (0,1) pruned, bounded delete
    assert r.count_value_history() == 3


def test_peak_read_write_roundtrip():
    r = _repo4()
    r.set_peak(_Dec("123456.78"), 999.0)
    peak = r.get_peak()
    assert peak.peak_value == _Dec("123456.78") and peak.peak_ts == 999.0


def test_reset_clears_value_history_and_reseeds_peak():
    r = _repo4()
    r.append_value_history(ts=1.0, portfolio_value=_Dec("90000"), cash=_Dec("90000"),
                           positions_value=_Dec("0"), stale=False, cap=1000)
    r.set_peak(_Dec("110000"), 1.0)                      # an inflated historical peak
    r.reset_portfolio("100000")
    assert r.count_value_history() == 0                  # value-history cleared
    peak = r.get_peak()
    assert peak.peak_value == _Dec("100000")             # re-seeded to the post-reset value
    assert peak.peak_ts is not None


def test_rebase_value_history_clears_and_reseeds():
    r = _repo4()
    r.append_value_history(ts=1.0, portfolio_value=_Dec("100000"), cash=_Dec("100000"),
                           positions_value=_Dec("0"), stale=False, cap=1000)
    r.rebase_value_history(ts=5.0, value=_Dec("100250"))   # risk_timeframe change
    assert r.count_value_history() == 0
    peak = r.get_peak()
    assert peak.peak_value == _Dec("100250") and peak.peak_ts == 5.0


def test_risk_timeframe_setting_roundtrip():
    r = _repo4()
    assert r.get_setting(RISK_TIMEFRAME_KEY) is None      # unset -> None (caller uses 1d default)
    r.set_setting(RISK_TIMEFRAME_KEY, "1m")
    assert r.get_setting(RISK_TIMEFRAME_KEY) == "1m"
