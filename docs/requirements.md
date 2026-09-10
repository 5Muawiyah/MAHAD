# Requirements

## Purpose and scope

MAHAD is a single-user desktop workstation that runs a simulated USD portfolio on live market data and reports market-risk figures over it. The requirements below are what the program as it stands in the repository is required to do and not to do; each names the test in the suite that proves it.

In scope: live stock and crypto prices with charting and indicators, a watchlist, simulated orders against an exact ledger, the risk figures on two bases, the market-context tiles, one-shot alerts, local persistence, the handling of the three optional free keys, and the headless report export.

Out of scope: any connection to a brokerage or trading account, any real order, any currency other than USD for the book (a GBP view is display only), multi-user or networked operation, and any form of investment advice.

## Stakeholders and users

The program has one machine, one user and two roles. The analyst runs the program, follows symbols, places simulated trades and reads the figures as they update. The reader consumes the figures without running the program: through the report CSV, the exported trade log, or the documents in this folder. There is no administrator, no server and no shared state.

## Functional requirements

Each requirement names the tests that prove it. Test names are functions in `tests/`; the file is given once per group.

### Market data

FR-01. The program shall fetch live US stock quotes from Finnhub with a free key and shall show a clear needs-a-key state on every stock surface when no key is configured. Proof: `test_finnhub_without_key_is_needs_key` and `test_stock_source_keyless_finnhub_is_needs_key` in `test_market_data_providers.py`; `test_keyless_finnhub_chart_state_carries_the_friendly_copy` and `test_keyless_finnhub_watchlist_row_flags_needs_key` in `test_worker_scheduling.py`.

FR-02. The program shall fetch crypto marks and candles from Kraken's public endpoints without a key, batching the marks of every held pair into one call. Proof: `test_kraken_fetch_assembles_quote_and_candles`, `test_kraken_ohlc_parses_and_marks_the_forming_bar` and `test_kraken_batch_covers_every_requested_pair` in `test_market_data_providers.py`; `test_held_crypto_marks_ride_one_batch_call` in `test_worker_scheduling.py`.

FR-03. Every provider failure shall be returned as a typed value (timeout, network, empty, bad data, needs key, invalid key) and never raised into the worker. Proof: `test_kraken_network_failure_is_a_value`, `test_finnhub_401_is_invalid_key`, `test_tiingo_network_failure_is_a_value` and `test_kraken_malformed_payload_is_a_value` in `test_market_data_providers.py`; `test_treasury_failures_are_values_never_raises` in `test_market_context.py`; `test_fx_failures_are_values` in `test_fx_rates_providers.py`.

FR-04. Provider rows shall normalise into frozen `Quote` and `Candle` values: malformed and non-positive rows dropped, duplicates removed, bars sorted, capped at 500, and the last bar flagged as forming. Proof: `test_ohlcv_normalises_sorts_dedupes_and_marks_forming`, `test_dedupe_key_is_symbol_timeframe_ts` and `test_history_cap_keeps_most_recent` in `test_normalisation.py`; `test_normalize_ohlcv_total_on_junk` in `test_fuzz.py`.

FR-05. A quote older than three poll intervals or fifteen seconds, whichever is longer, shall be marked stale; on a failed fetch the last good quote shall be kept and shown as stale. Proof: `test_staleness_window_floor_and_multiple` and `test_is_stale_boundary` in `test_normalisation.py`; `test_worker_poll_source_failure_keeps_last_good` in `test_robustness.py`.

FR-06. Stock marks between polls shall be assembled into one-minute, one-hour and one-day bars, opening and closing buckets on period boundaries and ignoring out-of-order marks. Proof: `test_bucket_opens_tracks_and_closes_on_the_boundary`, `test_gap_closes_the_open_bucket_exactly_once`, `test_out_of_order_mark_is_ignored` and `test_stock_source_accumulates_intraday_buckets` in `test_market_data_providers.py`.

### Charting

