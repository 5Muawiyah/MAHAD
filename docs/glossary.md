# Glossary

Plain-English definitions of the terms the MAHAD documents use, in alphabetical order.

**2s10s.** The difference between the ten-year and two-year US Treasury yields, in basis points. A negative value (an inverted curve) has often preceded recessions; the context tile calls under 25 basis points flat and anything wider normal.

**Adapter.** A small module that talks to one data provider and turns its answers into the program's own `Quote` and `Candle` shapes. Each adapter returns failures as values rather than raising exceptions.

**Adjusted close.** A daily closing price restated so that dividends and share splits do not show up as price moves. Stock history from Tiingo is used in this form.

**Backcast.** Running the trailing-window VaR day by day across the cached history with today's weights, to fill the backtest before 250 live forecasts have accrued. The panel labels it so it is never mistaken for the live series.

**Backtest.** A check of the VaR model against what happened: each day's forecast is compared with the next day's realised return, and a loss beyond the forecast counts as an exception.

**Bank Rate.** The Bank of England's official interest rate.

**Basel traffic light.** The supervisory reading of a 99% VaR backtest over 250 days: green for 0 to 4 exceptions, yellow for 5 to 9, red for 10 or more.

**Basis.** The return series a figure is computed on. MAHAD keeps two: the wall-clock basis (the portfolio's own value sampled on a fixed cadence) and the trading-day basis (daily returns aligned to the US trading calendar). Every figure is labelled with its basis.

**Beta.** How much the portfolio moves for a given move in a benchmark, here the SPY fund: the covariance of the two return series divided by the benchmark's variance.

**Candle.** One bar of price history: the open, high, low and close over a period, with the volume traded. The last candle is usually still forming.

**Component VaR.** A split of the portfolio's parametric VaR across its positions so that the parts add up to the whole. A hedge shows a negative share.

**Concentration.** How lopsided the book is. Measured with the HHI on position weights and, when sector names are known, on sector weights.

**Coverage weight.** The share of the portfolio's value whose assets have usable daily history. Figures computed on partial coverage say so.

**Drawdown.** The fall from a running peak to a later low, as a percentage. Maximum drawdown is the worst such fall in the series; drawdown duration is how long the value took to climb back, or how long it has been under water.

**Effective N.** One divided by the HHI: the number of equal-sized positions that would give the same concentration.

**EWMA.** Exponentially weighted moving average. Applied to squared returns with a decay of 0.94 it gives a volatility estimate that leans on recent days, the RiskMetrics convention.

**Ex-ante.** Computed in advance. An ex-ante backtest series is one where every forecast was recorded before the day it covered.

**Expected Shortfall (ES).** The average loss on the days that breach the VaR. At the same confidence it is never smaller than the VaR. MAHAD reports it at 97.5%, the level the Basel market-risk rules moved to.

**Exposure.** The value held in positions as a share of the whole portfolio, cash included.

**Fear and Greed index.** A daily crypto sentiment score from 0 (extreme fear) to 100 (extreme greed) published by alternative.me.

**Fixture.** A captured provider payload or a small known data set stored with the tests, so the adapters and calculations are checked against real shapes without any network.

**Forming bar.** The candle for the current period, which changes until the period ends. Indicators and alerts ignore it.

**HHI.** The Herfindahl-Hirschman Index: the sum of the squared weights. It runs from 1/n for n equal positions to 1 for a single holding.

**Historical VaR.** VaR read from the sorted past returns: at confidence c over T days the program takes the m-th worst day, with m = floor((1 - c) x T) + 1, and reports its loss.

**Intent.** A request from the window to the worker, such as add a symbol, place an order or arm an alert. Intents are queued to the worker thread and answered with events or a fresh snapshot.

**Kupiec test.** A statistical test of whether the number of backtest exceptions matches the confidence level. Too many and too few both fail it.

**Mark.** The current price used to value a position. For the live window it is the latest quote; for the headless report it is the last cached daily close.

**Mixin.** A class that holds a group of methods for another class to combine. The worker package uses one per responsibility, all sharing the state of the single worker object.

**Order statistic.** The k-th smallest value in a sorted sample. Historical VaR and Expected Shortfall are order statistics, which is why they can be reproduced by hand.

**Parametric VaR.** VaR computed from the mean and standard deviation of returns on the assumption that they are normally distributed.

**Provider.** An external service the program reads prices or reference data from: Finnhub, Tiingo, Kraken, Frankfurter, the US Treasury, FRED, the Bank of England and alternative.me.

**Quote.** The latest price of a symbol with its timestamp and source, and a flag when it has gone stale.

**Read model.** A frozen record the worker builds for the window to display, such as the watchlist state or the risk view. The window reads them and never computes figures itself.

**Repository.** The one module that reads and writes the SQLite database, through SQLAlchemy. Only the worker thread and the headless report use it.

**Risk-free rate.** The return available without risk, used by the Sharpe ratio. MAHAD uses the US Treasury three-month yield from the context tiles, de-annualised over 252 trading days.

**RSI.** The relative strength index, a momentum gauge from 0 to 100 built from the average size of recent gains and losses, smoothed the way Wilder described in 1978.

**Sharpe ratio.** The average return above the risk-free rate divided by the standard deviation of that excess return, annualised over 252 trading days.

**Simulated order.** A buy or sell that changes only the virtual portfolio. It fills at the live mark and is recorded in the trade log; no order goes anywhere.

**Snapshot.** The complete picture the worker sends to the window after each poll: chart points, indicator lines, the portfolio, the risk figures, the context tiles and the health state. Each one is complete, so the newest always wins.

**SONIA.** The Sterling Overnight Index Average, the UK's overnight interest-rate benchmark.

**Sortino ratio.** Like the Sharpe ratio but dividing by the downside deviation only, so upside swings are not counted as risk.

**Stale.** A quote older than three poll intervals or fifteen seconds, whichever is longer. Stale prices are still shown, dimmed, and alerts pause until a fresh one arrives.

**Stress replay.** A what-if that applies a past window's returns, such as February to March 2020, to today's weights to show the loss the book would have taken.

**Timeframe.** The size of a chart bar: one minute, one hour, one day, three days, one week or one month.

**Trading-day basis.** Returns measured from one US trading day's close to the next, with weekends and holidays folded into the following day. The analytics section runs on this basis and annualises with 252 days.

**Value-at-Risk (VaR).** The loss that a stated share of days should not exceed. A 95% one-day VaR of 1,934 USD means that on about one day in twenty the loss is expected to be worse than that.

**VIX.** The CBOE volatility index, a market-implied measure of expected S&P 500 volatility over the next 30 days. The context tile bands it as calm, normal, elevated or extreme.

**WAL.** Write-ahead logging, an SQLite mode in which readers and the single writer do not block each other. The database runs in this mode so the report can read while the program writes.

**Wall-clock basis.** Returns measured between samples of the portfolio's own value taken on a fixed cadence, including weekends for crypto. The headline volatility and drawdown use this basis and annualise with calendar periods.

**Watchlist.** The symbols being followed, each with its latest price. One of them is the active symbol shown on the chart.

**Worker.** The single background thread that fetches prices, runs the maths, writes the database and publishes snapshots and events to the window.
