# Risk methodology

MAHAD runs a simulated USD portfolio on live market data and reports a desk-style
risk panel over it. This note states every metric, its formula, and the conventions
it follows. All of it is plain Python in `mahad/engine/`; none of it depends on the
UI. Every figure is reproducible by hand from the worked vectors in
[verification.md](verification.md).

## Two return bases, two labels

MAHAD keeps two return series and never mixes them silently.

1. **Value-history (wall-clock) basis** - the portfolio's own marked value sampled on
   a fixed wall-clock cadence. Exposure, the headline volatility, and maximum drawdown
   are computed on this series and annualised on a calendar basis. Source:
   `mahad/engine/risk.py`.
2. **Trading-day basis** - per-asset daily simple returns aligned to the US trading
   calendar, from which an as-if portfolio return series is built. The analytics suite
   (VaR, Expected Shortfall, ratios, beta, the backtest, concentration, stress) runs on
   this series and annualises with the 252 trading-day convention. Source:
   `mahad/engine/returns.py` and `mahad/engine/risk_metrics.py`.

Each surface is labelled with the basis it uses, so a 365-basis volatility and a
252-basis Sharpe are never read as if they shared a denominator.

## Value-history metrics (`mahad/engine/risk.py`)

### Exposure

    exposure = (sum of qty x mark) / portfolio_value

Reported as an absolute USD figure and a fraction. Undefined (shown as "-") when
`portfolio_value <= 0`. Per-position exposure uses the same denominator
(`position_value / portfolio_value`), so the per-position fractions sum to the overall
figure. A fraction outside `[0, 1]` is flagged, but the flag is surfaced only when the
marks are non-stale (under stale marks it is "as of last good price", not an error).

### Volatility

Sample standard deviation (ddof = 1) of the simple per-period returns
`r_t = V_t / V_(t-1) - 1`, reported as a percentage (`sigma x 100`). The rolling window
is the last 30 returns; the figure is undefined until at least two returns exist.
Returns are taken only between consecutive non-stale, strictly positive samples.

The per-period figure is the headline. The annualised figure is

    sigma_annual = sigma_period x sqrt(periods_per_year)

with a single wall-clock constant per timeframe: 1d -> 365, 1h -> 8,760,
1m -> 525,600. The rationale for the wall-clock choice is below.

### Maximum drawdown

    maxDD = min over t of (value_t / running_max_t - 1)      (a negative percentage)

`running_max` is seeded at the persisted all-time peak (both value and timestamp), so a
capped history can never roll off the true peak; it updates whenever a sample exceeds
it. A flat or rising series gives 0.0%. Stale-mark samples are included here (drawdown
is value-based) even though they are excluded from the returns series used for
volatility. The result names the worst trough and the peak in force at that trough.

## Trading-day return series (`mahad/engine/returns.py`)

- Per-asset daily simple returns from daily closes. Stocks use Tiingo adjusted closes
  so dividends and splits are not read as price moves; crypto uses Kraken daily closes.
- Series align on the US trading calendar. A weekend or holiday crypto bar is dropped,
  so its move folds into the next trading day's return.
- The as-if portfolio series applies today's weights `w_i = qty_i x mark_i / portfolio_value`
  across the window, held constant over the window. Cash earns zero, so the uninvested
  remainder contributes nothing.
- A held asset with no usable history is excluded and reported, never silently dropped:
  the carrier names the included and excluded symbols and the covered weight, so the
  panel can show how much of the book each figure covers. Metrics gate on the number
  of aligned observations, not on covered weight alone.
- The risk-free rate is de-annualised as `annual_pct / 100 / 252` on this series.

The default window is 250 days (the Basel one-year observation period).

## Trading-day analytics (`mahad/engine/risk_metrics.py`)

### Historical VaR and Expected Shortfall

On the ascending order statistics of the return window:

    m       = floor((1 - c) x T) + 1
    VaR_c   = -r(m)
    ES_c    = -mean(r(1) .. r(m))

VaR is the m-th worst observed loss, with no interpolation - conservative and
reproducible by hand. The Expected Shortfall tail is inclusive of the VaR observation,
so `ES_c >= VaR_c` at the same confidence by construction.

### Parametric (variance-covariance) VaR

    VaR_c = -(mu - z_c x sigma)

with the sample mean and sample standard deviation (ddof = 1). The standard-normal
quantile `z_c` is re-derived by bisection on the normal CDF (no SciPy dependency). The
panel shows both the historical and parametric VaR and the gap between them; the gap is
itself information about tail fatness.

The standard-normal Expected Shortfall multiplier is

    ES_c / sigma = phi(z_c) / (1 - c)

At c = 97.5% this is 2.3378, close to the 99% VaR multiplier 2.3263 - the documented
reason the Fundamental Review of the Trading Book replaced 99% VaR with 97.5% ES.

### Kupiec proportion-of-failures and the Basel traffic light

