# What each input means

Taken from the user guide to Choi, Liu and Liu (2025). Getting these definitions
wrong is the most likely way to get a wrong answer out of a correct model, so
they are recorded here rather than left to the interface.

The market inputs below are the American variant's. The Italian variant keeps
the same definitions and changes the sources, and its methodology,
`variants/it/methodology.html`, gives each one.

## Risk aversion

One question, from the guide, which the page asks in three short steps.

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

**On the page it is three short steps.**

1. How willing you are to take risks in financial matters, from 0 to 10. It
   does not change the number; it only flags answers that contradict each
   other.
2. Five choices between the coin and a sure amount, one at a time, each
   amount depending on the answer before, with no range shown and nothing
   preselected. The coin pays what your household lives on now, after tax,
   or half of it: your wage, a second adult's wage and any pension already
   being received, added up, or the guide's own $100,000 when nothing is
   coming in. As in the guide, the whole amount must be spent and nothing
   can be borrowed.
3. A check: the sure amount your choices imply, which you confirm or adjust.

Both percentages are the guide's: its $100,000 is the wage of the paper's
worked example and its $50,000 half of that, and the Health and Retirement
Study frames its own income gambles on current family income the same way.
The table still applies, as shares of the good outcome (70.7% means 1, 58.6%
means 5, 54.0% means 10), because only the ratio of the two outcomes matters.
Each sure amount is the coin's worth at the middle of the range the answers
so far leave open, starting at 62.8% of the good outcome, so the five choices
place risk aversion within about 4%. Section 3.4 of the methodology gives the
sources.

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
  withdrawal. Multiply by 0.8 if you have no better estimate of the rate,
  which is the guide's own default and what the page's hint says.

Housing is excluded entirely.

**It has to be above zero.** Choi's spreadsheet asks for a figure above zero,
and his guide says the model was not solved for negative net worth. When
savings are zero or debts exceed them, the page says the model has no answer
instead of showing a share.

**Retired, or drawing on it?** Include what you will draw down over the years.
Leave out only what you will take from savings this year beyond your pension,
and money set aside for a goal with a date. That is Choi's own accounting. In
his model the money invested this year is cash on hand less this year's
spending, and cash on hand is what you hold plus this year's income (the
paper's section 1.1, equation 5). A retiree's pension this year pays for part
of this year's spending, so only the rest comes out of savings. When this
year's income and spending are about equal, the money invested is simply what
you hold, which is the guide's definition and what the page asks a worker for.
Spending in later years is the model's own consumption, so the savings that
will pay for it stay in.

**On the Italian page** the same rule counts two Italian items. TFR left with
the employer counts at about three quarters, because the rest is its separate
tax, and it belongs to the safe share. Pension funds, including TFR paid into
one, count at about nine tenths, because their benefits are taxed at 15%,
falling to 9% after 35 years of membership (D.Lgs. 252/2005, art. 11(6)).

**Run it again once a year**, and rebalance to the new figure, using new
savings first. The rule is meant to be applied at every age (the paper's
section 4): the share falls as savings grow against future earnings, and a mix
set once and left alone drifts above it.

## Wages and retirement benefits

**After tax, and in today's dollars.** Both matter. A gross figure overstates
human capital, and a nominal one overstates it further the longer the horizon.

Include employer retirement contributions such as a 401(k) match. Where those
go in before tax, which is usual, multiply them by 0.8 for the same reason as
above.

Figures run to age 100. In the guide's words, enter income as if alive in
each year; the calculations allow for United States mortality. They do so
inside Choi's fitted discount rates, which were solved with the American life
table: the income itself is not weighted by the chance of being alive to
receive it, because the paper's expectations are conditional on surviving.

**The career is projected, and so is the pension it pays.** From today's wage
the tool projects your pay along the average college graduate's earnings path
through age 66, the last year anyone works in Choi's model. From the year
after, it adds the pension your own work will pay, at the guide's estimate for
a college graduate: **40% of the after-tax wage in the year before payments
start**, which here is the last year of work,
then flat for life, up to Social Security's maximum: $4,152 a month at full
retirement age in 2026, counted at 0.8 after tax, or $39,859 a year. Above a
final wage of about $100,000 after tax, 40% would be more than Social Security
pays anyone. If you are 66 or older and still earning, this year is taken as
your last year of pay, and the pension starts next year at 40% of today's wage.
To work longer or stop sooner, type the years in the year-by-year box. A break
typed there, with wages after it, pays none of this pension during the break:
it starts after the last year with a wage.

On the Italian page the wage includes the TFR that accrues each year, about
7.5% of net pay after its tax, and the imputed pension is 61.4% of the last
such wage, which is the Italian Treasury's 66% of final net pay without the
TFR.

**A pension whose amount is already fixed** goes in the pension field, a year
of it after tax. Two settings sit beside it.

- **From age.** Left empty, the pension is already being paid. Include it even
  if you still work. An age means it starts then: a company pension from 60,
  or Social Security you will claim at 67 after stopping work at 62.