FR-07. The chart shall offer the timeframes 1m, 1h, 1d, 3d, 1w and 1mo, with 3d and 1mo resampled from daily bars and 1w native on Kraken. Proof: `test_config_chart_timeframes_and_risk_set_unchanged`, `test_kraken_native_weekly_only_3d_1mo_resampled` and `test_worker_chart_candles_routing` in `test_chart_timeframes.py`; `test_monthly_ohlc_aggregation_and_trailing_forming` and `test_weekly_buckets_by_iso_week` in `test_resample.py`.

FR-08. The chart shall overlay a simple moving average (SMA), an exponential moving average (EMA) and Wilder's relative strength index (RSI), computed on closed bars only, with periods clamped to 2 through 400 and the settings persisted. Proof: `test_sma_basic_and_warmup`, `test_ema_seed_equals_sma_of_first_n`, `test_wilder_rsi_hand_computed_period_3`, `test_snapshot_indicators_exclude_the_forming_bar` and `test_clamp_period_bounds` in `test_indicators.py`; `test_indicator_settings_roundtrip_and_defensive` in `test_persistence.py`.

FR-09. The header shall show the market session (open, closed with the next open, or 24/7 for crypto) from the NYSE calendar, including holidays and half days. Proof: `test_stock_closed_on_a_full_holiday`, `test_stock_early_close_half_day`, `test_computed_2027_matches_the_published_nyse_list`, `test_crypto_is_always_open24` and `test_session_line_text_by_state` in `test_market_session.py`.

### Watchlist

FR-10. Adding a symbol shall reject empty, malformed and non-USD entries with a stated reason, ignore duplicates, and refuse additions beyond 20 symbols. Proof: `test_validate_add_outcomes` in `test_persistence.py`; `test_empty_and_whitespace_rejected`, `test_non_usd_rejected_verbatim`, `test_duplicate_ignored_case_insensitive` and `test_watchlist_cap_message` in `test_invalid_entry.py`; `test_validate_add_total` in `test_fuzz.py`.

FR-11. Before a symbol is saved the worker shall probe the provider once; an unresolvable symbol or a failed probe shall be rejected inline and never added. Proof: `test_unresolvable_symbol_rejected_inline_not_added`, `test_probe_timeout_rejects_with_could_not_verify` and `test_resolving_symbol_is_added` in `test_validate_add_probe.py`.

FR-12. Removing a symbol shall be blocked while a position is held in it, shall fall back to the next symbol when the active one is removed, and shall clear to an empty state when the last one goes. Proof: `test_remove_held_symbol_blocked_with_inline_reason`, `test_remove_active_symbol_falls_back_to_next` and `test_remove_last_symbol_clears_to_empty_state` in `test_watchlist_remove.py`.

FR-13. Exactly one symbol shall be active at a time, the first added shall become active, and the choice shall persist across restarts. Proof: `test_seed_default_watchlist_first_is_active` and `test_set_active_switches_exactly_one` in `test_persistence.py`.

### Simulated trading

FR-14. A simulated market order shall fill at the quoted mark the ticket froze, shall be refused when that mark is absent or stale or while another order is in flight, and shall be recorded only after the database commit succeeds. Proof: `test_absent_mark_blocks_the_fill` in `test_portfolio.py`; `test_worker_place_order_hostile_payloads_never_raise` in `test_robustness.py`; `test_place_order_blocks_reentrant`, `test_single_buy_books_one_trade`, `test_fill_price_is_the_frozen_mark`, `test_stale_mark_order_is_refused` and `test_fill_persist_failure_is_not_adopted` in `test_spam_inputs.py`.

FR-15. Quantities shall be positive with at most eight decimal places; cash shall never go negative; a sell shall not exceed the position. Proof: `test_zero_negative_and_overprecise_qty_rejected`, `test_buy_to_exactly_zero_cash_accepted`, `test_buy_one_cent_over_cash_rejected_and_state_unchanged`, `test_sell_exceeds_position_rejected` and `test_sell_with_no_position_rejected` in `test_portfolio.py`; `test_validate_qty_total` in `test_fuzz.py`.

