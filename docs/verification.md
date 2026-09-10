# Verification

Every formula in the engine has a hand-worked reference on small inputs. That reference
is the answer key: the test suite pins each function to these exact values, so a
regression in any formula fails a test rather than drifting silently. Anyone can
reproduce each figure from the inputs below with a calculator.

The pinned tests are `tests/test_risk.py` (the value-history metrics),
`tests/test_returns.py` (the return series, checks M and N) and
`tests/test_risk_metrics.py` (the trading-day analytics).

## Worked vectors

| Check | Function | Input | Expected |
|-------|----------|-------|----------|
| A | `z_quantile` | c = 0.95 / 0.975 / 0.99 | 1.6449 / 1.95996 / 2.3263 |
| B | `historical_var`, `expected_shortfall` | T = 100, c = 95% | m = 6, VaR = 2.50%, ES = 3.4667% |
| C | `parametric_var_from_moments` | mu = 0.04%, sigma = 1.2% | VaR95 = 1.9338%, VaR99 = 2.7516% (1,933.82 USD on 100,000) |
| D | `normal_es_multiplier` | c = 97.5% | 2.3378 (vs z_0.99 = 2.3263; the FRTB switch) |
| E | `kupiec_pof` | T = 250, p = 0.01 | x = 0 -> LR 5.0252 reject; x = 4 -> 0.7691 accept; x = 7 -> 5.4970; x = 10 -> 12.9555 |
| E | `basel_zone` | 99% / 250d | P(X<=4) = 0.8922, P(X<=9) = 0.99975; GREEN 0-4, YELLOW 5-9, RED 10+ |
| F | `ewma_volatility` | seed variance 1e-4 | 1.0000% -> 1.0863% -> 1.0603% |
| G | `beta` | worked vectors | 1.1600; benchmark against itself = 1 |
| H | `sharpe` | excess mean 0.0008, sd 0.002550 | daily 0.3138, annual 4.9812 |
| H | `sortino` | DD_dev 0.0010 | daily 1.0000, annual 15.8745 |
| I | `drawdown_duration` | [100, 110, 99, 104.5, 112, 108] | -10.00%, peak 1, trough 2, recovery 4, duration 3 |
| J | `concentration` | weights [0.5, 0.3, 0.2] | HHI 0.3800, effective N 2.6316; five equal -> 0.2000 / 5.0000 |
| K | `correlation` | worked 4-point pair | 0.9950 |
| L | `stress_replay` | V 100,000; w {40, 35, 25}%; R {-30, -25, -40}% | -30,750.00 USD |
| M | `rf_daily_from_annual_pct` | 5.25% annual | 0.00020833 (2.0833 bp/day) |
| N | `single_day_return` | w [0.6, 0.4], R [0.01, -0.005] | 0.0040 |

## Conventions that the vectors lock in

- **Order statistics, not interpolation.** Historical VaR uses `m = floor((1 - c)T) + 1`
  and reads the m-th worst loss directly, so the same window always gives the same
  figure.
- **Tail inclusive of VaR.** Expected Shortfall averages observations 1..m, so
  `ES >= VaR` at the same confidence by construction (check B).
- **ddof = 1 for standard deviation and covariance.** Sample standard deviation and covariance use the unbiased
  divisor; the degrees-of-freedom term cancels in beta when applied consistently.
- **No SciPy.** The normal quantile is found by bisection on the CDF (check A), and the
  chi-square(1) critical value falls out as the 0.975 quantile squared, 3.8415 (check E).
- **The Euler identity.** Component VaR is checked against its closure properties: the
  component contributions sum to the portfolio sigma, the component VaRs sum to
  `z_c x sigma_p`, and the shares sum to 1.

## Component VaR cross-check

The component-VaR decomposition is checked against a separate first-principles
calculation, which confirms the Euler identities above and that a hedging position
yields a negative contribution. The covariance estimate it relies on is the same
sample covariance (ddof = 1) used elsewhere, and is fuzz-checked against a direct
pairwise computation.
