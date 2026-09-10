# MAHAD in plain English

MAHAD (Multi-Asset Heuristic Analytics Dashboard: several [asset classes](glossary.md#asset-class), the measures a bank's risk team reaches for by habit, one screen) is a desktop program that watches live market prices and shows how much a portfolio of shares and cryptocurrency could lose. The portfolio is a simulation: it starts with 100,000 virtual US dollars, no real money is involved, nothing goes to a broker, and the figures are not investment advice.

## Who it is for

MAHAD is for anyone learning how market risk is measured, from a course, a first job on a risk team or their own reading. It is a study tool, not a system a trading desk would run on. An analyst runs it and reads the figures as they update; a reader takes them from the report file or these documents and checks them against hand-worked answers. On a laptop, with real prices, it answers the question a risk desk asks all day: how much could we lose if prices move against us, and how sure are we. The [methodology note](risk-methodology.md) states every formula and the [verification note](verification.md) holds the answers the tests check against.

## A guided tour

![The MAHAD dashboard](images/dashboard.png)

The chart of the active symbol fills the left, the price in its corner, here Apple at 312.06 USD, up 0.59%. A symbol is the short code for a share or a crypto pair, such as AAPL or BTC/USD. The 1m to 1mo buttons above set the time each bar (one slice of time) covers. The watchlist and risk panel sit on the right. The portfolio tab shows cash, total value, and profit and loss, realised (closed trades) and unrealised (open positions).

![Price chart with SMA, EMA and RSI](images/chart.png)

The chart draws the closing price with two moving averages (smoothed lines of recent prices) over it: a 20-bar simple one (SMA) and a 12-bar exponential one (EMA), which leans on recent bars. Below it the 14-bar relative strength index (RSI) runs 0 to 100, [overbought](glossary.md#overbought) above 70 and [oversold](glossary.md#oversold) below 30. Every line is drawn on completed bars only.

![Watchlist](images/watchlist.png)

The watchlist holds the symbols being followed (five here, three in view), with their latest prices and a green dot when fresh. Clicking a row charts it. Crypto pairs such as BTC/USD need no account or key; the chart polls the active symbol every five seconds.

![Risk analytics panel](images/risk-analytics.png)

The top of the panel shows exposure (how much of the portfolio's value, its net asset value or NAV, is in positions rather than cash), the volatility (the typical size of one period's move, a day by default) of the portfolio's own value, and its worst fall from a peak. The analytics below run on the last 250 trading days, the correlation grid on 90. The loss measures are [Value-at-Risk](glossary.md#value-at-risk-var) at two confidence levels (how sure the estimate is), [Expected Shortfall](glossary.md#expected-shortfall-es), the bell-curve (parametric) version of the VaR at both levels, and three replayed shocks: the 2020 COVID crash, the 2022 tightening (central banks raising rates sharply) and the FTX week (a large crypto exchange collapsing). A traffic-light [backtest](glossary.md#backtest) checks the VaR against what happened. The remaining rows describe reward and spread: [beta](glossary.md#beta) against the S&P 500 fund SPY, the [Sharpe](glossary.md#sharpe-ratio) and [Sortino](glossary.md#sortino-ratio) ratios, a recent-weighted ([EWMA](glossary.md#ewma)) volatility, [concentration](glossary.md#concentration), each position's share of the risk, and how closely the positions move together.

![The risk panel with the market context section open](images/market-context.png)

The market context section is the backdrop: the US Treasury 10-year yield and the gap between the two-year and ten-year yields (35 basis points, or 0.35 percentage points; the ten-year paying more is the normal slope). Beside them sit the VIX fear gauge, the crypto Fear & Greed index (9, extreme fear) and the two UK rates, [SONIA](glossary.md#sonia) and the [Bank Rate](glossary.md#bank-rate).

![Simulated order ticket](images/order-ticket.png)

The order ticket places a simulated buy or sell at the live price (the mark), says no real order is placed, and the trade lands in the virtual portfolio at once.

![Alerts tab](images/alerts.png)

An alert watches for a condition, such as the price crossing 320 USD or the 20-bar average crossing below the 12-bar one, fires once and stays listed as fired until re-armed.

![Command palette](images/command-palette.png)

Ctrl+Shift+P opens a searchable list of every command and its shortcut.

## What the numbers mean

Value-at-Risk (VaR) is the loss a bad day would reach or exceed, at a stated confidence. The verification note's worked example is a 100,000 USD portfolio with daily returns averaging 0.04% and a volatility of 1.2%. The 95% one-day parametric VaR is 1.9338% of the portfolio, or 1,933.82 USD. Read it as "on nineteen days in twenty the loss stays under 1,934 USD; on about one day in twenty it is worse."

Historical VaR reads the figure from what happened: with 100 days of returns at 95%, it takes the sixth worst, 2.50%. Expected Shortfall asks how bad the bad days are on average: at 95% it averages the six worst days, 3.4667% here, and is never smaller than its VaR. The panel reports it at 97.5%, the level the [Basel](glossary.md#basel-traffic-light) bank rules use, so its figure differs.

The backtest checks the VaR against what happened: at 99% over 250 trading days, two or three breaches are expected. The [Basel traffic light](glossary.md#basel-traffic-light) calls up to four breaches green, five to nine yellow and ten or more red; it reads backcast while the count is still filled in from past data. The [Kupiec test](glossary.md#kupiec-test) asks the same question statistically and flags a model that breaches too rarely.

Drawdown is the fall from a peak: a value that goes 100, 110, 99, 104.5, 112, 108 falls 10% from 110 to 99. Concentration uses the Herfindahl-Hirschman Index, the sum of the squared weights: 50%, 30% and 20% give 0.38, and one over that is about 2.6 equal positions. Beta is how much the portfolio moves with the market: 1.16 means a 1% market move brings about 1.16%. Sharpe divides the return above a risk-free rate by the variation it took to earn it. Sortino counts the downside variation only.

## Where the data comes from

| What | From | How often | Access |
|---|---|---|---|
| Live stock quotes and sector names | Finnhub | every 5 seconds for the chart symbol, at most 55 a minute | free key |
| Stock daily history, adjusted for dividends and [splits](glossary.md#split) | Tiingo | nightly, plus one pull of recent bars | free key |
| Crypto prices and daily bars | Kraken's public price feeds | every 5 seconds for the chart symbol, daily bars nightly | no key |
| USD to GBP reference rate | Frankfurter (the European Central Bank's rate) | every 12 hours | no key |
| Treasury yields | US Treasury | every 12 hours | no key |
| VIX | FRED (the St. Louis Fed's data service) | every 12 hours | free key |
| SONIA and Bank Rate | Bank of England | every 12 hours | no key |
| Crypto Fear & Greed index | alternative.me | every 12 hours | no key |

The three keys are free sign-ups, kept in a local `.env` file that never leaves the machine or reaches a log.

## What it deliberately is not

MAHAD holds no brokerage account and cannot place a real order.

## The report export

`python -m mahad.report` writes the portfolio's risk figures to a CSV file without opening the window and without writing to the database, so it can run while the program is open. Every row carries seven columns: the metric, its value and unit, the basis (the price history behind it), the period where the figure has one, the date and a note.

## How to run it

1. Install Python 3.11 to 3.13 and download the code.
2. On Windows double-click `MAHAD.bat`; on macOS or Linux run `bash run.sh`. The first run sets itself up.
3. Add a symbol. Crypto works at once; for stocks, copy `.env.example` to `.env` and add the two free keys.

## Where to read next

The [technical guide](architecture.md) explains how the program is built and tested, the [requirements document](requirements.md) states what it does and names the test behind each point, the [data dictionary](data-dictionary.md) lists the database and every figure, and the [glossary](glossary.md) defines the terms.