FR-16. The ledger shall use exact decimals, round money half-up to the cent, keep the average cost at full precision, book realised profit and loss (P&L) on sells, and reconstruct cash and realised P&L from its own trade log. Proof: `test_money_rounds_half_up`, `test_avg_cost_kept_full_precision_changes_realised`, `test_sell_to_reduce_books_realised_and_deletes_at_zero` and `test_csv_reconstructs_the_ledger` in `test_portfolio.py`; `test_cash_never_negative_and_reconstruction_matches` in `test_fuzz.py`; `test_thousand_trades_ledger_exact` in `test_stress.py`.

FR-17. The portfolio view shall show cash, positions, and realised, unrealised and total P&L marked to the latest quotes, flagging the view stale when any mark is stale or missing. Proof: `test_unrealised_value_total_signs` in `test_portfolio.py`; `test_realised_plus_unrealised_is_total` in `test_fuzz.py`; `test_missing_mark_flags_all_three_valuation_views_stale` and `test_fresh_mark_keeps_all_three_views_non_stale` in `test_worker_context.py`.

FR-18. A reset shall clear positions, cash and realised P&L back to the starting cash, keep the trade log unless an export succeeded and clearing was requested, and re-seed the value history, the peak and the backtest series. Proof: `test_reset_clears_positions_cash_realised_retains_trades`, `test_reset_clears_value_history_and_reseeds_peak` in `test_persistence.py`; `test_reset_clears_the_backtest_series` in `test_worker_analytics.py`; `test_reset_in_flight_drops_reentrant` and `test_reset_clears_the_log_only_when_export_succeeded_and_clearing_requested` in `test_spam_inputs.py`.

### Risk analytics

FR-19. The portfolio value shall be sampled on a fixed wall-clock grid at the chosen risk timeframe, catching up one sample after a sleep and re-anchoring when the timeframe changes; the series shall persist up to 1,000 samples. Proof: `test_sleep_catchup_takes_one_sample_and_preserves_the_grid`, `test_heartbeat_no_sample_before_due` and `test_set_risk_timeframe_reanchors_the_grid` in `test_worker_context.py`; `test_value_history_capped_prune_drops_oldest` in `test_persistence.py`.

FR-20. Exposure, volatility (sample standard deviation over the last 30 returns, annualised on the calendar basis), maximum drawdown (seeded from the persisted peak) and drawdown duration shall be computed on the value history and match the hand-worked vectors. Proof: `test_exposure_overall_fraction_and_abs`, `test_volatility_ddof1_per_period_and_annualised`, `test_volatility_rolling_window_cap_min_available_30`, `test_max_drawdown_core_vector` and `test_max_drawdown_seeded_persisted_peak_survives_capping` in `test_risk.py`; `test_volatility_matches_statistics_stdev` in `test_fuzz.py`; `test_check_i_drawdown_duration` in `test_risk_metrics.py`.

FR-21. The trading-day analytics shall compute historical and parametric VaR, Expected Shortfall, the Kupiec test and the Basel zone, beta, Sharpe, Sortino, EWMA volatility, correlation, concentration, stress replay and component VaR, each matching its worked vector. Proof: `test_check_b_historical_var`, `test_check_b_expected_shortfall`, `test_check_c_parametric_from_moments`, `test_check_e_kupiec`, `test_check_e_basel_zones`, `test_check_g_beta`, `test_check_h_sharpe`, `test_check_h_sortino`, `test_check_f_ewma_steps`, `test_check_k_correlation`, `test_check_j_concentration`, `test_check_l_stress_replay` and `test_component_var_answer_key` in `test_risk_metrics.py`.

FR-22. The as-if portfolio return series shall use adjusted closes aligned to the US trading calendar with today's weights, shall report excluded assets and covered weight, and shall gate each figure on the number of aligned observations. Proof: `test_asset_returns_consume_the_adjusted_close_column` and `test_view_gates_on_n_not_coverage` in `test_worker_analytics.py`; `test_weekend_bars_fold_into_monday`, `test_portfolio_returns_reports_excluded_assets` and `test_check_n_through_the_full_series_path` in `test_returns.py`.

