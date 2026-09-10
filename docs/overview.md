# MAHAD in plain English

MAHAD is a desktop program that watches live market prices and shows how much a portfolio of shares and cryptocurrency could lose. The portfolio is a simulation: it starts with 100,000 virtual US dollars, no real money is involved, and nothing is ever sent to a broker.

## Who it is for

MAHAD is for anyone who wants to see how a risk desk's figures are produced and to check them: an analyst can run it on live prices, and a reader can follow the documents, where every figure has a stated method and a test. Risk teams in banks and funds run software that answers one question all day: how much could we lose if prices move against us, and how sure are we. That maths usually sits inside expensive desk systems where nobody outside the team sees it. MAHAD runs the standard calculations on a laptop, on real prices, so the figures can be checked line by line. The [methodology note](risk-methodology.md) states every formula, and the [verification note](verification.md) gives the hand-worked answers the tests check the program against.

## A guided tour

![The MAHAD dashboard](images/dashboard.png)

The chart of the active symbol fills the left, with the price in the corner (here Apple at 312.06 USD, up 0.59% on the previous close); the watchlist and the risk panel sit on the right. Along the bottom are three tabs: alerts, the portfolio and the trade log. The portfolio tab shows cash, total value, and profit and loss split into realised and unrealised.

![Price chart with SMA, EMA and RSI](images/chart.png)

The chart draws the closing price with two moving averages laid over it, a simple 20-day average and an exponential 12-day one, and below it the 14-day relative strength index, a gauge between 0 and 100 that traders read as overbought above 70 and oversold below 30. The row of buttons at the top left of the main window (1m to 1mo) sets how much time each bar covers, from one minute to one month. Every line is drawn on completed bars only.

![Watchlist](images/watchlist.png)

The watchlist holds the symbols being followed, each with its latest price and a green dot when that price is fresh. Clicking a row makes it the active chart. Crypto pairs such as BTC/USD need no account or key, so a live chart appears as soon as the program opens.

![Risk analytics panel](images/risk-analytics.png)

The top of the panel shows exposure (how much of the portfolio's value is in positions rather than cash), the volatility of the portfolio's own value, and its worst fall from a peak. The analytics section below runs the desk-style measures on the last 250 trading days: Value-at-Risk at two confidence levels, Expected Shortfall, the parametric versions of the same, beta against the S&P 500 fund SPY, the Sharpe and Sortino ratios, a recent-weighted (EWMA) volatility, concentration, a grid of how closely the holdings move together, the traffic-light backtest, each position's share of the risk, and three replayed shocks such as the 2020 COVID crash. Each is explained under What the numbers mean below and in the [glossary](glossary.md).

![The risk panel with the market context section open](images/market-context.png)

The market context section gives the backdrop: the US Treasury 10-year yield and the gap between two-year and ten-year yields (35 basis points, or 0.35 percentage points, a normal upward slope), the VIX fear gauge, the crypto Fear and Greed index (9, extreme fear), and the two UK rates, SONIA (the sterling overnight rate) and the Bank of England's Bank Rate.

![Simulated order ticket](images/order-ticket.png)

The order ticket places a simulated buy or sell at the live price. The ticket says so on its face: no real order is placed. The trade lands in the virtual portfolio and the figures update at the next price refresh.

![Alerts tab](images/alerts.png)

An alert watches for a condition, such as the price crossing 320 USD or the 20-day average crossing below the 12-day one. It fires once, shows a notification and stays listed as fired until re-armed.

![Command palette](images/command-palette.png)

Ctrl+Shift+P opens a searchable list of every command and its shortcut.

## What the numbers mean

Value-at-Risk (VaR) is the loss that a bad day would reach or exceed, at a stated confidence. Take the worked example from the verification note: a 100,000 USD portfolio whose daily returns average 0.04% with a volatility of 1.2%. The 95% one-day parametric VaR comes out at 1.9338% of the portfolio, or 1,933.82 USD. Read it as "on nineteen days in twenty the loss should stay under 1,934 USD; on about one day in twenty it will be worse." Parametric means it comes from the mean and volatility, assuming a bell curve.

Historical VaR skips that assumption and reads the figure straight from what happened. With 100 days of returns at 95%, the program sorts the days from worst to best and takes the sixth worst: in the worked vector that day lost 2.50%, so that's the VaR. Expected Shortfall answers a harder question, how bad the bad days are on average: it averages the six worst days, 3.4667% in the same vector, and is always at least as large as the VaR it pairs with.

The backtest checks the VaR against what happened: at 99% over 250 trading days the loss should breach it two or three times. The Basel traffic light, which banking supervisors use, calls up to four breaches green, five to nine yellow and ten or more red; the Kupiec test asks the same question statistically and also flags a model that breaches too rarely.

Drawdown is the fall from a peak. A value that goes 100, 110, 99, 104.5, 112, 108 has a maximum drawdown of minus 10%, the fall from 110 to 99. Concentration uses the Herfindahl-Hirschman Index: weights of 50%, 30% and 20% give 0.38, equivalent to about 2.6 equal positions. Beta says how much the portfolio moves with the market: 1.16 means a 1% market move tends to bring a 1.16% move. Sharpe and Sortino divide the return above a risk-free rate by the variation it took to earn it; Sortino counts only downside variation.

## Where the data comes from

| What | From | How often | Access |
|---|---|---|---|
| Live stock quotes and sector names | Finnhub | every 5 seconds for the chart symbol, within 55 calls a minute | free key |
| Stock daily history, adjusted for dividends and splits | Tiingo | nightly, plus one pull of recent minute and hour bars per symbol | free key |
| Crypto prices and daily bars | Kraken public endpoints | every 5 seconds for the chart symbol, daily bars nightly | no key |
| USD to GBP reference rate | Frankfurter (the European Central Bank's rate) | every 12 hours | no key |
| Treasury yield curve | US Treasury | every 12 hours | no key |
| VIX | FRED | every 12 hours | free key |
| SONIA and Bank Rate | Bank of England | every 12 hours | no key |
| Crypto Fear and Greed index | alternative.me | every 12 hours | no key |

The three keys are free sign-ups, kept in a local `.env` file that git ignores and never logged; none of them can trade or move money.

## What it deliberately is not

MAHAD holds no brokerage account and cannot place a real order; it calls only Kraken's public, read-only endpoints. The portfolio is a teaching simulation and the figures are not investment advice.

## The report export

`python -m mahad.report` writes the portfolio's risk figures to a CSV file without opening the window. It reads the same database the program writes, in read-only mode, so it can run while the program is open. Every row states the metric, its value and unit, the period it covers, the series it was measured on, the date, and a note when the database lacks something the figure needs.

## How to run it

1. Install Python 3.11, 3.12 or 3.13 and clone the repository.
2. On Windows double-click `MAHAD.bat`; on macOS or Linux run `bash run.sh`. The first run creates its own environment.
3. Add a symbol. Crypto works at once; for stocks, copy `.env.example` to `.env` and paste in the free Finnhub and Tiingo keys.

## Where to read next

The [technical guide](architecture.md) explains how the program is built and tested. The [requirements document](requirements.md) lists what it does and which test proves each point. The [data dictionary](data-dictionary.md) describes the database and every figure. The [glossary](glossary.md) defines the terms used here.
