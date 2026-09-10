<div align="center">

# MAHAD

### A desktop risk tool for live stock and crypto markets

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue) &nbsp;[![tests](https://github.com/5Muawiyah/MAHAD/actions/workflows/tests.yml/badge.svg)](https://github.com/5Muawiyah/MAHAD/actions/workflows/tests.yml) &nbsp;![Built with](https://img.shields.io/badge/built%20with-PySide6%20%2F%20Qt-41cd52)

</div>

<p align="center"><img src="docs/images/dashboard.png" alt="The MAHAD dashboard" width="100%"></p>

<p align="center"><i>One window: a live price chart, a watchlist, the risk panel, and a simulated portfolio with live profit and loss.</i></p>

Readers who are not technical can start with the [plain-English overview](docs/overview.md); the [technical guide](docs/architecture.md) is for engineers.

| Document | What it covers |
|---|---|
| [Overview](docs/overview.md) | what MAHAD is, a tour of the screens, what the numbers mean |
| [Technical guide](docs/architecture.md) | how the code is split into layers, the line of work that runs behind the window, the database, the eight data sources, the tests |
| [Requirements](docs/requirements.md) | what the program must do and how well, the user journeys with the checks each must pass, and which test proves each point |
| [Data dictionary](docs/data-dictionary.md) | the database's tables and columns, the fields each data source sends, the derived figures, the report file |
| [Risk methodology](docs/risk-methodology.md) | every formula and convention |
| [Verification](docs/verification.md) | the hand-worked answers the tests check the formulas against |
| [Glossary](docs/glossary.md) | the terms, in plain English |

MAHAD is a desktop risk tool that runs on live market data. Muawiyah Jahanzaib built it to show how the standard market-risk figures are produced and how each one can be checked, so it is made for analysis and learning rather than for trading. The name, Multi-Asset Heuristic Analytics Dashboard, means several kinds of asset (shares and crypto), the measures a bank's risk team reaches for by habit, one screen. It charts stocks and crypto, runs a simulated USD portfolio with live profit and loss, and computes the market-risk figures described below. The portfolio is a simulation, so MAHAD holds no broker or trading credentials and never places a real order.

## Highlights

The chart draws one symbol's closing price in bars, each bar one slice of time from one minute to one month. A symbol is the short code for a share, such as AAPL, or for a crypto pair such as BTC/USD, a coin priced in a currency. Three indicator lines go with it: two moving averages (smoothed lines of recent prices) over the price, and the RSI (relative strength index, a momentum gauge) beneath it.

Because the portfolio is simulated, a buy or sell order moves virtual USD only, and cash, positions (the shares and coins held) and profit and loss update at once.

On the right, the risk panel carries the measures a bank's risk desk would read, each defined in the [glossary](docs/glossary.md) and explained in the [overview](docs/overview.md). Market context tiles give the backdrop: US Treasury yields (what US government bonds pay) and the VIX index of expected market volatility (the typical size of a day's move, as a percentage). The other tiles carry the crypto Fear & Greed index (a daily sentiment score from 0, extreme fear, to 100, extreme greed) and the two UK rates, SONIA (the rate banks pay to borrow pounds from each other overnight) and the Bank Rate (the Bank of England's base rate). Alerts fire once when a price or indicator condition is met; a command palette lists every command with its shortcut.

## A closer look

### Live chart with indicators

<p align="center"><img src="docs/images/chart.png" alt="Price chart with SMA, EMA, and RSI" width="92%"></p>

The price chart carries a simple and an exponential moving average (SMA and EMA, the exponential one leaning on the most recent bars) and the relative strength index (RSI), and switches across bar sizes from one minute to one month. The indicator lines are drawn only on completed price bars, so the newest, still-changing bar never makes them flicker.

### Watchlist

<img src="docs/images/watchlist.png" alt="Watchlist" width="300" align="right">

Follow stocks and crypto side by side; the badge counts them (five here, three in view). Each row shows the latest price, and clicking one makes it the active symbol on the chart. Crypto needs no key and trades around the clock; the chart asks for a fresh price every five seconds.

<br clear="all">

### Risk analytics

<img src="docs/images/risk-analytics.png" alt="Risk analytics panel" width="330" align="right">

The panel answers the question a risk desk asks all day about the simulated portfolio: how much could we lose if prices move against us, and how sure are we. The first is [Value-at-Risk](docs/glossary.md#value-at-risk-var) (VaR, the loss a bad day could reach) with [Expected Shortfall](docs/glossary.md#expected-shortfall-es) beyond it, each position's share of the total risk, and replays of dated shocks such as the 2020 COVID crash. The second is a backtest that counts how often losses breach the VaR, shown as the [Basel traffic light](docs/glossary.md#basel-traffic-light), with the [Kupiec test](docs/glossary.md#kupiec-test) in the note that appears when the mouse rests on it. The rest of the panel describes reward and spread: [beta](docs/glossary.md#beta) against the market, the [Sharpe](docs/glossary.md#sharpe-ratio) and [Sortino](docs/glossary.md#sortino-ratio) ratios, a smoothed volatility ([EWMA](docs/glossary.md#ewma)), [concentration](docs/glossary.md#concentration) and a grid of how closely the positions move together. Every formula is written out in the [methodology note](docs/risk-methodology.md). Each block names the period it covers (its window), and each percentage says what it is a share of.

<br clear="all">

### Market context

<img src="docs/images/market-context.png" alt="The risk panel with the market context section open" width="330" align="right">

The market backdrop in one place, at the foot of the risk panel: the 10-year Treasury yield and the 2s10s spread (the gap between two- and ten-year yields), the VIX volatility index, the crypto Fear & Greed index, and the UK rates (SONIA, the sterling overnight rate, and the Bank Rate). All of these but the VIX run without a key; the VIX tile needs the free key for FRED, the St. Louis Fed's data service.

<br clear="all">

### Simulated orders

<img src="docs/images/order-ticket.png" alt="Simulated order ticket" width="420" align="right">

Place a simulated buy or sell from the order ticket. The ticket shows the live price as the mark and the estimated cost, and its button reads Confirm buy; the trade lands in the virtual portfolio the moment it is confirmed. No real order is ever placed, and no trading account is involved.

<br clear="all">

### Alerts

<p align="center"><img src="docs/images/alerts.png" alt="Alerts tab" width="100%"></p>

Set a price or indicator alert; it fires once, raises a notification, and is listed in the Alerts tab.

### Command palette

<img src="docs/images/command-palette.png" alt="Command palette" width="420" align="right">

Press Ctrl+Shift+P for a searchable, keyboard-driven list of every command, each shown with its shortcut.

<br clear="all">

## What it shows about the build

The window is a PySide6 and Qt desktop application (Qt is the window toolkit and PySide6 its Python form) whose dark colour scheme meets the AA level of the Web Content Accessibility Guidelines (WCAG) for the contrast between text and its background. A missing or rejected key shows a message naming the source rather than a crash. Every risk formula is stated in [docs/risk-methodology.md](docs/risk-methodology.md) and checked against the hand-worked answers in [docs/verification.md](docs/verification.md), and the test suite runs with no window open on every change pushed to main and on every pull request, as the badge above shows.

## How it is built

<p align="center"><img src="docs/images/architecture.svg" alt="The four layers, the providers and the database" width="100%"></p>

The screen asks, a background thread does the work and reports back; a thread is a line of work that runs alongside the window's own. The window is the ui layer, short for user interface. It draws the screen and sends intents, which are requests such as add a symbol or place an order. One background worker thread fetches, computes and writes. The engine does the calculations in plain Python with no Qt, so the tests call it directly. The data layer reaches all eight providers (the market data sources) through code that turns a failed fetch into a message: an adapter module each for the three price feeds, and one module of small functions for the five reference-data sources. It also owns the SQLite database, which lives in one file. Each layer calls only the one below it, from the window down to the data layer, and the worker hands complete snapshots (the whole picture the window shows) back through Qt signals, the toolkit's messages between threads. The [technical guide](docs/architecture.md) has the diagrams and a map of the code's files.

## Report export

```
python -m mahad.report
```

Writes the portfolio's risk figures to a CSV file (plain text that a spreadsheet opens) from the app's own database, read-only, so it runs whether or not the window is open. `--db`, `--out`, `--confidence` and `--window` are the options it takes; the [data dictionary](docs/data-dictionary.md) lists the columns.

## Tech stack

Python 3.11 to 3.13 · PySide6 / Qt · pyqtgraph (charting) · numpy (maths) · SQLite via SQLAlchemy (the database layer). Live data from Finnhub and Tiingo (stocks), a keyless Kraken adapter (crypto), Frankfurter (the USD to GBP rate), the US Treasury, FRED, the Bank of England, and alternative.me (the Fear & Greed index).

## Getting started

MAHAD needs **Python 3.11, 3.12 or 3.13** (newer versions are not validated for MAHAD yet). Then:

```
git clone https://github.com/5Muawiyah/MAHAD.git
cd MAHAD
```

On Windows double-click `MAHAD.bat`, which sets up its own environment on the first run and then launches; on macOS or Linux run `bash run.sh`.

MAHAD launches fully keyless: crypto, the USD to GBP rate, Treasury yields, UK rates and the Fear & Greed gauge all work with no key.

### API keys (optional, free)

Live stock quotes and history, and the VIX tile, use free keys. Without them MAHAD still runs, and the stock screens show a "needs a free key" message that points back here; everything keyless keeps working.

| Key | What it adds | Where to get it (free) |
|---|---|---|
| `FINNHUB_API_KEY` | live US stock quotes | finnhub.io/register |
| `TIINGO_API_KEY` | stock history, adjusted for dividends and splits (a split divides each share into several) | tiingo.com |
| `FRED_API_KEY` | the VIX tile (optional) | fred.stlouisfed.org |

Copy `.env.example` to `.env` and paste your keys in. The `.env` file is never added to the public code and never leaves your machine, and none of the keys can trade or move money. MAHAD uses FRED's data service but is not endorsed or certified by the Federal Reserve Bank of St. Louis.

## Run the tests

```
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite is headless (no network, no display): it covers the risk maths, the data adapters (checked against saved sample responses from each provider), and the window's source code (the words on screen, the colours and the shortcuts the design depends on).

---

<div align="center"><sub>Built by Muawiyah Jahanzaib. MIT licensed. A simulated USD portfolio for analysis and learning, not investment advice.</sub></div>