FR-23. The VaR backtest shall log one 99% forecast per trading day, resolve it against the next trading day's realised return, and run in backcast mode until 250 live forecasts have accrued. Proof: `test_backtest_persistence_round_trip`, `test_accrual_resolves_with_the_prior_days_weights`, `test_accrual_is_idempotent_per_day`, `test_backtest_mode_labels` and `test_ex_ante_label_takes_over_at_the_window` in `test_worker_analytics.py`; `test_backcast_hand_vector` in `test_risk_metrics.py`.

FR-24. Daily history shall be cached per symbol for every held position, the active stock and the SPY benchmark: fetched as a delta from the latest cached date, re-pulled in full when a corporate action (a dividend or split that changes the adjusted history) is seen, refreshed at most one symbol per tick of the worker's five-second heartbeat timer. Proof: `test_coverage_set_is_positions_active_stock_and_benchmark`, `test_stock_delta_fetch_starts_at_the_latest_cached_date`, `test_corporate_action_in_the_delta_triggers_a_full_repull` and `test_at_most_one_coverage_fetch_per_tick` in `test_worker_daily.py`; `test_daily_bars_upsert_is_idempotent_and_updates` in `test_daily_bar_migration.py`.

FR-25. Every risk figure shall be labelled with its basis and window, and the analytics section shall name the missing key when stock history is keyless. Proof: `test_row_formats_are_pinned` and `test_portfolio_stats_carry_methodology_tooltips` in `test_analytics_ui.py`; `test_view_names_the_tiingo_key_when_stock_history_is_keyless` in `test_worker_analytics.py`.

### Market context

FR-26. The context tiles shall show the Treasury curve with the 2s10s spread and its reading, the VIX with its band, the crypto Fear and Greed index and the two UK rates, refreshing at most one source per heartbeat tick and each source every 12 hours, caching the tiles across restarts and keeping the last good values with a note after a failure. Proof: `test_treasury_picks_the_latest_row_regardless_of_order`, `test_spread_bp_hand_checked_vectors`, `test_vix_band_edges` and `test_fng_parses_the_live_captured_payload` in `test_market_context.py`; `test_boe_parses_latest_per_series` in `test_fx_rates_providers.py`; `test_one_context_fetch_per_heartbeat_tick`, `test_context_success_builds_tiles_and_persists_the_cache`, `test_context_failure_keeps_cached_values_with_an_honest_note` and `test_load_context_cache_restores_tiles_offline` in `test_worker_context.py`.

FR-27. The VIX tile shall show a keyless state without a FRED key and shall never show a cached value once the key is gone. Proof: `test_vix_without_a_key_is_the_designed_keyless_state` and `test_cached_vix_is_not_shown_when_the_key_is_gone` in `test_worker_context.py`.

FR-28. The GBP figures shall be a display-only conversion at the European Central Bank (ECB) reference rate and shall never enter the ledger. Proof: `test_fx_parses_the_reference_rate` and `test_portfolio_gbp_view_is_display_only` in `test_fx_rates_providers.py`.

### Alerts

FR-29. An alert shall be one of four conditions (price threshold, RSI threshold, price crossing an SMA, SMA crossing an EMA) with validated parameters, shall fire once and disarm, and shall be re-armable. Proof: `test_validate_params_canonical_and_ranges`, `test_evaluate_alert_one_shot_then_rearm` and `test_price_sma_crossover_up_fires_down_does_not` in `test_signals.py`; `test_set_alert_state_fire_then_rearm_roundtrip` in `test_persistence.py`.

FR-30. Crossovers shall use closed bars only, shall not fire across an intraday data gap, and shall not replay after a symbol or timeframe switch. Proof: `test_crossover_uses_closed_closes_only_forming_bar_excluded` and `test_crossover_no_signal_across_a_data_gap_intraday` in `test_signals.py`; `test_switch_resets_crossover_baseline_no_replay_from_cache` in `test_worker_switch.py`.

FR-31. Alerts shall pause while the quote is stale, shall persist the fire before the event is emitted, shall be capped at 20, and identical alerts shall be blocked. Proof: `test_worker_stale_quote_pauses_alerts_no_fire` and `test_worker_persist_before_emit_on_fire` in `test_robustness.py`; `test_add_alert_cap_20` and `test_add_alert_identical_duplicate_blocked_incl_150_vs_150_0` in `test_persistence.py`.

