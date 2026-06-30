from __future__ import annotations

from dataclasses import dataclass

from mahad.data.repository import (SCHEMA_MIGRATION_KEY, MahadRepository)


@dataclass(frozen=True)
class _Row:
    ts: float
    open: float
    high: float
    low: float
    close: float
    adj_close: float
    volume: float
    div_cash: float
    split_factor: float


def _bar(ts, close, div=0.0, split=1.0):
    return _Row(ts=ts, open=close - 1, high=close + 1, low=close - 2,
                close=close, adj_close=close * 0.98, volume=1000.0,
                div_cash=div, split_factor=split)


def _repo(tmp_path, name="m.db"):
    return MahadRepository(f"sqlite:///{tmp_path / name}")


# --------------------------------------------------------------------------- #
# DailyBar cache
# --------------------------------------------------------------------------- #
def test_daily_bars_round_trip_ordered_and_capped(tmp_path):
    repo = _repo(tmp_path)
    repo.add("AAPL", "stock", "USD", "finnhub")
    rows = [_bar(86400.0 * i, 100.0 + i) for i in (3, 1, 2)]
    assert repo.upsert_daily_bars("AAPL", rows) == 3
    got = repo.list_daily_bars("AAPL")
    assert [b.ts for b in got] == [86400.0, 172800.0, 259200.0]   # oldest first
    assert got[-1].close == 103.0 and got[-1].adj_close == 103.0 * 0.98
    assert repo.latest_daily_bar_ts("AAPL") == 259200.0
    limited = repo.list_daily_bars("AAPL", limit=2)
    assert [b.ts for b in limited] == [172800.0, 259200.0]        # most-recent 2
    repo.close()


def test_daily_bars_upsert_is_idempotent_and_updates(tmp_path):
    repo = _repo(tmp_path)
    repo.add("AAPL", "stock", "USD", "finnhub")
    repo.upsert_daily_bars("AAPL", [_bar(86400.0, 100.0)])
    repo.upsert_daily_bars("AAPL", [_bar(86400.0, 101.0, div=0.25)])  # same ts
    got = repo.list_daily_bars("AAPL")
    assert len(got) == 1 and got[0].close == 101.0 and got[0].div_cash == 0.25
    repo.close()


def test_daily_bars_carry_corporate_actions(tmp_path):
    repo = _repo(tmp_path)
    repo.add("AAPL", "stock", "USD", "finnhub")
    repo.upsert_daily_bars("AAPL", [_bar(86400.0, 100.0, div=0.26),
                                    _bar(172800.0, 25.0, split=4.0)])
    got = repo.list_daily_bars("AAPL")
    assert got[0].div_cash == 0.26 and got[1].split_factor == 4.0
    repo.close()


def test_daily_bars_clear_and_unknown_symbol(tmp_path):
    repo = _repo(tmp_path)
    repo.add("AAPL", "stock", "USD", "finnhub")
    repo.upsert_daily_bars("AAPL", [_bar(86400.0, 100.0)])
    repo.clear_daily_bars("AAPL")
    assert repo.list_daily_bars("AAPL") == []
    assert repo.upsert_daily_bars("NOPE", [_bar(1.0, 2.0)]) == 0
    assert repo.list_daily_bars("NOPE") == [] and repo.latest_daily_bar_ts("NOPE") is None
    repo.close()


# --------------------------------------------------------------------------- #
# The one-time migration: old shape in -> new shape out
# --------------------------------------------------------------------------- #
def _old_shape_repo(tmp_path):
    repo = _repo(tmp_path, "old.db")
    repo.add("AAPL", "stock", "USD", "yfinance")
    repo.add("BTC/USDT", "crypto", "USDT", "kraken")
    alert, reason = repo.add_alert("BTC/USDT", "price_threshold",
                                   {"level": 70000.0}, "up")
    assert alert is not None, reason
    return repo


def test_migration_renames_providers_and_pairs(tmp_path):
    repo = _old_shape_repo(tmp_path)
    assert repo.migrate_legacy_schema() is True
    symbols = {p.symbol: p for p in repo.list_watchlist()}
    assert "BTC/USD" in symbols and "BTC/USDT" not in symbols
    assert symbols["BTC/USD"].quote_currency == "USD"
    assert symbols["BTC/USD"].provider == "kraken"
    assert symbols["AAPL"].provider == "finnhub"
    # alert follows its FK across the rename
    alerts = repo.list_alerts()
    assert len(alerts) == 1 and alerts[0].symbol == "BTC/USD"
    repo.close()


