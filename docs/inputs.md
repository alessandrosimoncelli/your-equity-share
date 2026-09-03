# What each input means

Taken from the user guide to Choi, Liu and Liu (2025). Getting these definitions
wrong is the most likely way to get a wrong answer out of a correct model, so
they are recorded here rather than left to the interface.

## Risk aversion

One question, from the guide.

> A coin is flipped. Heads, you live on $100,000 for the next year. Tails, you
> live on $50,000. You must spend the whole amount and cannot borrow. A genie
> offers to cancel the gamble and hand you a guaranteed $X instead. What value
> of X leaves you exactly indifferent?

| Your answer | Risk aversion |
| --- | --- |
| $70,710 | 1 |
| $66,667 | 2 |
| $63,246 | 3 |
| $60,571 | 4 |
| $58,566 | 5 |
| $57,083 | 6 |
| $55,978 | 7 |
| $55,143 | 8 |
| $54,499 | 9 |
| $53,991 | 10 |

A lower answer means you dislike risk more. Economists generally work in the 1
to 10 range.

That table is not a lookup table in this codebase: `your_equity_share.risk_aversion`
computes it, because each row is simply the certainty equivalent of the gamble
at that level of risk aversion. `gamma_from_certainty_equivalent` inverts it, so
any answer maps to a value, not only the ten printed above.

This replaces the three-part willingness / ability / need scoring the earlier
draft used. That scoring was an advisory heuristic; this is the definition of
the parameter the model actually contains.

## Investable net worth

Non-housing assets, minus non-mortgage debt.

**Include** cash, current and savings balances, and stocks, bonds, funds and
ETFs held in brokerage or retirement accounts such as 401(k)s and IRAs.
**Subtract** credit card balances, car loans and other personal debt.

Then reduce it by tax that will be owed when the assets are sold and spent:

- Roth 401(k) and Roth IRA: no adjustment.
- Ordinary taxable accounts: a small adjustment in principle, since the cost
  basis is not taxed again. The guide says leaving it alone is tolerable.
- Pre-tax 401(k) and traditional IRA: the whole balance is taxable on
  withdrawal. Multiply by 0.8 if you have no better estimate of the rate.

Housing is excluded entirely.

## Wages and retirement benefits

**After tax, and in today's dollars.** Both matter. A gross figure overstates
human capital, and a nominal one overstates it further the longer the horizon.

Include employer retirement contributions such as a 401(k) match. Where those
go in before tax, which is usual, multiply them by 0.8 for the same reason as
above.

Figures run to age 100. That does not assume you live to 100: the underlying
model applies a probability of dying each year taken from United States
mortality statistics, so later years are already weighted by the chance of
being alive to receive them.

If you do not know your Social Security benefit, the guide's estimate for a
college graduate is **40% of the after-tax wage in the year before claiming**,
then flat for life. Where one spouse earned much less, they will usually claim
the spousal benefit instead, **50% of the higher earner's**.

## Expected stock market real return

The input the recommendation is most sensitive to, and the one nobody can
observe. It is **built from public data three independent ways** and the median
is used.

| Method | What it is | Latest |
| --- | --- | --- |
| Implied premium | Damodaran's implied equity risk premium, a discounted cash flow on the index, plus the real risk-free rate | 7.07% |
| Building blocks | Payout yield (dividends and buybacks) plus 100-year real earnings growth per share, no repricing | 5.13% |
| Valuation regression | Realised 30-year real returns regressed on the cyclically adjusted earnings yield across Shiller's history since 1881, read off today's valuation | 5.17% |
| **Median, used** | | **5.17%** |

They span nearly two percentage points. That spread is the honest measure of how
little is known here, and the tool reports it rather than hiding it.

Two of the three land at about 5.15%, which independently reproduces the 5%
default in Choi's guide and its stated reasoning. The implied premium is the
outlier: it embeds near-term analyst growth forecasts, which run high.

### Why the horizon of the regression matters

The relation between valuation and subsequent return weakens sharply as the
horizon lengthens. Fitted on the same data, the slope falls from 0.91 at ten
years to 0.26 at thirty, and today's stretched valuation therefore predicts:

