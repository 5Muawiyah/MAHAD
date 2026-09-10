<div align="center">

# MAHAD

### A desktop market-risk workstation for live stock and crypto markets

![Python](https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue) &nbsp;[![tests](https://github.com/5Muawiyah/MAHAD/actions/workflows/tests.yml/badge.svg)](https://github.com/5Muawiyah/MAHAD/actions/workflows/tests.yml) &nbsp;![Built with](https://img.shields.io/badge/built%20with-PySide6%20%2F%20Qt-41cd52)

</div>

<p align="center"><img src="docs/images/dashboard.png" alt="The MAHAD dashboard" width="100%"></p>

<p align="center"><i>One window: a live price chart, a watchlist, the risk panel, and a simulated portfolio with live profit and loss.</i></p>

**Start here:** the [plain-English overview](docs/overview.md) if you are not technical, or the [technical guide](docs/architecture.md) if you are.

| Document | What it covers |
|---|---|
| [Overview](docs/overview.md) | what MAHAD is, a tour of the screens, what the numbers mean |
| [Technical guide](docs/architecture.md) | the layering, the worker thread, persistence, the providers, the tests |
| [Requirements](docs/requirements.md) | the functional and non-functional requirements, user stories, traceability to tests |
| [Data dictionary](docs/data-dictionary.md) | the SQLite schema, provider fields, derived figures, the report CSV |
| [Risk methodology](docs/risk-methodology.md) | every formula and convention |
| [Verification](docs/verification.md) | the hand-worked vectors the tests pin the formulas to |
| [Glossary](docs/glossary.md) | the terms, in plain English |

MAHAD is a desktop risk tool that runs on live market data. It charts stocks and crypto, runs a simulated USD portfolio with live profit and loss, and computes the market-risk figures described below. The portfolio is a simulation, so MAHAD holds no broker or trading credentials and never places a real order.

## Highlights

The window shows one symbol's price chart with two moving averages and the RSI momentum gauge drawn over it, at bar sizes from one minute to one month. A watchlist follows several stocks and crypto pairs at once. Simulated buy and sell orders move a virtual USD portfolio whose cash, positions and profit and loss update on every price refresh. The risk panel computes the standard measures of how much the portfolio could lose on a bad day and how sure that estimate is, each defined in the [glossary](docs/glossary.md) and explained in the [overview](docs/overview.md). Market context tiles give the backdrop: US Treasury yields, the VIX volatility index, the crypto Fear & Greed index and the two UK rates. One-shot alerts fire once when a price or indicator condition is met, and a command palette lists every command with its shortcut.

## A closer look

### Live chart with indicators

<p align="center"><img src="docs/images/chart.png" alt="Price chart with SMA, EMA, and RSI" width="92%"></p>

The price chart carries a simple and an exponential moving average (SMA and EMA) and the relative strength index (RSI), and switches across bar sizes from one minute to one month. The indicator lines are drawn only on completed price bars, so the newest, still-changing bar never makes them flicker.

### Watchlist

<img src="docs/images/watchlist.png" alt="Watchlist" width="300" align="right">

Follow stocks and crypto side by side. Each row shows the latest price, and clicking one makes it the active symbol on the chart. Crypto needs no API key and updates around the clock, so a live chart appears within seconds of opening.

<br clear="all">

### Risk analytics

<img src="docs/images/risk-analytics.png" alt="Risk analytics panel" width="330" align="right">

On the simulated portfolio the panel computes historical and parametric Value-at-Risk, Expected Shortfall, each holding's share of the total risk (component VaR), beta against the market, the Sharpe and Sortino ratios, a smoothed (EWMA) volatility, concentration, a correlation heatmap, a backtest that counts how often losses beat the VaR (the Basel traffic light and the Kupiec test), and replays of dated shocks such as the 2020 COVID crash. Every figure is labelled with the period it covers (its window) and the series it is measured on (its basis), so the same holding's different percentages are never ambiguous.

<br clear="all">

### Market context

<img src="docs/images/market-context.png" alt="The risk panel with the market context section open" width="330" align="right">

The macro backdrop in one place, at the foot of the risk panel: the 10-year Treasury yield and the 2s10s spread (the gap between two- and ten-year yields), the VIX volatility index, the crypto Fear & Greed index, and the UK rates (SONIA, the sterling overnight rate, and the Bank Rate). All of these but the VIX run without a key; the VIX tile needs the free FRED key.

<br clear="all">

### Simulated orders

<img src="docs/images/order-ticket.png" alt="Simulated order ticket" width="420" align="right">

Place a simulated buy or sell from the order ticket. The trade is recorded against a virtual USD portfolio, and cash, positions and live profit and loss update at once. No real order is ever placed, and no trading account is involved.

<br clear="all">

### Alerts

<p align="center"><img src="docs/images/alerts.png" alt="Alerts tab" width="100%"></p>

Set a price or indicator alert; it fires once, raises a notification, and is listed in the Alerts tab.

### Command palette

<img src="docs/images/command-palette.png" alt="Command palette" width="420" align="right">

Press Ctrl+Shift+P for a searchable, keyboard-driven list of every command, each shown with its shortcut.

<br clear="all">

## What this demonstrates

For a technical reader: the window is a PySide6 and Qt desktop application with a dark design system that meets WCAG AA contrast. Each of the eight data sources sits behind an adapter that returns failures as values, so a missing or rejected key shows a message naming the source rather than a crash. Every risk formula is stated in [docs/risk-methodology.md](docs/risk-methodology.md) and checked against the hand-worked answers in [docs/verification.md](docs/verification.md). The code is layered one way (ui to worker to engine to data), the engine is pure Python with no Qt, and the suite runs without a display on every push, as the badge above shows.

## How it is built

<p align="center"><img src="docs/images/architecture.svg" alt="The four layers, the providers and the database" width="100%"></p>

The window renders and sends intents; one background worker thread fetches, computes and writes; the engine is pure Python that the tests call directly; the data layer wraps each provider in an adapter that returns failures as values and owns the SQLite file. Imports run one way, from the window down to the data layer, and the worker hands complete snapshots back through Qt signals. The [technical guide](docs/architecture.md) has the diagrams and the module map.

## Report export

```
python -m mahad.report
```

Writes the portfolio's risk figures to a CSV from the app's own database, read-only, so it runs whether or not the window is open. `--db`, `--out`, `--confidence` and `--window` are the flags; the [data dictionary](docs/data-dictionary.md) lists the columns.

## Tech stack

Python 3.11 to 3.13 · PySide6 / Qt · pyqtgraph · numpy · SQLite via SQLAlchemy. Live data from Finnhub and Tiingo (stocks), a keyless Kraken adapter (crypto), Frankfurter (the USD to GBP rate), the US Treasury, FRED, the Bank of England, and alternative.me (the Fear & Greed index).

## Getting started

MAHAD needs **Python 3.11, 3.12 or 3.13** (newer versions are not validated for MAHAD yet). Then:

```
git clone https://github.com/5Muawiyah/MAHAD.git
cd MAHAD
```

On Windows double-click `MAHAD.bat`, which sets up its own environment on the first run and then launches; on macOS or Linux run `bash run.sh`.

MAHAD launches fully keyless: crypto, the USD to GBP rate, Treasury yields, UK rates and the Fear & Greed gauge all work with no key, and a live BTC/USD chart appears within seconds.

### API keys (optional, free)

Live stock quotes and history, and the VIX tile, use free, email-only keys. Without them MAHAD still runs, and the stock screens show a clear "needs a free key" message that points back here; everything keyless keeps working.

| Key | What it adds | Where to get it (free) |
|---|---|---|
| `FINNHUB_API_KEY` | live US stock quotes | finnhub.io/register |
| `TIINGO_API_KEY` | stock history, adjusted for dividends and splits | tiingo.com |
| `FRED_API_KEY` | the VIX tile (optional) | fred.stlouisfed.org |

Copy `.env.example` to `.env` and paste your keys in. The `.env` file is git-ignored and never leaves your machine, and none of the keys can trade or move money. MAHAD uses the FRED API but is not endorsed or certified by the Federal Reserve Bank of St. Louis.

## Run the tests

```
pip install -r requirements-dev.txt
python -m pytest -q
```

The suite is headless (no network, no display): it covers the risk maths, the data adapters on captured fixtures, and the UI source-invariants.

---

<div align="center"><sub>MIT licensed. A simulated USD portfolio for analysis and learning, not investment advice.</sub></div>
