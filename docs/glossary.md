# Glossary

Plain-English definitions of the terms the MAHAD documents use, in alphabetical order.

### 2s10s

The difference between the ten-year and two-year US Treasury yields, in basis points. A negative value (an inverted curve) has often preceded recessions; the context tile calls a negative spread inverted, under 25 basis points flat and anything wider normal.

### Adapter

A small module that talks to one data provider and turns its answers into the program's own `Quote` and `Candle` shapes. Each adapter returns failures as values rather than raising exceptions.

### Adjusted close

A daily closing price restated so that dividends and share splits do not show up as price moves. Stock history from Tiingo is used in this form.

### As-if portfolio return

The daily return the book would have earned on a past day with today's weights held across it. The analytics run on this series so that a trade today does not rewrite yesterday's risk.

### Asset class

A kind of investment; here the two are shares and crypto.

### Backcast

Running the trailing-window VaR day by day across the cached history with today's weights, to fill the backtest before 250 live forecasts have accrued. The panel labels it so it is never mistaken for the live series.

### Backtest

A check of the VaR model against what happened: each day's forecast is compared with the next day's realised return, and a loss beyond the forecast counts as an exception.

### Bank Rate

The Bank of England's official interest rate.

### Basel traffic light

The supervisory reading of a 99% VaR backtest over 250 days: green for 0 to 4 exceptions, yellow for 5 to 9, red for 10 or more. Each colour is a zone, which is how the requirements and the report name it.

### Basis

