# 3d / 1w / 1mo are chart-display only; the risk timeframe set is a separate, locked concept
from __future__ import annotations

import datetime as dt
import pathlib

from tests._qt_stub import install as _install_qt_stub

_install_qt_stub()

from mahad import config
from mahad.data.models import Candle
from tests.test_worker_switch import _series, _worker

UTC = dt.timezone.utc


def _daily(symbol, items):
    return tuple(
        Candle(symbol=symbol, timeframe="1d",
               ts=dt.datetime(*d, tzinfo=UTC).timestamp(),
               open=c, high=c + 1, low=c - 1, close=c, volume=1.0, is_closed=True)
        for d, c in items)


def test_config_chart_timeframes_and_risk_set_unchanged():
    assert config.VALID_CHART_TIMEFRAMES == ("1m", "1h", "1d", "3d", "1w", "1mo")
    assert config.DEFAULT_TIMEFRAME == "1d"
    assert config.VALID_RISK_TIMEFRAMES == ("1m", "1h", "1d")   # locked, do not extend


def test_kraken_native_weekly_only_3d_1mo_resampled():
    from mahad.data import kraken_source
    assert kraken_source._TF_INTERVAL["1w"] == 10080
    assert "3d" not in kraken_source._TF_INTERVAL
    assert "1mo" not in kraken_source._TF_INTERVAL


def test_signals_adjacency_spacing_for_new_bars():
    from mahad.engine.signals import timeframe_seconds
    assert timeframe_seconds("3d") == 259200.0
    assert timeframe_seconds("1w") == 604800.0
    assert timeframe_seconds("1mo") == 2629800.0
    assert timeframe_seconds("1d") == 86400.0


def test_main_window_uses_the_chart_timeframe_set():
    src = (pathlib.Path(__file__).resolve().parents[1] / "mahad" / "ui"
           / "main_window.py").read_text(encoding="utf-8")
    assert "config.VALID_CHART_TIMEFRAMES" in src
    assert 'SegmentedControl(["1m", "1h", "1d"]' not in src     # old hardcoded list must be gone


def test_worker_chart_candles_routing(tmp_path):
    w = _worker(tmp_path)
    # stock: 3d/1w/1mo resample the official daily series
    daily = _daily("AAPL", [((2026, 1, 5), 10), ((2026, 1, 6), 11),
                            ((2026, 1, 7), 12), ((2026, 2, 2), 20)])
    w._daily_series["AAPL"] = daily
    mo = w._chart_candles("AAPL", "1mo", ())
    assert len(mo) == 2 and all(b.timeframe == "1mo" for b in mo)
    assert mo[0].is_closed is True and mo[1].is_closed is False
    assert w._chart_candles("AAPL", "1d", ()) == daily          # 1d official passthrough
    fetched = _series("AAPL", "1h")
    assert w._chart_candles("AAPL", "1h", fetched) == fetched   # 1m/1h passthrough

    # crypto: 3d/1mo resample the fetched Kraken daily; 1w is native passthrough
    cdaily = _daily("BTC/USD", [((2026, 1, 5), 100), ((2026, 2, 2), 200)])
    cmo = w._chart_candles("BTC/USD", "1mo", cdaily)
    assert len(cmo) == 2 and cmo[-1].timeframe == "1mo"
    native_weekly = _series("BTC/USD", "1w")
    assert w._chart_candles("BTC/USD", "1w", native_weekly) == native_weekly