### Persistence

FR-32. The watchlist, indicator settings, alerts, portfolio, positions, trades, value history, daily bars and backtest rows shall survive a restart, and the schema shall carry a version row. Proof: `test_schema_version_row_created`, `test_add_alert_persists_and_lists`, `test_position_upsert_then_delete_at_zero`, `test_value_history_append_list_and_stale_flag_roundtrip` and `test_peak_read_write_roundtrip` in `test_persistence.py`; `test_daily_bars_round_trip_ordered_and_capped` in `test_daily_bar_migration.py`.

FR-33. A corrupt or mismatched database file shall be backed up and recreated, a locked file shall not be rotated, and a file that cannot be opened shall degrade the session to memory with a visible notice. Proof: `test_open_repository_recovers_corrupt_file`, `test_open_repository_schema_mismatch_backs_up`, `test_open_repository_does_not_rotate_on_transient_lock` and `test_worker_db_open_failure_degrades_to_memory` in `test_robustness.py`; `test_db_notice_rides_a_discrete_signal_and_is_emitted_on_start` in `test_context_wiring_guards.py`.

FR-34. The one-time migration shall rename stock rows whose provider is the retired yfinance to finnhub and crypto tickers quoted in USDT or USDC to their USD pair, shall run once, roll back on failure, and skip a target that already exists. Proof: `test_migration_renames_providers_and_pairs`, `test_migration_is_a_no_op_on_relaunch`, `test_migration_skips_a_colliding_target` and `test_migration_failure_rolls_back_and_retries_next_launch` in `test_daily_bar_migration.py`.

### Keys and security

FR-35. The three keys shall be read from a `.env` file or the environment, never written to a log, never stored on the worker, and redacted from error text. Proof: `test_read_env_key_file_then_environment` and `test_read_env_key_never_logs_the_value` in `test_market_context.py`; `test_finnhub_errors_are_redacted_of_the_key` in `test_market_data_providers.py`; `test_worker_never_stores_the_key_value` and `test_env_example_is_committed_and_env_is_ignored` in `test_context_wiring_guards.py`.

FR-36. The program shall hold no trading credential of any kind and shall call only Kraken's public endpoints. Proof: `test_no_credential_kinds_beyond_the_one_free_data_key` in `test_context_wiring_guards.py`.

FR-37. Symbols, alert parameters and settings values shall be stored as inert data: injection strings land as literals, markup and path traversal are rejected at the symbol gate, and parameters are canonicalised before they are compared. Proof: `test_sqli_symbols_stored_as_literals`, `test_params_canonicalisation_defeats_smuggling`, `test_symbol_charset_gate_blocks_markup_and_traversal` and `test_csv_hostile_symbols_are_data_only` in `test_security.py`.

### Exports and the report

FR-38. The trade log, the value history and the risk snapshot shall export as self-contained CSV files. Proof: `test_csv_rows_are_self_contained` in `test_portfolio.py`; `test_value_history_csv_round_trip` in `test_market_context.py`; `test_risk_snapshot_csv_round_trips` in `test_fx_rates_providers.py`.

FR-39. `python -m mahad.report` shall write the book's figures to a CSV from the database in read-only mode, equal to the engine's own outputs on the same inputs, saying in a note when the database cannot support a figure, exiting with code 1 and a plain message when there is no data, and loading no module of the Qt window toolkit. Proof: `test_rows_equal_the_engine_on_the_same_inputs`, `test_rows_say_when_data_is_missing`, `test_csv_has_the_columns_and_the_summary_prints`, `test_no_data_gives_a_message_and_exit_one`, `test_the_report_connection_cannot_write` and `test_importing_the_report_pulls_in_no_qt` in `test_report.py`.

### Commands