The return series a figure is computed on. MAHAD keeps two: the wall-clock basis (the portfolio's own value sampled on a fixed cadence) and the trading-day basis (daily returns aligned to the US trading calendar). Every figure is labelled with its basis.

### Basis point

One hundredth of a percentage point: 35 basis points is 0.35 percentage points.

### Beta

How much the portfolio moves for a given move in a benchmark, here the SPY fund, which tracks the S&P 500: the covariance of the two return series divided by the benchmark's variance.

### Book

The portfolio as a desk calls it: the cash and the positions the ledger holds.

### Candle

One bar of price history: the open, high, low and close over a period, with the volume traded. The last candle is usually still forming.

### Chip

A small rounded label on the panel that carries a state in words, such as the backtest zone reading "GREEN" with its count.

### CI

Continuous integration: the GitHub Actions workflow in `.github/workflows/tests.yml` that runs the checks and the suite on pushes to main and on pull requests, on Ubuntu and Windows across Python 3.11, 3.12 and 3.13.

### Component VaR

A split of the portfolio's parametric VaR across its positions so that the parts add up to the whole. A hedge shows a negative share.

### Concentration

How lopsided the book is. Measured with the HHI on position weights and, when sector names are known, on sector weights.

### Coverage weight

The share of the portfolio's value whose assets have usable daily history. Figures computed on partial coverage say so.

### Drawdown

The fall from a running peak to a later low, as a percentage. Maximum drawdown is the worst such fall in the series; drawdown duration is how long the value took to climb back, or how long it has been under water.

### Effective N

One divided by the HHI: the number of equal-sized positions that would give the same concentration.

### EMA

Exponential moving average: a price average that weights recent bars more, seeded from the simple average of the first period. The chart overlays a 12-bar EMA by default.

### EWMA

Exponentially weighted moving average. Applied to squared returns with a decay of 0.94 (each day's weight is 0.94 times the next day's) it gives a volatility estimate that leans on recent days, the convention JP Morgan's RiskMetrics service set in the 1990s.

### Ex-ante

Computed in advance. An ex-ante backtest series is one where every forecast was recorded before the day it covered.

### Expected Shortfall (ES)

The average loss over the worst days in the window, the VaR day included, so at the same confidence it is never smaller than the VaR. MAHAD reports it at 97.5%, the level the Basel market-risk rules moved to.

### Exposure

The value held in positions as a share of the whole portfolio, cash included.

### Fear & Greed index

A daily crypto sentiment score from 0 (extreme fear) to 100 (extreme greed) published by alternative.me.

### Fixture

A captured provider payload or a small known data set stored with the tests, so the adapters and calculations are checked against real shapes without any network.

### Forming bar

The candle for the current period, which changes until the period ends. Indicators and alerts ignore it.

### Headless

Running without a window: the test suite and the report export both run this way, with no display and no Qt widgets.

### Heartbeat

The worker's five-second timer that drives the slow work off a wall-clock grid: sampling the portfolio value, refreshing one context source, refreshing one symbol's daily history, rebuilding the analytics.

### HHI

The Herfindahl-Hirschman Index: the sum of the squared weights. It runs from 1/n for n equal positions to 1 for a single holding.

### Historical VaR

VaR read from the sorted past returns: at confidence c over T days the program takes the m-th worst day, with m = floor((1 - c) x T) + 1, and reports its loss.

### Intent

A request from the window to the worker, such as add a symbol, place an order or arm an alert. Intents are queued to the worker thread and answered with events or a fresh snapshot.

### JSON

The text format the settings values and the alert parameters are written in.

### Kupiec test

A statistical test of whether the number of backtest exceptions matches the confidence level, reported as a likelihood ratio with its p-value. Too many and too few both fail it.

### Likelihood ratio

The Kupiec test's statistic: it compares how likely the observed number of exceptions is at the model's confidence level with how likely it is at the rate actually seen, and a large value fails the model.

### Mark

The current price used to value a position. For the live window it is the latest quote; for the headless report it is the last cached daily close.

### Mixin

A class that holds a group of methods for another class to combine. The worker package uses one per responsibility, all sharing the state of the single worker object.

### OpenGL

The graphics library a Qt window draws with. The Ubuntu CI runners lack it, so the suite runs there without a window.

### Order statistic

The k-th smallest value in a sorted sample. Historical VaR is an order statistic and Expected Shortfall the mean of the lowest m, which is why both can be reproduced by hand.

### Overbought

An RSI reading above 70: the price has risen fast enough that a pause or a fall is more likely than usual.

### Oversold

An RSI reading below 30: the price has fallen fast enough that a bounce is more likely than usual.

### P&L

Profit and loss. Realised P&L is booked when a sell closes part of a position; unrealised P&L is the gain or loss on the positions still open at the current mark.

### p-value

The chance of a result at least as extreme as the one observed if the model were right; a small p-value means the exception count is unlikely under the model, and the Kupiec test fails it.

### Parametric VaR

VaR computed from the mean and standard deviation of returns on the assumption that they are normally distributed.

### Provider

An external service the program reads prices or reference data from: Finnhub, Tiingo, Kraken, Frankfurter, the US Treasury, FRED (the Federal Reserve Bank of St. Louis's data service), the Bank of England and alternative.me.

### Qt

The desktop window toolkit MAHAD's screen is built with; PySide6 is its Python form.

### Quote

The latest price of a symbol with its timestamp and source, and a flag when it has gone stale.

### Read model

A frozen record the worker builds for the window to display, such as the watchlist state or the risk view. The window reads them and never computes figures itself.

### Repository

The one module that reads and writes the SQLite database, through SQLAlchemy. Only the worker thread and the headless report use it.

### Return on VaR

The book's realised plus unrealised P&L divided by its 95% one-day VaR in USD: how many worst-case days the gains so far amount to.

### Risk-free rate

The return available without risk, used by the Sharpe ratio. MAHAD uses the US Treasury three-month yield from the context tiles, de-annualised over 252 trading days.

### Rolling VaR

Historical VaR recomputed on a 60-trading-day window stepped across the history, 40 points, so the panel can show how the figure has moved.

### RSI

The relative strength index, a momentum gauge from 0 to 100 built from the average size of recent gains and losses, smoothed the way Wilder described in 1978.

### Sharpe ratio

The average return above the risk-free rate divided by the standard deviation of that excess return, annualised over 252 trading days.

### Simulated order

A buy or sell that changes only the virtual portfolio. It fills at the live mark and is recorded in the trade log; no order goes anywhere.

### SMA

Simple moving average: the plain average of the last n closing prices. The chart overlays a 20-bar SMA by default.

### Snapshot

The complete picture the worker sends to the window after each poll: chart points, indicator lines, the portfolio, the risk figures, the context tiles and the health state. Each one is complete, so the newest always wins.

### SONIA

The Sterling Overnight Index Average, the UK's overnight interest-rate benchmark.

### Sortino ratio

The mean return, measured against a zero target rather than a risk-free rate, divided by the downside deviation only, so upside swings are not counted as risk; annualised over 252 trading days.

### Split

A company dividing each of its shares into several, which lowers the price per share; adjusted history removes the jump so it does not look like a price move.

### SQLAlchemy

The Python library the repository uses to read and write the SQLite database.

### SQLite

The database engine MAHAD stores its data in: one file on the machine, with no server to run.

### Stale

A quote older than three poll intervals or fifteen seconds, whichever is longer. Stale prices are still shown, dimmed, and alerts pause until a fresh one arrives.

### Stress replay

A what-if that applies a past window's returns, such as February to March 2020, to today's weights to show the loss the book would have taken.

### Tick

One cycle of a worker timer: a poll of the active symbol or a beat of the heartbeat, both every five seconds by default.

### Timeframe

The size of a chart bar: one minute, one hour, one day, three days, one week or one month.

### Toast

A short notice that appears in the corner of the window and fades, used when an alert fires. A refused order shows its reason on the ticket instead, or in the status bar once the ticket has closed.

### Trading-day basis

Returns measured from one US trading day's close to the next, with weekends and holidays folded into the following day. The analytics section runs on this basis and annualises with 252 days.

### Value history

The portfolio's own value sampled on a fixed cadence (one minute, one hour or one day) while the program runs, kept to the newest 1,000 samples. The headline volatility, the maximum drawdown and the drawdown duration are computed on it.

### Value-at-Risk (VaR)

The loss that a stated share of days should not exceed. A 95% one-day VaR of 1,934 USD means that on about one day in twenty the loss is expected to be worse than that.

### Verification vector

A worked example with fixed inputs and an answer computed by hand, tabled in the verification note; the tests pin each formula to its vector.

### VIX

The Chicago Board Options Exchange (CBOE) volatility index, a market-implied measure of expected S&P 500 volatility over the next 30 days. The context tile bands it with the labels "calm", "normal", "elevated" and "extreme".

### WAL

Write-ahead logging, an SQLite mode in which readers and the single writer do not block each other. The database runs in this mode so the report can read while the program writes.

### Wall-clock basis

Returns measured between samples of the portfolio's own value taken on a fixed cadence, including weekends for crypto. The headline volatility and drawdown use this basis and annualise with calendar periods.

### Warming

A not-yet state: a watchlist symbol that is listed but has no price yet, an analytics figure short of its minimum observations, or the risk panel header while the value history has fewer than two returns.

### Watchlist

The symbols being followed, each with its latest price. One of them is the active symbol shown on the chart.

### WCAG AA

The AA level of the Web Content Accessibility Guidelines: text must contrast with its background by at least 4.5 to 1 for normal text.

### Worker

The single background thread that fetches prices, runs the maths, writes the database and publishes snapshots and events to the window.
