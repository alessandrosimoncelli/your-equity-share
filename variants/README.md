# Variants

Two countries, one model.

```
variants/
  us/  market_data.toml   snapshot.toml   methodology.html
  it/  market_data.toml   snapshot.toml   methodology.html
```

Each folder holds everything a country owns: the market data its tool reads,
and the document that argues for it. The filename does not repeat the country,
because the folder already says it and saying it twice is how two files drift
apart.

Both documents are published beside the tool, the American one at
`/methodology.html` and the Italian one at `/it/methodology.html`.

## Live data and frozen data

`market_data.toml` is live. It is rewritten every Monday when the refresh
passes its checks, so the site and the Python tool run on the latest figures
that did. A week that fails keeps the previous week's.

`snapshot.toml` is frozen. It is the market data the methodology was written
with, and it changes only when the document is rewritten against newer data.
The tests check the figures each document quotes against its snapshot, not
against the live file, and a test holds each snapshot to the date its document
states. They check the inputs a document quotes, not every figure derived
from them.

The split exists because a document quotes numbers. Checked against the live
file, a refresh made the document wrong and failed the build, which is what
happened before the split existed. Checked against its snapshot, the tool can
move with the market while the document stays true to the day it describes.

## What is deliberately not split

`src/your_equity_share/` is one model, shared, and it should stay that way.

That is not laziness about copying files. It is the property several rounds of
work were spent establishing: **both variants use the same estimator, so the
gap between a 21% American answer and a 54% Italian one for the same household
(45, 100,000 a year after tax, 1.5 million saved, risk aversion 5), both before
tax and on the documents' data, is the country rather than the method.** Both take the
dividend yield from their own index, both take real growth in earnings per
share from the same hundred-year trend through Shiller, both compound the two
and assume no repricing, and a test asserts the growth term is identical to
five decimal places rather than merely close.

Duplicate the model into two folders and that guarantee is gone within a month.
The two would be edited on different days, and every later comparison between
them would silently mix a country difference with a code difference.

One difference of basis is left, and it is small. The Italian yield is net of
the withholding tax a world fund suffers abroad, as MSCI's net index measures
it, and that index tracks what the fund delivered after its own costs. The
American figure is before any fund's costs, as in Choi's guide. A 0.03% index
fund would take the American answer for that household from 20.7% to 20.4%.

## What each variant does differ in, and where it is argued

|  | United States | Italy |
|---|---|---|
| equity sleeve | S&P 500 | FTSE All-World |
| dividend yield | Shiller, trailing over today's price | MSCI ACWI in euro, net of the withholding the fund suffers, same construction |
| real growth | 100-year Shiller trend | the same number, and `us_vs_global.py` measures what that substitution costs |
| safe asset | US Treasury 30-year real yield, which FRED republishes as DFII30, annualised from its semiannual quote | ECB AAA 30-year par yield, annualised, less the market break-even of the Bund€i |
| volatility | Choi's 18.5%, CRSP monthly 1926 to 2024, fixed | 16.45%, MSCI ACWI in euro, monthly log returns 2001 to 2026 from every day of the month, averaged and fixed (`tools/italy_volatility.py`) |
| earnings | an American college graduate, Cocco, Gomes and Maenhout | an Italian private-sector employee, Daminato and Padula, Table 7 of working paper CSEF 585 (2020; published 2024) |
| pension | 40% of the final wage, up to Social Security's maximum of $39,859 a year after tax | 61.4% of the final wage with the TFR, which is the Ragioneria Generale dello Stato's 66% of final net pay without it, projected for an average earner retiring in 2050 at 66 years and 2 months |
| spousal benefit | Choi's switch: half of the earner's Social Security, from the partner's 62 | none, as the switch is Social Security's |
| tax | not modelled, as in Choi | not modelled either: measured in section 8 of the Italian methodology, `tools/tax_check.py` |

## Refreshing

GitHub Actions runs both refreshes every Monday, and keeps the result only if
both succeed and every check passes; see the main README. By hand, run both,
in this order, because the Italian refresh takes its growth term from the
Shiller data the American one downloads:

```bash
python update.py                      # rewrites variants/us/market_data.toml
python tools/refresh_italy.py --write # rewrites variants/it/market_data.toml
```

`update.py` refuses to touch the Italian file. It learned that the hard way:
run against it once, it wrote the United States TIPS in as the euro safe rate
and deleted the note saying which figures were still guesses.
