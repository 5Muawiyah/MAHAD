# Data dictionary

The SQLite schema the application writes, the provider fields it consumes and how they normalise, the figures it derives, and the columns of the four CSV exports.

## The SQLite schema

The file is `~/.mahad/mahad.db`, opened in WAL mode with foreign keys on. Money and quantities are stored as text and read back as exact `Decimal` values. Timestamps are epoch seconds (seconds since 1 January 1970, UTC) stored as floats. Every foreign key cascades on delete except a trade's link to its symbol, which is set to null so the trade log survives a symbol's removal.

### symbols

One row per instrument the application has seen, watchlisted or not.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 1 |
| ticker | VARCHAR(40) | the symbol as typed, upper-cased; crypto is BASE/QUOTE | AAPL, BTC/USD |
| asset_class | VARCHAR(16) | stock or crypto | stock |
| provider | VARCHAR(24) | the adapter that serves it | finnhub, kraken |
| quote_currency | VARCHAR(8) | always USD in this version | USD |
| display_name | VARCHAR(80) | the label shown; the ticker | AAPL |
| active | BOOLEAN | true for the one symbol on the chart | 1 |
| created_at | FLOAT | epoch seconds when first seen | 1749650000.0 |

Unique on (ticker, provider); indexed on ticker.

### watchlist

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 1 |
| symbol_id | INTEGER, unique | the symbols row | 1 |
| added_at | FLOAT | epoch seconds; rows list in this order | 1749650000.0 |

### settings

A key-value store. Values are JSON text and are validated when read; a corrupt value falls back to the default.

| Column | Type | Meaning | Example |
|---|---|---|---|
| key | VARCHAR(64), primary key | the setting name | indicators |
| value | TEXT | JSON | {"sma_enabled": true, "sma_period": 20, ...} |
| value_type | VARCHAR(16) | always json | json |

Keys in use: `indicators` (the overlay settings), `risk_timeframe` (1m, 1h or 1d), `market_context` (the cached context tiles), `sector_map` (sector names from Finnhub) and `schema_migration` (the marker that the one-time migration ran).

### alerts

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 3 |
| symbol_id | INTEGER, indexed | the symbols row | 1 |
| condition_type | VARCHAR(32) | price_threshold, rsi_threshold, price_sma_cross or sma_ema_cross | price_threshold |
| params | TEXT | canonical JSON with sorted keys, used to block duplicates | {"level":320.0} |
| direction | VARCHAR(8) | up or down | up |
| armed | BOOLEAN | false once fired, true again after re-arm | 1 |
| fired_at | FLOAT, nullable | epoch seconds of the fire | null |
| created_at | FLOAT | epoch seconds | 1749650100.0 |

At most 20 rows; the cap is enforced in the repository.

### portfolio

The single virtual book. One row, created on first run with the starting cash and the peak seeded at that value.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 1 |
| name | VARCHAR(40) | the book's name | paper |
| base_currency | VARCHAR(8) | always USD | USD |
| starting_cash | TEXT (Decimal) | the opening cash | 100000 |
| cash | TEXT (Decimal) | cash now, to the cent | 46460.00 |
| realised_pnl | TEXT (Decimal) | the sum of realised trade results | -300.00 |
| peak_value | TEXT (Decimal), nullable | the all-time high of the portfolio value | 103120.55 |
| peak_ts | FLOAT, nullable | epoch seconds of that peak | 1750250000.0 |
| created_at | FLOAT | epoch seconds | 1749650000.0 |
| reset_at | FLOAT, nullable | epoch seconds of the last reset | null |

### positions

Open long positions (holdings bought and not yet sold); a row is deleted when its quantity reaches zero.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 2 |
| portfolio_id | INTEGER, indexed | the portfolio row | 1 |
| symbol_id | INTEGER, indexed | the symbols row | 1 |
| quantity | TEXT (Decimal) | units held, up to 8 decimal places | 100, 0.30000000 |
| avg_cost | TEXT (Decimal) | average cost per unit at full precision | 308.00 |
| opened_at | FLOAT | epoch seconds | 1749650200.0 |

Unique on (portfolio_id, symbol_id).

### trades

Rows are never updated or removed singly. The table is emptied in two ways, both only after a successful export: the trade-log panel's Clear control, which the worker honours only while the log still holds the exported count, and a reset that asked to clear the log. Each row carries its own symbol string so the CSV export needs no lookup in the symbols table.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 7 |
| portfolio_id | INTEGER, indexed | the portfolio row | 1 |
| symbol_id | INTEGER, nullable, indexed | the symbols row, null once the symbol is removed | 1 |
| symbol | VARCHAR(40) | the ticker at the time of the fill | AAPL |
| side | VARCHAR(8) | buy or sell | buy |
| quantity | TEXT (Decimal) | units filled | 100 |
| fill_price | TEXT (Decimal) | the mark the order filled at | 308.00 |
| avg_cost_at_fill | TEXT (Decimal) | the average cost the fill was measured against: the new blended average on a buy, the average the position carried before the fill on a sell | 308.00 |
| qty_before | TEXT (Decimal) | position size before | 0 |
| qty_after | TEXT (Decimal) | position size after | 100 |
| realised_pnl | TEXT (Decimal) | the result booked by this fill; zero on a buy | 0.00 |
| ts | FLOAT, indexed | epoch seconds of the fill | 1749650200.0 |