FR-40. The command palette shall list these commands, and the ones with a shortcut shall drive the same path as the buttons: New simulated order (Ctrl+N), New alert (Ctrl+Shift+A), Add symbol to watchlist (Ctrl+K), Indicator overlays (Ctrl+I), Settings (Ctrl+,), Help (F1), Timeframe 1m, 1h and 1d (Ctrl+1, Ctrl+2, Ctrl+3), Export trades CSV (Ctrl+E), Export value-history CSV (Ctrl+Shift+E), Export risk-metrics CSV, Show Alerts tab, Show Portfolio tab, Show Trade log tab, Toggle Risk Analytics and Toggle Market Context. Proof: `test_registry_covers_core_commands` in `test_command_palette.py`; `test_shortcuts_are_installed_with_tooltip_hints` and `test_timeframe_shortcut_drives_the_same_intent_path` in `test_context_wiring_guards.py`.

## Non-functional requirements

NFR-01. Keyless start: crypto, the USD to GBP rate, the Treasury curve, the UK rates and the Fear and Greed index shall work with no key, and the program shall boot and show a live chart without one. Proof: `test_stock_source_keyless_tiingo_still_samples_1d` in `test_market_data_providers.py`; `test_vix_without_a_key_is_the_designed_keyless_state` in `test_worker_context.py`; the keyless boot is proved by the Windows CI jobs, which run `python -m mahad --smoke` (the flag starts the window offscreen, stops it after three seconds and exits 1 on any exception).

NFR-02. No trading credentials and no real-money path shall exist in the code. Proof: `test_no_credential_kinds_beyond_the_one_free_data_key` in `test_context_wiring_guards.py`.

NFR-03. The test suite shall run headless with no network and no display, and the report module shall load no module of the Qt window toolkit. Proof: `test_importing_the_report_pulls_in_no_qt` in `test_report.py`; the Ubuntu CI jobs run the suite on runners without the OpenGL libraries a Qt window needs.

NFR-04. Painted text shall meet the WCAG AA contrast standard (a 4.5 to 1 ratio for normal text), and state shall never be conveyed by colour alone. Proof: `test_contrast_ratio_matches_known_wcag_values`, `test_heatmap_incell_numerals_clear_aa_on_every_cell` and `test_traffic_chip_is_painted_text_never_colour_only` in `test_analytics_ui.py`; `test_count_badge_is_blue_and_aa` and `test_unread_badge_is_aa_safe_on_the_left` in `test_ui_layout_guards.py`.

NFR-05. Compute-side latency, measured as benchmark medians wherever the suite runs: SMA, EMA and RSI over 500 bars under 50 ms each; a snapshot with three indicators under 250 ms; twenty alerts evaluated under 250 ms; the value-history risk over 1,000 samples under 50 ms; a portfolio view with 1,000 trades under 250 ms; one fill commit and one value-history append at cap under 500 ms each. Proof: the nine tests in `test_perf.py`.

NFR-06. Without a network the program shall keep the last good prices marked stale, back off to at most 60 seconds between attempts, pause alerts, and show the cached context tiles. Proof: `test_worker_poll_source_failure_keeps_last_good` and `test_worker_stale_quote_pauses_alerts_no_fire` in `test_robustness.py`; `test_backoff_caps_at_config_ceiling` and `test_backoff_resets_on_success_and_user_intent_bypasses` in `test_worker_switch.py`; `test_context_failure_with_no_data_reads_unavailable` in `test_worker_context.py`.

NFR-07. Memory shall stay bounded: 500 bars per series, 300 rendered points, 1,000 value samples, 20 alerts, 20 watchlist symbols, and repeated snapshots shall not grow. Proof: `test_history_cap_enforced_on_hostile_input`, `test_render_cap_bounds_snapshot`, `test_value_history_cap_pruned_in_db`, `test_alert_cap_enforced`, `test_watchlist_cap_via_worker` and `test_thousand_snapshot_cycles_no_growth` in `test_stress.py`.

NFR-08. Hostile or malformed input shall never raise out of an adapter, a validator or a worker slot. Proof: `test_normalize_ohlcv_drops_malformed_rows_never_raises` and `test_worker_arm_alert_hostile_payloads_never_raise` in `test_robustness.py`; `test_validate_params_total` in `test_fuzz.py`.