def test_migration_is_a_no_op_on_relaunch(tmp_path):
    repo = _old_shape_repo(tmp_path)
    assert repo.migrate_legacy_schema() is True
    before = [(p.symbol, p.provider) for p in repo.list_watchlist()]
    assert repo.migrate_legacy_schema() is False                  # marker stops a re-run
    assert [(p.symbol, p.provider) for p in repo.list_watchlist()] == before
    assert repo.get_setting(SCHEMA_MIGRATION_KEY) is not None
    repo.close()


def test_migration_skips_a_colliding_target(tmp_path):
    repo = _repo(tmp_path, "clash.db")
    repo.add("BTC/USD", "crypto", "USD", "kraken")         # target already exists
    repo.add("BTC/USDT", "crypto", "USDT", "kraken")
    assert repo.migrate_legacy_schema() is True
    tickers = sorted(p.symbol for p in repo.list_watchlist())
    assert tickers == ["BTC/USD", "BTC/USDT"]              # skipped, not merged
    assert repo.get_setting(SCHEMA_MIGRATION_KEY) is not None
    repo.close()


def test_migration_carries_positions_and_the_usdc_variant(tmp_path):
    # positions hang off symbol_id, so an in-place rename must carry them; also covers /USDC
    from decimal import Decimal
    from mahad.data.repository import PersistedTrade
    repo = _repo(tmp_path, "pos.db")
    repo.add("BTC/USDT", "crypto", "USDT", "kraken")
    repo.add("ETH/USDC", "crypto", "USDC", "kraken")
    repo.load_or_create_portfolio("100000")
    repo.record_fill(
        cash=Decimal("25000"), realised_pnl=Decimal("0"), symbol="BTC/USDT",
        new_quantity=Decimal("1"), new_avg_cost=Decimal("75000"),
        trade=PersistedTrade(ts=1.0, symbol="BTC/USDT", side="buy",
                             quantity=Decimal("1"), fill_price=Decimal("75000"),
                             avg_cost_at_fill=Decimal("75000"),
                             qty_before=Decimal("0"), qty_after=Decimal("1"),
                             realised_pnl=Decimal("0")))
    assert repo.migrate_legacy_schema() is True
    positions = {p.symbol: p for p in repo.get_positions()}
    assert "BTC/USD" in positions and "BTC/USDT" not in positions
    assert positions["BTC/USD"].quantity == Decimal("1")     # FK carried it
    assert {p.symbol for p in repo.list_watchlist()} == {"BTC/USD", "ETH/USD"}
    trades = repo.list_trades()
    assert trades[0].symbol == "BTC/USDT"      # history keeps its ticker (artifact)
    repo.close()


def test_migration_failure_rolls_back_and_retries_next_launch(tmp_path, monkeypatch):
    repo = _old_shape_repo(tmp_path)
    real_commit = repo._session.commit
    def boom():
        raise RuntimeError("disk hiccup")
    monkeypatch.setattr(repo._session, "commit", boom)
    assert repo.migrate_legacy_schema() is False                  # commit blew up, rolled back
    monkeypatch.setattr(repo._session, "commit", real_commit)
    assert repo.get_setting(SCHEMA_MIGRATION_KEY) is None
    assert {p.symbol for p in repo.list_watchlist()} == {"AAPL", "BTC/USDT"}
    assert repo.migrate_legacy_schema() is True                   # retries clean next launch
    assert {p.symbol for p in repo.list_watchlist()} == {"AAPL", "BTC/USD"}
    repo.close()


def test_migration_marker_survives_reopen(tmp_path):
    repo = _old_shape_repo(tmp_path)
    repo.migrate_legacy_schema()
    repo.close()
    repo2 = MahadRepository(f"sqlite:///{tmp_path / 'old.db'}")
    assert repo2.migrate_legacy_schema() is False
    assert {p.symbol for p in repo2.list_watchlist()} == {"AAPL", "BTC/USD"}
    repo2.close()