The Kupiec POF likelihood-ratio test is distributed chi-square with one degree of
freedom under correct coverage; the 5% critical value is 3.8415 (the 0.975 normal
quantile squared). Too few exceptions is also a coverage failure, so a clean window can
still reject.

The Basel traffic light (BCBS, 1996) is a separate framing at 99% over 250 days:
GREEN for 0 to 4 exceptions, YELLOW for 5 to 9, RED for 10 or more. The two readings
are reported side by side because they answer different questions; a window can sit
Basel-GREEN while the Kupiec test rejects.

The backtest is also run in a labelled backcast mode: the trailing-window VaR is rolled
day by day across the cached history and compared against realised returns ("today's
weights applied to history"), kept visually distinct from the accruing ex-ante series.

### EWMA volatility

The RiskMetrics recursion with lambda = 0.94:

    sigma_t^2 = lambda x sigma_(t-1)^2 + (1 - lambda) x r_(t-1)^2

seeded by default with the window's sample variance. It returns the final sigma.

### Beta

    beta = Cov(r_p, r_b) / Var(r_b)

over the common window. The degrees-of-freedom term cancels when applied consistently;
the benchmark's beta against itself is exactly 1.

### Sharpe and Sortino

    Sharpe  = mean(r - rf) / sd(r - rf, ddof = 1),   annualised x sqrt(252)
    Sortino = (mean(r) - target) / DD_dev,           annualised x sqrt(252)

The Sortino downside deviation uses the full-N form `sqrt(mean(min(r - target, 0)^2))`
with target 0 (the Sortino-Price convention). Dividing by the count of downside
observations instead of N is a common implementation slip, so the choice is stated here.

### Correlation and concentration

Pairwise Pearson correlation over the most recent window (90 observations by default)
gives the held-assets matrix
(diagonal 1.0; undefined pairs left empty). The diversification drill-down reduces that
matrix to the average off-diagonal correlation and the most and least correlated pairs.

Concentration uses the Herfindahl-Hirschman Index on position weights (cash excluded):

    HHI         = sum w_i^2          (lies in [1/n, 1])
    effective N = 1 / HHI

with an optional sector roll-up that sums weights per sector and squares those.

### Drawdown duration

A separate function on the same value series finds the worst peak-to-trough pair and the
time from the peak to the first later sample at or above that peak. It reports
"ongoing (n periods)" when the drawdown has not recovered. It is kept separate from the
value-history drawdown in `mahad/engine/risk.py`, which it does not call.

### Component VaR (Euler decomposition)

A parametric, additive decomposition of portfolio risk onto positions:

    Sigma w           the covariance matrix times the weight vector
    sigma_p           = sqrt(w^T Sigma w)
    MCTR_i            = (Sigma w)_i / sigma_p          (marginal contribution)
    CCTR_i            = w_i x MCTR_i                    (sum_i CCTR_i = sigma_p)
    component VaR_i   = z_c x CCTR_i                    (sum_i = z_c x sigma_p)
    share_i           = CCTR_i / sigma_p               (sum_i = 1)

The covariance matrix is the sample estimate (ddof = 1) on the aligned return vectors.
A hedging position contributes negative risk by design. The figure is parametric,
normal, zero-mean and daily, and is labelled separately from the historical and
parametric portfolio VaR.

### Return on VaR and rolling VaR

Return on VaR is `pnl / VaR_usd` (the desk read of P&L against capital at risk),
defined only when VaR is positive. Rolling VaR is a short history of the trailing-window
historical VaR, the same metric tracked over time.

### Stress replay

Linear re-pricing of a historical window:

    stressed P&L = V x sum_i (w_i x R_i(window))

exact for a long-only, no-derivatives book. Each leg names its source ("cache" or
"constant"); a symbol with no window data becomes a no-data leg, and the result
reports the covered weight so partial coverage is never read as full.

## The annualisation rationale

The standard equities convention annualises daily volatility with sqrt(252), the
trading-day count. The analytics suite (Sharpe, Sortino, the VaR series) follows that
convention, because it runs on a trading-day return series aligned to the US calendar.

The headline value-history volatility instead annualises on a calendar wall-clock basis
(1d -> 365), for three reasons:

1. **Multi-asset consistency.** The book mixes equities, which trade about 252 days a
   year, with crypto, which trades 365. A single calendar basis is consistent across
   both rather than privileging the equity calendar.
2. **24/7 sampling.** The value history is sampled on a fixed wall-clock cadence,
   including weekends and holidays for crypto, so the natural period count is calendar
   time, not trading sessions.
3. **Determinism.** A fixed calendar constant is reproducible and does not depend on a
   calendar lookup at sample time.

The trade-off is that non-trading periods contribute near-zero returns, which damps the
annualised figure. So the per-period volatility is the headline, and the annualised
value-history figure is treated as indicative. The trading-day suite, where the 252
convention is the right one, carries the annualised ratios.