- **It is my Social Security.** Tick it if the pension in the field is your own
  Social Security: claimed already, even while you still work, or your own
  estimate of it, entered with the age you will claim. It then replaces the
  tool's 40% estimate, as the benefit cell does in Choi's spreadsheet. Left
  unticked, the pension is added to that estimate, which is right for a
  military, company or other employer pension paid on top of Social Security.
  A Social Security disability benefit becomes the retirement benefit at full
  retirement age, so it is ticked too. So is a Social Security survivor's
  benefit larger than your own would be, because Social Security pays only the
  larger of the two.

The tick matters. Social Security already claimed and left unticked is counted
twice: for a 67-year-old still earning $60,000 after tax who already draws
$15,000 of it, with $500,000 saved, the answer is 18.4% ticked and 28.0%
unticked. The Italian page's tick reads "È la mia pensione INPS di vecchiaia"
and works the same way.

A pension in the field that is already being paid, or fixed by an earlier
job, is treated as riskless: it is divided by the benefit discount rates from
today, from the age it starts, rather than carried on the same discount chain
as the wage. An estimate of your own Social Security for a later claim is
different: the rest of your career still moves it, so, ticked, it is
discounted like the 40% estimate it replaces, on the wage rates until your
wage stops. That
departs from Choi's spreadsheet and from his paper (methodology section 7.6).
A pension that does not rise with prices goes in at about four fifths of its
amount.

**The second adult** has the same field, start age and tick. On the American
page they have one more tick: **They will claim the spousal benefit, half of
your Social Security, instead of a pension of their own.** It is the switch in
Choi's spreadsheet. From the year they turn 62, once you have claimed, half of
your Social Security is added to your own and valued with it, on your discount
chain: at the wage rate while it still depends on your future pay, including
when it rests on an estimate you entered for a later claim, and as riskless
where it rests on Social Security you already draw, entered in your field and
ticked. The tool then imputes them no pension of their own. The tick counts
only while their own pension field is empty, because the benefit is claimed
instead of a pension of their own; on the command line `--partner-spousal`
cannot go with `--partner-benefit`. Do not
type the spousal benefit in their pension field instead: there it would be
valued as riskless from today, though it moves with your career.

For the default earner, 45 on $100,000 with $500,000 saved, and a partner of
42 with no wage, the tick takes the answer from 37.3% to 38.4%. For a
one-earner couple, with the earner aged 35 to 55 and the partner two or three
years younger, it is worth about half a point to 3 points with five years of
pay saved and under a point with fifteen. Nearer retirement it is worth more:
4.6 points with five years of pay saved and 1.5 with fifteen, for an earner of
60 and a partner of 58. These are on the data of 3 September 2026. The Italian
page has no such tick, because the benefit is Social Security's.

**Typing earnings year by year** replaces the wage and pension amounts above
with what you type, one line per year to age 100, until you press Reset to
projection. Once you edit a year the pension fields lock, and a pension
entered there before the edit keeps its treatment: they still tell the model
which part of each typed benefit is fixed. Typed only in the box, a pension
that is there from the box's first year counts as one already being paid; one
that starts in a later year is discounted on the same chain as the wage, so a
fixed pension from a later age belongs in the field, with the age it starts.

**On the command line**, `recommend.py` asks for the same things, or takes
them as flags: `--benefit`, `--benefit-start` and `--state-pension` for you;
`--partner-age`, `--partner-wage`, `--partner-benefit`,
`--partner-benefit-start` and `--partner-state-pension` for a second adult;
and `--partner-spousal` for the spousal benefit. It runs the American variant.

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
| **Expected real return** | the three terms compounded, not added | **3.41% compound** |
| | converted once, at the point the model reads it | **5.19% arithmetic** |

**The terms compound.** The yield is trailing: last year's dividends over
today's price. With the ratios held constant, next year's dividends are last
year's grown at the growth rate, and the price grows at the same rate, so
1 + R = (1 + yield)(1 + growth) exactly. Adding the two instead, 3.38%, leaves
out their product.

**Not the payout yield.** Buybacks return a further 1.53%, and it is tempting to
add them, since a buyback is cash reaching a shareholder. It would be double
counting. Retiring shares is exactly what makes earnings *per share* grow, so a
buyback is already inside the growth term; adding it again as income counts it
twice and overstates the expected return by the buyback yield. This tool made
that mistake until September 2026, and correcting it moved the default
household from 65% equities to 37%. Section 3.1 of the methodology works the
arithmetic through on a single company, and reports a backtest against realised
returns since 1910.

The correct alternative pairing, a payout yield with *aggregate* earnings
growth, is unavailable rather than rejected: aggregate growth needs a share
count and the S&P earnings history is per share.

