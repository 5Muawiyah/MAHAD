# MAHAD in plain English

MAHAD (Multi-Asset Heuristic Analytics Dashboard: several [asset classes](glossary.md), a bank risk team's rules of thumb, one screen) is a desktop program that watches live market prices and shows how much a portfolio of shares and cryptocurrency could lose. The portfolio is a simulation: it starts with 100,000 virtual US dollars, no real money is involved, nothing goes to a broker, and the figures are not investment advice.

## Who it is for

MAHAD is for anyone who wants to see how a risk team's figures are produced and check them: an analyst can run it on live prices, and a reader can follow the documents. On a laptop, with real prices, it runs the standard calculations that risk teams in banks and funds use to answer one question: how much could we lose if prices move against us, and how sure are we. The [methodology note](risk-methodology.md) states every formula. The [verification note](verification.md) holds the hand-worked answers the tests check against.

## A guided tour

![The MAHAD dashboard](images/dashboard.png)

The chart of the active symbol fills the left; a symbol is the short code for a share or a crypto pair, such as AAPL or BTC/USD. The price sits in the chart's corner, here Apple at 312.06 USD, up 0.59%. The 1m to 1mo buttons in the toolbar above set the time each bar (one slice of time) covers. The watchlist and risk panel sit on the right. The portfolio tab at the bottom shows cash, total value, and profit and loss, realised (on trades already closed) and unrealised (on positions still held).

![Price chart with SMA, EMA and RSI](images/chart.png)

The chart draws the closing price with two moving averages (smoothed lines of recent prices) over it, a 20-bar simple one (SMA) and a 12-bar exponential one (EMA, which leans on the most recent bars), and below it the 14-bar relative strength index (RSI), a 0 to 100 gauge, [overbought](glossary.md) above 70 and [oversold](glossary.md) below 30. Every line is drawn on completed bars only.

![Watchlist](images/watchlist.png)

The watchlist holds the symbols being followed (five here, three in view), with their latest prices and a green dot when a price is fresh; clicking a row makes it the active chart. Crypto pairs such as BTC/USD need no account or key (a free sign-up code); a live chart appears within seconds.

![Risk analytics panel](images/risk-analytics.png)

The top of the panel shows exposure (how much of the portfolio's value is in positions rather than cash), the volatility (the typical size of one period's move, a day by default) of the portfolio's own value, and its worst fall from a peak. The analytics section below runs the measures risk teams use, most on the last 250 trading days and the correlation grid on the last 90. The loss measures are [Value-at-Risk](glossary.md) at two confidence levels (how sure the estimate is), [Expected Shortfall](glossary.md), their bell-curve (parametric) versions, the traffic-light [backtest](glossary.md) and three replayed shocks such as the 2020 COVID crash. Others describe reward and how the risk is spread: [beta](glossary.md) against the S&P 500 fund SPY, the [Sharpe](glossary.md) and [Sortino](glossary.md) ratios, a recent-weighted (EWMA) volatility, [concentration](glossary.md), each position's share of the risk, and a grid of how closely the positions move together.

![The risk panel with the market context section open](images/market-context.png)

The market context section is the backdrop: the US Treasury 10-year yield (what the bond pays) and the gap between two-year and ten-year yields (35 basis points, or 0.35 percentage points; the ten-year paying more is the normal slope), the VIX fear gauge, the crypto Fear & Greed index (9, extreme fear), and the two UK rates, [SONIA](glossary.md) (the sterling overnight rate) and the [Bank Rate](glossary.md).

![Simulated order ticket](images/order-ticket.png)

The order ticket places a simulated buy or sell at the live price (the ticket calls it the mark) and says no real order is placed; the trade lands in the virtual portfolio at once.

![Alerts tab](images/alerts.png)

An alert watches for a condition, such as the price crossing 320 USD or the 20-bar average crossing below the 12-bar one, fires once with a notification, and stays listed as fired until re-armed.

![Command palette](images/command-palette.png)

Ctrl+Shift+P opens a searchable list of every command and its shortcut.

## What the numbers mean

Value-at-Risk (VaR) is the loss a bad day would reach or exceed, at a stated confidence. The verification note's worked example is a 100,000 USD portfolio with daily returns averaging 0.04% and a volatility of 1.2%. The 95% one-day parametric VaR comes out at 1.9338% of the portfolio, or 1,933.82 USD. Read it as "on nineteen days in twenty the loss stays under 1,934 USD; on about one day in twenty it is worse."

Historical VaR reads the figure from what happened: with 100 days of returns at 95%, the program sorts the days worst to best and takes the sixth worst, 2.50% in the worked example. Expected Shortfall asks how bad the bad days are on average: it averages the six worst days, 3.4667% in the same example, and is never smaller than its VaR.

The backtest checks the VaR against what happened: at 99% over 250 trading days the loss should breach it two or three times. The [Basel traffic light](glossary.md) calls up to four breaches green, five to nine yellow and ten or more red; the [Kupiec test](glossary.md) asks the same question statistically and also flags a model that breaches too rarely.

Drawdown is the fall from a peak: a value that goes 100, 110, 99, 104.5, 112, 108 has a maximum drawdown of minus 10%, the fall from 110 to 99. Concentration uses the Herfindahl-Hirschman Index, the sum of the squared weights: 50%, 30% and 20% give 0.25 + 0.09 + 0.04, or 0.38, and one over that is about 2.6 equal positions. Beta is how much the portfolio moves with the market: 1.16 means a 1% market move brings about a 1.16% move. Sharpe divides the return above a risk-free rate (the Treasury bill yield) by the variation it took to earn it; Sortino divides the plain return by the downside variation only.

## Where the data comes from

| What | From | How often | Access |
|---|---|---|---|
| Live stock quotes and sector names | Finnhub | every 5 seconds for the chart symbol, at most 55 a minute | free key |
| Stock daily history, adjusted for dividends and [splits](glossary.md) | Tiingo | nightly, plus one pull of recent minute and hour bars | free key |
| Crypto prices and daily bars | Kraken's public price feeds | every 5 seconds for the chart symbol, daily bars nightly | no key |
| USD to GBP reference rate | Frankfurter (the European Central Bank's rate) | every 12 hours | no key |
| Treasury yields | US Treasury | every 12 hours | no key |
| VIX | FRED (the St. Louis Fed's data service) | every 12 hours | free key |
| SONIA and Bank Rate | Bank of England | every 12 hours | no key |
| Crypto Fear & Greed index | alternative.me | every 12 hours | no key |

The three keys are free sign-ups, kept in a local `.env` file that never leaves the machine or reaches a log; none can trade or move money.

## What it deliberately is not

MAHAD holds no brokerage account and cannot place a real order; Kraken's public price feeds cannot trade.

## The report export

`python -m mahad.report` writes the portfolio's risk figures to a CSV file (a spreadsheet-readable file) without the window and without writing to the database, even while the program is open. Every row states the metric, its value and unit, its period and basis (the price history it is measured on), the date, and a note when the database lacks what the figure needs.

## How to run it

1. Install Python 3.11 to 3.13 and download the code.
2. On Windows double-click `MAHAD.bat`; on macOS or Linux run `bash run.sh`. The first run sets itself up.
3. Add a symbol. Crypto works at once; for stocks, copy `.env.example` to `.env` and paste in the free Finnhub and Tiingo keys.

## Where to read next

The [technical guide](architecture.md) explains how the program is built and tested, the [requirements document](requirements.md) states what it does and names the test behind each point, the [data dictionary](data-dictionary.md) lists the database and every figure, and the [glossary](glossary.md) defines the terms.
