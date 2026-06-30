# widget guards read each module's source so they run under the Qt stub

from __future__ import annotations

from pathlib import Path
from mahad.data.portfolio_view import (ContributionRow, RiskAnalyticsView, StressRow,
                                       analytics_summary, backtest_chip_text,
                                       build_risk_snapshot_csv)
from mahad.ui import theme  # pure (Qt-free) contrast helpers


ROOT = Path(__file__).resolve().parents[1]

def _src(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def test_summary_formats_the_live_header():
    view = RiskAnalyticsView(available=True, var95_pct=0.0193,
                             es975_pct=0.0250, backtest_zone="green")
    assert analytics_summary(view) == "VaR95 1.9% · backtest GREEN · ES 2.5%"


def test_summary_surfaces_the_note_when_unavailable():
    view = RiskAnalyticsView(available=False,
                             note="needs history - free Tiingo key (tiingo.com)")
    assert "tiingo.com" in analytics_summary(view)
    assert analytics_summary(RiskAnalyticsView()) == "warming"


def test_chip_text_names_zone_counts_and_mode():
    base = {"available": True, "backtest_exceptions": 2,
            "backtest_observations": 209, "window": 250}
    backcast = RiskAnalyticsView(backtest_zone="green",
                                 backtest_mode="backcast", **base)
    assert backtest_chip_text(backcast) == "GREEN · 2 exc / 209d · backcast"
    accruing = RiskAnalyticsView(backtest_zone="green",
                                 backtest_mode="accruing", accruing_n=31, **base)
    assert backtest_chip_text(accruing).endswith("accruing (31/250)")
    exante = RiskAnalyticsView(backtest_zone="red", backtest_mode="ex-ante",
                               **base)
    assert backtest_chip_text(exante).startswith("RED")
    assert backtest_chip_text(exante).endswith("ex-ante")
    assert backtest_chip_text(RiskAnalyticsView()) == "no observations yet"


def test_stress_row_carrier_shape():
    row = StressRow(scenario="COVID crash", start="2020-02-19",
                    end="2020-03-23", pl_usd=-30750.0, covered_weight=1.0,
                    constant_legs=("BTC/USD",))
    assert row.legs_no_data == () and row.constant_legs == ("BTC/USD",)


def test_section_exists_default_collapsed_and_ordered():
    src = _src("mahad/ui/risk_panel.py")
    assert 'QLabel("RISK ANALYTICS")' in src
    ra = src.index('QLabel("RISK ANALYTICS")')
    ctx = src.index('QLabel("MARKET CONTEXT")')
    assert ra < ctx                       # portfolio-derived before exogenous
    assert "self._ra_body.hide()" in src  # collapsed by default to save height
    assert "self._ra_collapsed = True" in src
    assert "self._ra_chevron.set_expanded(False)" in src


def test_traffic_chip_is_painted_text_never_colour_only():
    src = _src("mahad/ui/risk_panel.py")
    chip = src.split("class _TrafficChip", 1)[1].split("\nclass ", 1)[0]
    assert "drawText" in chip             # state carried by text, not colour alone
    assert "drawRoundedRect" in chip
    assert "theme._qcolor(" in chip
    # zone spelled in WORDS, not colour-coded
    assert "backtest_chip_text" in src


def test_heatmap_is_imageitem_with_painted_numerals():
    src = _src("mahad/ui/risk_panel.py")
    hm = src.split("class _CorrHeatmap", 1)[1].split("\nclass ", 1)[0]
    assert "ImageItem" in hm
    assert "TextItem" in hm               # rho numeral in every cell
    assert '"-" if v is None else f"{v:+.2f}"' in hm


def test_engine_carries_the_core_formulas():
    src = _src("mahad/engine/risk_metrics.py")
    assert "floor((1-c)T) + 1" in src                 # VaR order statistic
    assert "tail inclusive" in src                    # ES convention
    assert "bcbs22" in src                            # Basel citation
    assert "sqrt(252)" in src                          # trading-day annualisation
    assert "downside" in src                          # Sortino convention


def test_main_window_wires_the_analytics_view():
    src = _src("mahad/ui/main_window.py")
    assert "set_analytics(snap.analytics)" in src


def test_summary_uses_the_eliding_contract():
    # set_full_text is resize-safe and carries the tooltip; raw setText is not
    src = _src("mahad/ui/risk_panel.py")
    assert "self._ra_summary.set_full_text(" in src
    assert "self._ra_summary.setText(" not in src
    assert "self._ra_summary.setVisible(self._ra_collapsed)" in src


def test_heatmap_cap_is_surfaced_and_rows_unmirrored():
    src = _src("mahad/ui/risk_panel.py")
    assert 'f" · FIRST {cap} OF {n_corr}"' in src     # the silent cap surfaced
    assert "img[::-1, :]" in src                      # fills match the numerals
    hm = src.split("class _CorrHeatmap", 1)[1].split("\nclass ", 1)[0]
    assert "self._vb.addItem(t)" in hm
    # inks via _qcolor (not raw RGB), chosen per cell for AA
    assert "theme._qcolor(theme.aa_ink_for(" in hm


def test_row_formats_are_pinned():
    src = _src("mahad/ui/risk_panel.py")
    assert 'pct(view.var95_pct) + usd(view.var95_usd)' in src   # USD + %
    assert 'f"{view.rf_annual_pct:.2f}% · {view.rf_as_of}"' in src
    assert '"Kupiec POF p = ' in src or 'Kupiec POF p =' in src
    assert 'QLabel(f"{row.scenario}\\n{row.start} to {row.end}")' in src \
        or "{row.start} to {row.end}" in src          # dates visible on rows


def test_chip_text_yellow_zone():
    view = RiskAnalyticsView(available=True, backtest_zone="yellow",
                             backtest_mode="ex-ante", backtest_exceptions=6,
                             backtest_observations=250, window=250)
    assert backtest_chip_text(view) == "YELLOW · 6 exc / 250d · ex-ante"


def test_theme_has_the_value_token():
    src = _src("mahad/ui/theme.py")
    assert "QLabel#CtxVal {" in src or "QLabel#CtxVal {{" in src


def test_heatmap_incell_numerals_clear_aa_on_every_cell():
    ground = theme._rgb_tuple(theme.ROW_SOLID)
    worst = 99.0
    for base in ((37, 99, 235), (248, 81, 73)):
        for step in range(0, 101):
            rho = step / 100.0
            alpha = int(40 + 120 * min(rho, 1.0))
            cell = theme.composite_over((base[0], base[1], base[2], alpha), ground)
            ink = theme.aa_ink_for(cell)
            cr = theme.contrast_ratio(theme._rgb_tuple(ink), cell)
            worst = min(worst, cr)
    assert worst >= theme.AA_NORMAL, f"worst in-cell numeral contrast {worst:.2f} < AA 4.5"


def test_heatmap_uses_contrast_aware_ink_not_a_fixed_token():
    src = _src("mahad/ui/risk_panel.py")
    # ink chosen per cell against the composited fill, never one hard-coded ink
    assert "aa_ink_for(" in src
    assert "composite_over(_fill" in src


def test_contrast_ratio_matches_known_wcag_values():
    # white on black == 21:1; identical colours == 1:1 (sanity-pins the math)
    assert abs(theme.contrast_ratio((255, 255, 255), (0, 0, 0)) - 21.0) < 0.05
    assert abs(theme.contrast_ratio((18, 20, 24), (18, 20, 24)) - 1.0) < 1e-9


def test_contribution_row_shape():
    c = ContributionRow(symbol="AAPL", weight=0.4, pct=1.1,
                        comp_var_pct=0.012, comp_var_usd=1234.0)
    assert c.symbol == "AAPL" and c.pct == 1.1 and c.comp_var_usd == 1234.0


def test_view_carries_component_var_fields():
    v = RiskAnalyticsView(available=True, comp_var_pct=0.0109,
                          comp_var_usd=1094.0, comp_sigma_pct=0.00665,
                          contributions=(ContributionRow("AAA", 0.5, 1.1,
                                                         0.012, 1200.0),))
    assert v.comp_confidence == 0.95
    assert v.comp_var_pct == 0.0109 and len(v.contributions) == 1


def test_csv_includes_component_var_and_contrib_rows():
    v = RiskAnalyticsView(available=True, n=250, comp_var_pct=0.0109,
                          contributions=(ContributionRow("AAA", 0.5, 1.1,
                                                         0.012, 1200.0),
                                         ContributionRow("BBB", 0.3, -0.1,
                                                         -0.002, -180.0)))
    csv = build_risk_snapshot_csv(v)
    assert "component_var95" in csv
    assert "contrib_AAA" in csv and "contrib_BBB" in csv


def test_contributions_block_block_guards():
    src = _src("mahad/ui/risk_panel.py")
    assert 'QLabel("RISK CONTRIBUTIONS")' in src
    assert "_render_contributions" in src and "TIP_RA_CONTRIB" in src
    assert "COMP VAR" in src
    assert "c.pct * 100.0:+" in src          # signed: a hedge reads negative
    assert "c.comp_var_usd:+" in src


def test_diversification_block_block_guards():
    src = _src("mahad/ui/risk_panel.py")
    assert 'QLabel("DIVERSIFICATION")' in src
    assert "_render_diversification" in src and "TIP_RA_DIVERS" in src
    assert "avg rho" in src
    assert "sector_weights" in src            # full breakdown, not top-N


def test_engine_documents_component_var():
    src = _src("mahad/engine/risk_metrics.py")
    assert "component_var" in src
    assert "Euler" in src
    assert "negative" in src                       # the hedge note


def test_view_carries_pnl_linkage_fields():
    v = RiskAnalyticsView(available=True, pnl_total_usd=2500.0,
                          pnl_unrealised_usd=1800.0, pnl_realised_usd=700.0,
                          pnl_to_var95=2.3, unreal_to_var95=1.6)
    assert v.pnl_total_usd == 2500.0 and v.pnl_to_var95 == 2.3


def test_pnl_vs_risk_block_block_guards():
    src = _src("mahad/ui/risk_panel.py")
    assert 'QLabel("P&L vs RISK")' in src
    assert "TIP_RA_PNL" in src and "_ra_pnl_rows" in src
    assert "x VaR95" in src
    assert "signed_usd(" in src               # signed: a loss reads negative
    assert "return_on_risk" in _src("mahad/worker.py")


def test_view_carries_var_history():
    v = RiskAnalyticsView(available=True, var_history=(0.018, 0.019, 0.021),
                          var_trend="rising")
    assert v.var_history[-1] == 0.021 and v.var_trend == "rising"


def test_var_history_block_block_guards():
    src = _src("mahad/ui/risk_panel.py")
    assert 'QLabel("VAR HISTORY")' in src
    assert "TIP_RA_VARHIST" in src and "_render_varhistory" in src
    assert "_ra_varhist_spark" in src and "Sparkline()" in src
    assert "60d roll" in src


def test_portfolio_stats_carry_methodology_tooltips():
    src = _src("mahad/ui/portfolio_panel.py")
    assert "def _stat(self, row: QHBoxLayout, label: str, tip: str" in src
    assert "marked to market live" in src
    assert "booked on closed quantity" in src
    assert "moves with the marks" in src
    assert "Simulated USD portfolio" in src        # no real-money framing must survive