### value_history

The portfolio's value sampled on the risk timeframe, pruned to the newest 1,000 rows.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 512 |
| portfolio_id | INTEGER, indexed | the portfolio row | 1 |
| ts | FLOAT, indexed | epoch seconds on the sample grid | 1750291200.0 |
| portfolio_value | TEXT (Decimal) | cash plus positions at the marks | 99728.54 |
| cash | TEXT (Decimal) | cash at the sample | 46460.00 |
| positions_value | TEXT (Decimal) | quantity times mark, summed | 53268.54 |
| stale | BOOLEAN | true when any mark was stale or missing | 0 |

### daily_bars

The cached daily history per symbol: adjusted stock bars from Tiingo and daily candles from Kraken.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 9001 |
| symbol_id | INTEGER, indexed | the symbols row | 1 |
| ts | FLOAT, indexed | epoch seconds at UTC midnight of the trading day | 1749600000.0 |
| open, high, low, close | FLOAT | the raw prices | 310.12 |
| adj_close | FLOAT | the close adjusted for dividends and splits; equals close for crypto | 310.12 |
| volume | FLOAT | units traded; zero when unknown | 51234567.0 |
| div_cash | FLOAT | cash dividend on the day; zero for crypto | 0.0 |
| split_factor | FLOAT | split factor on the day; 1.0 when none | 1.0 |

Unique on (symbol_id, ts).

### var_backtest

One row per forecast day. A row is resolved when the next trading day's realised return is known.

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | row id | 130 |
| portfolio_id | INTEGER, indexed | the portfolio row | 1 |
| forecast_ts | FLOAT, indexed | epoch seconds at UTC midnight of the forecast day | 1749600000.0 |
| var99_pct | FLOAT | the 99% one-day historical VaR as a loss fraction | 0.0182 |
| weights_json | TEXT | the position weights the forecast used | {"AAPL": 0.31, "BTC/USD": 0.22} |
| realised_pct | FLOAT, nullable | the next day's as-if portfolio return | -0.0041 |
| exception | BOOLEAN, nullable | true when realised_pct is below minus var99_pct | 0 |
| resolved_ts | FLOAT, nullable | epoch seconds when resolved | 1749700000.0 |

Unique on (portfolio_id, forecast_ts).

### schema_version

| Column | Type | Meaning | Example |
|---|---|---|---|
| id | INTEGER, primary key | always 1 | 1 |
| version | INTEGER | the schema version the file was created with | 1 |

A file whose version differs from the code's is backed up and recreated on open.

## Provider fields and how they normalise

`Quote` has the fields symbol, mark, ts (epoch seconds when received), source, stale and an optional exchange_ts (the venue's own price time). `Candle` has symbol, timeframe, ts (the bar's open time), open, high, low, close, volume and is_closed.

