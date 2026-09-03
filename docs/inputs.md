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

That table is not a lookup table in this codebase: `merton_share.risk_aversion`
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

Your estimate of the average return of the stock market over your lifetime,
above inflation. The guide's default is **5%**.

A more precise way to set it than a single guess is to build it from parts:

    expected real return
      = dividend yield
      + net buyback yield
      + real earnings growth
      + repricing

The first three are close to observable. Only repricing, the change in the
multiple the market pays, is a forecast of sentiment. Setting it to zero and
adding the rest is exactly how the guide's 5% arises: a dividend yield around
1.3%, a net buyback yield around 0.5% and real earnings growth around 3.2%.

Setting repricing to zero is an assumption, not a neutral choice. A market
priced above its own history has a negative expected repricing term that this
sum ignores, so 5% would then be too high.

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