NFR-09. One background thread shall do all fetching, computing and writing; the window shall not block on the network, shall gate a symbol switch while one is in flight, and shall stop the thread cooperatively on close. Proof: `test_symbol_switch_is_gated_while_in_flight` in `test_ui_layout_guards.py`; `test_closeevent_requests_interruption` in `test_spam_inputs.py`; the thread wiring is a manual check against `mahad/ui/main_window.py`.

NFR-10. The program shall run on Python 3.11, 3.12 and 3.13 on Windows, macOS and Linux. Proof: the GitHub Actions matrix covers the three versions on Ubuntu and Windows; macOS is a manual check.

NFR-11. User-facing copy shall use British English with hyphens, never dashes. Proof: `test_no_em_or_en_dashes_in_the_context_files` in `test_context_wiring_guards.py`; `test_summary_strings_are_dash_clean_and_descriptive` in `test_signals.py`.

## User stories

### Watch a symbol

As the analyst I want to follow a symbol so that I can see its price and indicators update live.

Given the watchlist is showing and the symbol is a USD-quoted ticker not already listed, when I type it and press add, then the worker probes the provider once, the symbol appears in the list in a warming state (listed, no price yet), and it becomes the active chart if it was the first symbol added.

Given a typed symbol is empty, malformed, non-USD or already listed, when I press add, then the entry is rejected inline with the reason, or ignored as a duplicate, and nothing is saved.

Given a symbol is listed, when I click its row, then the chart switches to it, a cached series renders at once if one exists, and the fresh fetch replaces it within one poll.

### Place a simulated order

As the analyst I want to buy or sell a symbol in the virtual book so that I can see the risk figures react.

Given the active symbol has a fresh quote, when I open the ticket, choose a side and a quantity within cash and position and confirm, then the order fills at the frozen mark, the trade log gains one row, and cash, positions and P&L update at the next poll.

Given the quote is stale or absent, when I confirm, then the order is refused with the reason and the book is unchanged.

Given a buy would take cash below zero or a sell exceeds the position, when I confirm, then the order is refused and the book is unchanged.

### Read the risk panel

As the analyst I want each figure to state what it is so that I never confuse two percentages for the same holding.

Given the book holds positions with cached daily history, when the panel renders after the nightly history refresh, then the analytics section shows the figures FR-21 lists, each with its window, basis and as-of date.

Given a held stock has no history because the Tiingo key is missing, when the section renders, then it names the missing key instead of a figure.

Given the value history holds fewer than two returns, when the panel renders, then volatility reads as warming (not enough samples yet) rather than a number.

### Set an alert

As the analyst I want a one-shot alert so that I am told once when a condition is met.

Given the active symbol has a fresh quote, when I arm a price threshold, then the alert is saved, listed as armed, and fires once with a toast (a short notice in the corner of the window) when the mark reaches the level, after which it shows as fired until I re-arm it.

Given an identical alert already exists or twenty alerts are armed, when I arm another, then it is refused with the reason.

Given the quote goes stale, when the worker evaluates alerts, then none fire and the panel shows alerts as paused.

### Export a report

As the reader I want the book's figures in a file so that I can use them without opening the window.

Given the program has run at least once and the book holds positions with cached history, when I run `python -m mahad.report`, then a CSV with the columns metric, value, unit, basis, window, as_of and note is written, the headline figures print on screen, and the values equal the engine's outputs on the same inputs.

Given the database is missing or the book is empty, when I run the report, then it prints a plain reason and exits with code 1 without creating a file.

Given the program is running, when I run the report, then it reads the database in read-only mode and the program keeps writing undisturbed.

## Assumptions and constraints

The book is USD only and long only; short positions and margin are not modelled. Marks come from the latest quote in the window and from the last cached daily close in the report, and each surface says which. Free-tier providers limit calls, so the worker paces Finnhub at 55 calls a minute and refreshes history nightly. The trading-day series follows the NYSE calendar, so a crypto bar on a weekend folds into the following trading day. The risk formulas are pinned to the verification vectors and are not changed without a new vector. The program is single-user and single-machine; the database is one local file with one writer.

