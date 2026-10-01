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
gap between a 21% American answer and a 64% Italian one, both before tax and on
the documents' data, is the country rather than the method.** Both take the
dividend yield from their own index, both take real growth in earnings per
share from the same hundred-year trend through Shiller, both assume no
repricing, and a test asserts the growth term is identical to five decimal
places rather than merely close.

Duplicate the model into two folders and that guarantee is gone within a month.
The two would be edited on different days, and every later comparison between
them would silently mix a country difference with a code difference.

## What each variant does differ in, and where it is argued

|  | United States | Italy |
|---|---|---|
| equity sleeve | S&P 500 | FTSE All-World |
| dividend yield | Shiller, trailing over today's price | MSCI ACWI in euro, same construction |
| real growth | 100-year Shiller trend | the same number, and `us_vs_global.py` measures what that substitution costs |
| safe asset | US Treasury 30-year real yield, which FRED republishes as DFII30 | ECB AAA 30-year curve less the market break-even |
| volatility | SPY, five years daily | VWCE, five years daily |
| earnings | an American college graduate, Cocco, Gomes and Maenhout | an Italian private-sector employee, Daminato and Padula (2024) |
| pension | 40% replacement | 66%, the Italian Treasury's projection for retiring near 67 |
| tax | not modelled | applied to the answer by default, `src/your_equity_share/taxes.py` |

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