| Horizon | Predicted real return |
| --- | --- |
| 10 years | 2.37% |
| 20 years | 3.54% |
| 30 years | 5.17% |

A lifetime model must use a long horizon. Using the ten-year figure would put
the recommendation at zero equities, which is an artefact of the horizon
mismatch, not a finding.

### The statistical caveat that matters

The regression uses overlapping windows, so its 1,350 observations contain only
about **four independent** thirty-year periods. The reported error divides the
residual spread by the square root of that number, not of 1,350. It is roughly
0.7 percentage points, and that is generous.

### Compound is not arithmetic, and the gap is 1.5 points

Every forward-looking estimate of equity returns is naturally a **compound**
return. A discounted cash flow gives an internal rate of return. Gordon's
formula gives a discount rate. A regression on realised annualised returns gives
an annualised return. All three compound.

Choi's input slot is an **arithmetic mean**, which you can see in his own
regressor subtracting sigma squared over two. So the estimate is converted once,
at the point it is handed to the model:

    arithmetic = exp( ln(1 + compound) + sigma^2 / 2 ) - 1

At 17.2% volatility that is worth **1.56 percentage points**: our median of
5.17% compound becomes 6.74% arithmetic. Feeding the compound figure straight in
would understate the input by more than the entire equity risk premium is
currently worth.

The intuition: +50% then −50% averages to zero, but leaves you down 25%. The
arithmetic mean always sits above what money actually grows at, by roughly half
the variance.

### A cross-check worth entering by hand: AQR

Choi anchors his own 2% figure to AQR's year-end 2023 forecast of **1.9%** for
US large-cap equities' log excess return over cash, from their Capital Market
Assumptions. That publication is free but arrives as an annual PDF, so it is not
automated here.

It is worth knowing how it maps onto this model, because it maps unusually well:

- It is already a **log** excess return, so it is directly comparable to the
  `pi` the tool prints, with no conversion.
- It is measured **over cash**, whereas this model's safe asset is a 30-year
  TIPS. With the real curve upward sloping, an excess over cash is larger than
  an excess over a long real bond by roughly the real term premium, currently
  about half a point.

So AQR's 1.9% over cash is roughly 1.4% over a long real bond, against the 1.87%
this tool currently computes. Close enough to be reassuring, and a sensible
annual sanity check.

### To override

```bash
python update.py --fixed-return 0.05
```

### One more warning the tool gives you

Choi fitted his approximation over **log** excess drifts of 2%, 3% and 4%, where

    pi = ln(1 + mu) - sigma^2 / 2 - ln(1 + r)

An arithmetic premium is not that quantity: at 18.5% volatility the two differ
by 1.71 points. At today's real rate of about 3%, an expected return below
roughly 6.9% puts the log drift **below** the range the coefficients were fitted
over, and the tool says so. Choi's own guide defaults, 5% and 2.5%, sit outside
it too. The answer is then an extrapolation and should be read as indicative.

## Real risk-free interest rate

The return on the safe asset, above inflation. The guide suggests the **30-year
TIPS yield**, which is a real yield directly and needs no inflation adjustment.

If most of your bonds sit in a taxable account, reduce it by your marginal
income tax rate: at a combined 30%, multiply by 0.7.

This project takes the real rate as a single input for that reason. Deriving it
as a nominal yield minus an inflation expectation invites a maturity mismatch,
since the freely available series are a 3-month bill and a 10-year breakeven,
and the difference between them is neither a 3-month nor a 10-year real rate.

## What the model assumes about you

Two assumptions are built into the fitted coefficients and cannot be changed
from the interface.

**Your earnings are as risky as an average college graduate's.** The paper
solves separately for other education levels; the spreadsheet this project
follows uses the college-graduate calibration.

**Your equity holding is well diversified**, an index fund rather than a handful
of positions. The guide is explicit that the recommendation does not hold
otherwise, because the model's single risky asset is the market.

## Outputs

**Equity portfolio share.** The percentage of your financial portfolio the model
puts in the stock market.

**Human capital value.** The present value of future wages and benefits. For
information only.

**Equity share without human capital.** The Merton (1969) answer for someone
with no future earnings. For information only, and useful mainly to show how
much of the recommendation the human capital adjustment is responsible for.