Three others are computed as cross-checks and are **not used**: Damodaran's
implied premium plus the real safe rate (7.07%, the outlier, embedding near-term analyst growth
forecasts and quoted against the wrong maturity), a regression of realised
30-year returns on valuation (5.32%, R2 of 0.19 on about four independent
periods), and an earnings anchor built the way AQR builds theirs, a cyclically
adjusted earnings yield at a 50% payout plus 1.8% equilibrium growth (3.12%).
Section 3.1 of the methodology gives the full reasoning.

The choice matters more than any other in the tool: across the five estimators
Table 5 of the methodology compares, from the cyclically adjusted earnings
yield to Damodaran's premium, the recommendation for the default household
runs from 20% to 100%.

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
thirty-year figure 72%. That gap is the horizon mismatch, not a finding.

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

### Compound is not arithmetic, and the gap is 1.8 points

Every forward-looking estimate of equity returns is naturally a **compound**
return. A discounted cash flow gives an internal rate of return. Gordon's
formula gives a discount rate. A regression on realised annualised returns gives
an annualised return. All three compound.

Choi's input slot is an **arithmetic mean**, which you can see in his own
regressor subtracting sigma squared over two. So the estimate is converted once,
at the point it is handed to the model:

    arithmetic = exp( ln(1 + compound) + sigma^2 / 2 ) - 1

At Choi's 18.5% volatility, which the tool holds fixed, that is worth **1.78
percentage points**: 3.41% compound becomes 5.19% arithmetic. Feeding the
compound figure straight in would understate the input by those 1.78 points,
which is most of the equity premium: over the 2.98% real safe rate the premium
is 2.21 points, and it would shrink to 0.43.

The volatility is not re-measured. It is the 18.5% Choi, Liu and Liu use, the
annualised standard deviation of monthly CRSP log excess returns from 1926 to
2024, and over the whole S&P 500 history daily, monthly and annual returns all
give about that figure (18.9%, 18.5% and 19.0%). A trailing window of a few
years moves the answer each time a crash enters or leaves it, with no change
in the long-run risk the model is about. The Italian variant fixes its own
figure the same way: 16.45%, the same estimator, applied to total rather than
excess returns, on MSCI All Country World in
euro from January 2001 to August 2026, run from every day of the month and
averaged, because over twenty-five years the day each month is cut on matters.
Cut at month-end alone it gives 13.99%, the lowest of them all, since the 2008
and 2020 crashes each fell across two month-ends.

The intuition: +50% then −50% averages to zero, but leaves you down 25%. The
arithmetic mean always sits above what money actually grows at, by roughly half
the variance.

### A cross-check worth making once a year: AQR

Choi anchors his own 2% figure to AQR's year-end 2023 forecast of **1.9%** for
US large-cap equities' log excess return over cash, from their Capital Market
Assumptions. The publication is free but arrives as an annual PDF, so it is
compared by hand rather than fetched.

AQR's forecast has the same three terms as this tool's: a yield, real growth
in earnings per share, and no repricing. Their 2026 edition puts US large caps
at **3.9% real**, from what their Exhibit 3A calls a 1.3% combined payout yield
and 2.7% combined growth, against this tool's 3.41% on 3 September 2026, from
a 1.10% dividend yield compounded with 2.29% growth. Each of their two terms
averages two estimates, one built on the dividend yield and one on an earnings
anchor, so their yield is not a dividend yield alone. Most of the half point between the
totals is growth: AQR starts from 25-year growth and shrinks it towards the
global average, forecast GDP growth and an equilibrium rate, where this tool
fits a hundred-year trend. Section 8.3 of the methodology sets the two side by
side, beside eight other published forecasts.

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

An arithmetic premium is not that quantity: at 18.5% volatility and today's
rates the two differ by 1.80 points, which is half the variance, 1.71, plus
0.09 from taking logs. At today's real rate of about 3%, an expected return
below roughly 6.9% puts the log drift **below** the range the coefficients
were fitted over, and the 30-year real rate sits above the 0% to 2% range
fitted for the safe rate as well. Choi's own guide defaults, 5% and 2.5%, sit
outside it too. The answer is then an extrapolation.

`update.py` says so every time it refreshes. The page shows the drift in its
inputs table, Exhibit 5, and mentions the range beside the risk question only
when risk aversion is below 4, where it is out of range too. Section 3.6 of the
methodology sets out what being outside the range affects, which is the value
of future wages, and what it does not, which is the Merton share, and it
measures the formula's error there.

## Real risk-free interest rate

The return on the safe asset, above inflation. The guide suggests the **30-year
TIPS yield**, which is a real yield directly and needs no inflation adjustment.
The safe part of the answer means TIPS held to maturity, or a ladder of them,
which is what the page names.

**It is annualised first.** Like the Treasury's other par yields it is quoted on a
semiannual basis, and the model reads annual rates, as the Italian variant's
are. So the tool converts it, (1 + y/2)^2 - 1, and keeps the quote beside it:
the 2.96% quoted on 3 September 2026 is 2.98% a year.

The tool works before tax. If most of your bonds sit in a taxable account, the
guide suggests reducing the rate by your marginal income tax rate. The page
does not, so in that case read its answer as low. The guide's rule also
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