| Provider | Field | Becomes |
|---|---|---|
| Finnhub quote | `c` (current price) | `Quote.mark`, when it is a finite positive number |
| Finnhub quote | `t` (price time) | `Quote.exchange_ts`; a zero payload means an unknown symbol |
| Finnhub profile | `finnhubIndustry` | the sector name cached in the `sector_map` setting |
| Kraken Ticker | `c[0]` (the last trade), else the midpoint of `b[0]` (the best bid) and `a[0]` (the best ask) | `Quote.mark`; the pair key is matched back to the requested symbol through the XBT and XDG aliases (Kraken's older codes for BTC and DOGE) |
| Kraken OHLC (open, high, low, close bars) | `[time, open, high, low, close, vwap (volume-weighted average price), volume, count]` | a `Candle` per row after `normalize_ohlcv` drops malformed and non-positive rows, de-duplicates on (symbol, timeframe, ts), sorts, caps at 500 bars and flags the last row as forming |
| Tiingo daily | `date, open, high, low, close, adjClose, volume, divCash, splitFactor` | a `daily_bars` row; the analytics read `adj_close` |
| Tiingo IEX (its intraday feed) | `date, open, high, low, close, volume` | closed one-minute or one-hour `Candle` rows merged into the sampled series |
| Treasury CSV | `Date, 3 Mo, 2 Yr, 10 Yr, 30 Yr` | the yield-curve tile; the newest row carrying both the two-year and the ten-year yield |
| FRED | `observations[].date, value` | the VIX tile; a dot means a missing value and is skipped |
| alternative.me | `data[0].value, value_classification, timestamp` | the sentiment tile, rejected outside 0 to 100 |
| Frankfurter | `rates.GBP` or `rates.GBP.ECB`, `date` | the FX view, rejected outside 0.01 to 100 |
| Bank of England CSV | `IUDSOIA`, `IUDBEDR` columns with a date column | the UK-rates tile, the latest value per series |

Stock marks between polls are turned into one-minute, one-hour and one-day bars by `data/sampled_bars.py`: a mark opens a bucket at the period boundary, later marks update the high, low and close, and the bucket closes when a mark arrives in the next period.

## Derived figures

Formula references point at sections of the [methodology note](risk-methodology.md).

| Figure | Formula | Basis | Window | Unit |
|---|---|---|---|---|
| Exposure | Exposure | wall-clock | now | USD and fraction |
| Volatility | Volatility | wall-clock | the last 30 returns | percent per period and annualised |
| Maximum drawdown | Maximum drawdown | wall-clock | the value history, peak seeded from the portfolio row | percent |
| Historical VaR 95% and 99% | Historical VaR and Expected Shortfall | trading-day | 250 days | fraction and USD |
| Expected Shortfall 97.5% | Historical VaR and Expected Shortfall | trading-day | 250 days | fraction and USD |
| Parametric VaR 95% and 99% | Parametric (variance-covariance) VaR | trading-day | 250 days | fraction |
| Backtest exceptions and zone | Kupiec proportion-of-failures and the Basel traffic light | trading-day | 250 days at 99% | count and zone |
| Kupiec statistic | Kupiec proportion-of-failures and the Basel traffic light | trading-day | 250 days | likelihood ratio and p-value |
| EWMA volatility | EWMA volatility | trading-day | the window, seeded with its variance | percent per day |
| Beta | Beta | trading-day | the common dates in the window | ratio |
| Sharpe and Sortino | Sharpe and Sortino | trading-day | 250 days, annualised with 252 | ratio |
| Correlation and its summary | Correlation and concentration | trading-day | 90 observations | rho (the correlation coefficient) |
| HHI, effective N, sector HHI | Correlation and concentration | position weights now | now | index and count |
| Drawdown duration | Drawdown duration | wall-clock | the value history | periods |
| Component VaR and shares | Component VaR (Euler decomposition, the split whose parts add to the whole) | trading-day | 250 days at 95% | fraction, USD and share |
| Return on VaR | Return on VaR and rolling VaR | mixed: ledger P&L over the 95% VaR in USD | now | ratio |
| Rolling VaR | Return on VaR and rolling VaR | trading-day | 60-day windows, 40 points | fraction |
| Stress replay | Stress replay | scenario windows on cached closes, else the per-asset constants in `config.STRESS_CONSTANTS` | the scenario | USD |

## The other three exports

The window writes three more files, each self-contained so it reads back without the database.

| Export | Columns | Written by |
|---|---|---|
| Trade log | `ts, symbol, side, quantity, fill_price, avg_cost_at_fill, qty_before, qty_after, realised_pnl`, under a `# starting_cash,<amount>` line | `build_trade_csv` in `mahad/engine/portfolio.py` |
| Value history | `ts_iso_utc, ts_epoch, portfolio_value, stale` | `build_value_history_csv` in `mahad/data/portfolio_view.py` |
| Risk snapshot | `metric, value, units, convention, as_of` | `build_risk_snapshot_csv` in `mahad/data/portfolio_view.py` |

## The report CSV

`python -m mahad.report` writes one row per figure with these columns.

| Column | Meaning |
|---|---|
| metric | the figure's name, for example `var_hist`, `es975_hist`, `mark_AAPL`, `stress_COVID_crash` |
| value | the number, six decimal places for floats; empty when the database cannot support the figure |
| unit | USD, fraction, percent, ratio, rho, index, count, days, periods, zone, flag, p-value or statistic |
| basis | the formula and the series it ran on, in words |
| window | the observation window in trading days or returns, empty on rows that have none; the rules are below the table |
| as_of | the date of the newest data the figure used |
| note | why a value is empty, or what a figure was built from, for example which stress legs came from constants |

The window column holds four different figures. The analytics rows carry the analytics window, 250 trading days unless `--window` says otherwise. The three correlation rows carry 90 (`config.CORRELATION_WINDOW`) and the six backtest rows carry 250 (`config.RISK_WINDOW`), whatever `--window` was. The two volatility rows carry the configured 30 value-history returns (`config.VOLATILITY_WINDOW`) even when the history holds fewer. The column is empty on the portfolio_value, cash, positions_value, mark, exposure, P&L, concentration, stress, drawdown and value_samples rows.

The report values positions at the last cached daily close rather than a live quote; the portfolio value, positions value, mark and unrealised P&L rows say so in their basis column, and the figures built on them (exposure, concentration, the stress replays, the P&L ratios) inherit that mark.
