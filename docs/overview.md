# MAHAD in plain English

MAHAD (Multi-Asset Heuristic Analytics Dashboard: several [asset classes](glossary.md#asset-class), the measures a risk team reaches for by habit, one screen) is a desktop program that watches live prices and shows how much a portfolio of shares and cryptocurrency could lose. The portfolio is a simulation: it starts with 100,000 virtual US dollars, no real money is involved, nothing goes to a broker, and the figures are not investment advice.

## Who it is for

MAHAD is for anyone learning how market risk is measured: from a course, a first job or their own reading. It is a study tool, not a system a risk desk would run on. On a laptop, with real prices, it works out how much a portfolio could lose if prices moved against it and how sure that figure is. The figures can be read on screen or taken from the exported file and checked by hand. The [methodology note](risk-methodology.md) states every formula and the [verification note](verification.md) holds the answers the tests check against.

## A guided tour

![The MAHAD dashboard](images/dashboard.png)

The chart of the active symbol fills the left, the price in its corner, here Apple at 312.06 USD, up 0.59%. A symbol is the short code for a share or a crypto pair, such as AAPL or BTC/USD; the 1m to 1mo buttons above set the time each bar covers. The watchlist and risk panel sit on the right. The portfolio tab shows cash, total value and profit and loss, realised (banked on closed trades) and unrealised (on paper, still held).

![Price chart with SMA, EMA and RSI](images/chart.png)

The chart can draw two moving averages over the closing price: a 20-bar simple one (SMA) and a 12-bar exponential one (EMA), which leans on recent bars. Below it the 14-bar relative strength index (RSI) runs 0 to 100, [overbought](glossary.md#overbought) above 70 and [oversold](glossary.md#oversold) below 30. Every line is drawn on completed bars only.

![Watchlist](images/watchlist.png)

The watchlist holds the symbols followed (five here, three in view), with their latest prices and a green dot when fresh; clicking a row charts it. Crypto pairs such as BTC/USD need no account or key; the chart asks for a fresh price every five seconds.

![Risk analytics panel](images/risk-analytics.png)

The top of the panel shows exposure (how much of the value, its net asset value or NAV, is in positions rather than cash), the volatility of that value (the typical size of one period's move, a day by default), and its worst fall from a peak. The analytics below run on the last 250 trading days, the correlation grid on 90. The loss measures are [Value-at-Risk](glossary.md#value-at-risk-var) at two confidence levels (how sure the estimate is), [Expected Shortfall](glossary.md#expected-shortfall-es), the bell-curve (parametric) version of the VaR, and three replayed shocks: the 2020 COVID crash, the 2022 tightening (central banks raising rates sharply) and the FTX week (a large crypto exchange collapsing). A traffic-light [backtest](glossary.md#backtest) checks the VaR against events. The remaining rows describe reward and spread: [beta](glossary.md#beta) against the S&P 500 fund SPY, the [Sharpe](glossary.md#sharpe-ratio) and [Sortino](glossary.md#sortino-ratio) ratios, a recent-weighted ([EWMA](glossary.md#ewma)) volatility, [concentration](glossary.md#concentration), each position's share of the risk, and how closely they move together.

![The risk panel with the market context section open](images/market-context.png)

The market context section is the backdrop: the US Treasury 10-year yield and the gap between the two-year and ten-year yields (35 [basis points](glossary.md#basis-point); the ten-year paying more is the normal shape). Below them sit the VIX fear gauge, the crypto Fear & Greed index (9, extreme fear) and the two UK rates, [SONIA](glossary.md#sonia) and the [Bank Rate](glossary.md#bank-rate).

![Simulated order ticket](images/order-ticket.png)

The order ticket places a simulated buy or sell at the live price (the mark), says no real order is placed, and the trade lands at once.

![Alerts tab](images/alerts.png)

An alert watches for a condition, such as the price crossing 320 USD or the 20-bar average crossing below the 12-bar one, fires once and stays listed until re-armed.

![Command palette](images/command-palette.png)

Ctrl+Shift+P opens a searchable list of every command and any shortcut it has.

## What the numbers mean

Value-at-Risk (VaR) is the loss a bad day would reach or exceed, at a stated confidence. Take a 100,000 USD portfolio with daily returns averaging 0.04% and a volatility of 1.2%: its 95% one-day parametric VaR is 1.9338%, or 1,933.82 USD. On nineteen days in twenty the loss stays under 1,934 USD; on about one in twenty it is worse.

Historical VaR reads it from what happened: with 100 days of returns at 95%, it takes the sixth worst, 2.50%. Expected Shortfall averages the bad days: at 95% it averages the six worst, 3.4667% here, and is never smaller than its VaR. The panel reports it at 97.5%, the level the [Basel](glossary.md#basel-traffic-light) rules use, so its figure differs.

The backtest checks the VaR against events: at 99% over 250 trading days, two or three breaches are expected. The [Basel traffic light](glossary.md#basel-traffic-light) calls up to four breaches green, five to nine yellow and ten or more red. The window fills as the program runs, which is why the picture shows 215 days; the zone chip reads [backcast](glossary.md#backcast) while the earlier days come from stored history. The [Kupiec test](glossary.md#kupiec-test) asks the same statistically, and flags a model that breaches too rarely.

Drawdown is the fall from a peak: 100, 110, 99, 104.5, 112, 108 falls 10% from 110 to 99. Concentration uses the Herfindahl-Hirschman Index, the sum of the squared weights: 50%, 30% and 20% give 0.38, and one over that is 2.6, as concentrated as a portfolio of 2.6 equal positions. Beta is how much the portfolio moves with the market: 1.16 means a 1% market move brings about 1.16%. Sharpe divides the return above a risk-free rate by the variation it took to earn; Sortino counts the downside only.

## Where the data comes from

| What | From | How often | Access |
|---|---|---|---|
| Live stock quotes and sector names | Finnhub | every 5 seconds for the chart symbol, 55 a minute | free key |
| Stock daily history, adjusted for dividends and [splits](glossary.md#split) | Tiingo | nightly, plus one pull of recent bars | free key |
| Crypto prices and daily bars | Kraken's public feeds | every 5 seconds for the chart symbol, daily bars nightly | no key |
| USD to GBP reference rate | Frankfurter (the European Central Bank's rate) | every 12 hours | no key |
| Treasury yields | US Treasury | every 12 hours | no key |
| VIX | FRED (the St. Louis Fed's data service) | every 12 hours | free key |
| SONIA and Bank Rate | Bank of England | every 12 hours | no key |
| Crypto Fear & Greed index | alternative.me | every 12 hours | no key |

The three keys are free sign-ups, kept in a local `.env` file that stays on the machine.

## What it deliberately is not

MAHAD holds no brokerage account and cannot place a real order. The portfolio is US dollars only and holds only what it has bought: it never sells what it does not hold (a short position) and never borrows. It runs for one person on one machine. The figures are not advice: they are worth what the formulas and the tests behind them are worth.

## The report export

`python -m mahad.report` writes the portfolio's risk figures to a CSV file without opening the window and without writing to the database, so it runs while the program is open. Every row carries seven columns: the metric, its value and unit, the basis it is worked out on, the period where the figure has one, the date and a note.

## How to run it

1. Install Python 3.11 to 3.13 and download the code.
2. On Windows double-click `MAHAD.bat`; on macOS or Linux run `bash run.sh`. The first run sets itself up.
3. Add a symbol. Crypto works at once; for stocks, copy `.env.example` to `.env` and add the two free keys.

## Where to read next

The [technical guide](architecture.md) explains how the program is built and tested, the [requirements document](requirements.md) states what it does and names the test behind each point, the [data dictionary](data-dictionary.md) lists the database and every figure, and the [glossary](glossary.md) defines the terms.
