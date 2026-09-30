# What each input means

Taken from the user guide to Choi, Liu and Liu (2025). Getting these definitions
wrong is the most likely way to get a wrong answer out of a correct model, so
they are recorded here rather than left to the interface.

The market inputs below are the American variant's. The Italian variant keeps
the same definitions and changes the sources, and its methodology,
`variants/it/methodology.html`, gives each one.

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
observe. Choi makes it a user input and offers a default of 5%, justified as
"what is implied by current stock market valuation ratios if those ratios stay
constant and future dividend or earnings growth equals its long-run historical
average". He specifies no estimator.

**One estimator is used**, and it is that sentence written as arithmetic. The
figures on this page are those of 3 September 2026, the data the methodology
was written with; the tool shows the current ones.

| Term | Source | 3 Sep 2026 |
| --- | --- | --- |
| Dividend yield | Dividends over price, same month of Shiller's workbook | 1.10% |
| Real earnings growth | 100-year trend through log real earnings per share, Shiller | 2.29% |
| Repricing | Set to zero, which is what "ratios stay constant" means | 0.00% |
| **Expected real return** | | **3.38% compound** |
| | converted once, at the point the model reads it | **4.92% arithmetic** |

**Not the payout yield.** Buybacks return a further 1.53%, and it is tempting to
add them, since a buyback is cash reaching a shareholder. It would be double
counting. Retiring shares is exactly what makes earnings *per share* grow, so a
buyback is already inside the growth term; adding it again as income counts it
twice and overstates the expected return by the buyback yield. This tool made
that mistake until September 2026, and correcting it moved the default
household from 70% equities to 38%. Section 3.1 of the methodology works the
arithmetic through on a single company, and reports a backtest against realised
returns since 1910.

The correct alternative pairing, a payout yield with *aggregate* earnings
growth, is unavailable rather than rejected: aggregate growth needs a share
count and the S&P earnings history is per share.

Three others are computed as cross-checks and are **not used**: Damodaran's
implied premium (7.05%, the outlier, embedding near-term analyst growth
forecasts and quoted against the wrong maturity), a regression of realised
30-year returns on valuation (5.32%, R2 of 0.19 on about four independent
periods), and an earnings anchor built the way AQR builds theirs, a cyclically
adjusted earnings yield at a 50% payout plus 1.8% equilibrium growth (3.13% on
29 September 2026). Section 3.1 of the methodology gives the full reasoning.

The choice matters more than any other in the tool: across the five estimators
Table 5 of the methodology compares, from the cyclically adjusted earnings
yield to Damodaran's premium, the recommendation for the default household
runs from 19% to 100%.

### Why the horizon of the regression matters

The relation between valuation and subsequent return weakens sharply as the
horizon lengthens. Fitted on the same data, the slope falls from 0.86 at ten
years to 0.24 at thirty, and today's stretched valuation therefore predicts:

| Horizon | Predicted real return |
| --- | --- |
| 10 years | 2.74% |
| 20 years | 3.75% |
| 30 years | 5.32% |

A lifetime model must use a long horizon. On the same data and the same day,
the ten-year figure gives the default household 26% in equities and the
thirty-year figure 78%. That gap is the horizon mismatch, not a finding.

### Risk aversion: the guide's scale is not the paper's grid

The guide publishes a table from 1 to 10 and the tool accepts that range. The
paper solves the model at **4, 5, 6, 7, 8, 9 and 10** only. An answer implying
less than 4 is extrapolation, though on the side where the answer saturates at
100% and therefore matters least. Section 3.6 of the methodology has the detail.

### The statistical caveat that matters

The regression uses overlapping windows, so its 1,387 observations contain only
about **four independent** thirty-year periods. The reported error divides the
residual spread by the square root of that number, not of 1,387. It is roughly
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

At 17.2% volatility that is worth **1.54 percentage points**: 3.38% compound
becomes 4.92% arithmetic. Feeding the compound figure straight in would
understate the input by those 1.54 points, which is most of the equity
premium: over the 2.96% real safe rate the premium is 1.96 points, and it
would shrink to 0.42.

The intuition: +50% then −50% averages to zero, but leaves you down 25%. The
arithmetic mean always sits above what money actually grows at, by roughly half
the variance.

### A cross-check worth making once a year: AQR

Choi anchors his own 2% figure to AQR's year-end 2023 forecast of **1.9%** for
US large-cap equities' log excess return over cash, from their Capital Market
Assumptions. The publication is free but arrives as an annual PDF, so it is
compared by hand rather than fetched.

The comparison is unusually clean, because AQR builds its equity forecast the
way this tool does: a dividend yield, plus real growth in earnings per share,
plus no repricing. Their 2026 edition puts US large caps at **3.9% real**, from
a 1.3% yield and 2.7% growth, against this tool's 3.38% on 3 September 2026,
from 1.10% and 2.29%. Most of the half point between them is growth: AQR
starts from 25-year growth and shrinks it towards the global average,
forecast GDP growth and an equilibrium rate, where this tool fits a
hundred-year trend. Section 8.3 of the
methodology sets the two side by side, with nine other firms.

Compare the total real return, as that section does, rather than a premium.
AQR's premium is over cash and this tool's safe asset is a 30-year TIPS, and a
premium quoted in one year sits on that year's real rate, so two premiums from
different years or over different safe assets do not measure the same thing.

### To override

```bash
python update.py --fixed-return 0.05
```

The figure is taken as an **arithmetic** mean, the form the model uses, so
0.05 is Choi's default as he states it. The page's own override slider takes a
compound rate instead, the form forecasts are published in, and converts it.

### One more thing the answer depends on: the fitted range

Choi fitted his approximation over **log** excess drifts of 2%, 3% and 4%, where

    pi = ln(1 + mu) - sigma^2 / 2 - ln(1 + r)

An arithmetic premium is not that quantity: at 18.5% volatility the two differ
by 1.71 points. At today's real rate of about 3%, an expected return below
roughly 6.9% puts the log drift **below** the range the coefficients were fitted
over, and the 30-year real rate sits above the 0% to 2% range fitted for the
safe rate as well. Choi's own guide defaults, 5% and 2.5%, sit outside it too.
The answer is then an extrapolation and should be read as indicative.

`update.py` says so every time it refreshes. The page shows the drift in its
inputs table, Exhibit 5, but prints no warning beside the answer. Section 3.6
of the methodology sets out what being outside the range affects, which is the
value of future wages, and what it does not, which is the Merton share.

## Real risk-free interest rate

The return on the safe asset, above inflation. The guide suggests the **30-year
TIPS yield**, which is a real yield directly and needs no inflation adjustment.

The tool works before tax. If most of your bonds sit in a taxable account,
the guide says to reduce the rate by your marginal income tax rate, which
understates the tax: the yearly inflation increase in a TIPS principal is
taxed as income too, in the year it occurs (IRS Publication 1212). What is
left after tax is roughly `r(1 - t) - t * inflation`. At a 3% real yield, 2.5%
inflation and a combined 30% rate that is about 1.4%, not the 2.1% that
multiplying by 0.7 gives. Section 3.3 of the methodology has the detail.

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