## Traceability matrix

| Requirement | Test file(s) | Test count |
|---|---|---|
| FR-01 | test_market_data_providers.py, test_worker_scheduling.py | 4 |
| FR-02 | test_market_data_providers.py, test_worker_scheduling.py | 4 |
| FR-03 | test_market_data_providers.py, test_market_context.py, test_fx_rates_providers.py | 6 |
| FR-04 | test_normalisation.py, test_fuzz.py | 4 |
| FR-05 | test_normalisation.py, test_robustness.py | 3 |
| FR-06 | test_market_data_providers.py | 4 |
| FR-07 | test_chart_timeframes.py, test_resample.py | 5 |
| FR-08 | test_indicators.py, test_persistence.py | 6 |
| FR-09 | test_market_session.py | 5 |
| FR-10 | test_persistence.py, test_invalid_entry.py, test_fuzz.py | 6 |
| FR-11 | test_validate_add_probe.py | 3 |
| FR-12 | test_watchlist_remove.py | 3 |
| FR-13 | test_persistence.py | 2 |
| FR-14 | test_portfolio.py, test_robustness.py, test_spam_inputs.py | 7 |
| FR-15 | test_portfolio.py, test_fuzz.py | 6 |
| FR-16 | test_portfolio.py, test_fuzz.py, test_stress.py | 6 |
| FR-17 | test_portfolio.py, test_fuzz.py, test_worker_context.py | 4 |
| FR-18 | test_persistence.py, test_worker_analytics.py, test_spam_inputs.py | 5 |
| FR-19 | test_worker_context.py, test_persistence.py | 4 |
| FR-20 | test_risk.py, test_fuzz.py, test_risk_metrics.py | 7 |
| FR-21 | test_risk_metrics.py | 13 |
| FR-22 | test_worker_analytics.py, test_returns.py | 5 |
| FR-23 | test_worker_analytics.py, test_risk_metrics.py | 6 |
| FR-24 | test_worker_daily.py, test_daily_bar_migration.py | 5 |
| FR-25 | test_analytics_ui.py, test_worker_analytics.py | 3 |
| FR-26 | test_market_context.py, test_fx_rates_providers.py, test_worker_context.py | 9 |
| FR-27 | test_worker_context.py | 2 |
| FR-28 | test_fx_rates_providers.py | 2 |
| FR-29 | test_signals.py, test_persistence.py | 4 |
| FR-30 | test_signals.py, test_worker_switch.py | 3 |
| FR-31 | test_robustness.py, test_persistence.py | 4 |
| FR-32 | test_persistence.py, test_daily_bar_migration.py | 6 |
| FR-33 | test_robustness.py, test_context_wiring_guards.py | 5 |
| FR-34 | test_daily_bar_migration.py | 4 |
| FR-35 | test_market_context.py, test_market_data_providers.py, test_context_wiring_guards.py | 5 |
| FR-36 | test_context_wiring_guards.py | 1 |
| FR-37 | test_security.py | 4 |
| FR-38 | test_portfolio.py, test_market_context.py, test_fx_rates_providers.py | 3 |
| FR-39 | test_report.py | 6 |
| FR-40 | test_command_palette.py, test_context_wiring_guards.py | 3 |
| NFR-01 | test_market_data_providers.py, test_worker_context.py, the Windows CI jobs | 2 |
| NFR-02 | test_context_wiring_guards.py | 1 |
| NFR-03 | test_report.py, the Ubuntu CI jobs | 1 |
| NFR-04 | test_analytics_ui.py, test_ui_layout_guards.py | 5 |
| NFR-05 | test_perf.py | 9 |
| NFR-06 | test_robustness.py, test_worker_switch.py, test_worker_context.py | 5 |
| NFR-07 | test_stress.py | 6 |
| NFR-08 | test_robustness.py, test_fuzz.py | 3 |
| NFR-09 | test_ui_layout_guards.py, test_spam_inputs.py, manual check | 2 |
| NFR-10 | the CI matrix, manual check | 0 |
| NFR-11 | test_context_wiring_guards.py, test_signals.py | 2 |
