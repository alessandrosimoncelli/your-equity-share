# Variants

Two countries, one model.

```
variants/
  us/  market_data.toml   methodology.html
  it/  market_data.toml   methodology.html   (not written yet)
```

Each folder holds everything a country owns: the market data its tool reads,
and the document that argues for it. The filename does not repeat the country,
because the folder already says it and saying it twice is how two files drift
apart.

## What is deliberately not split

`src/your_equity_share/` is one model, shared, and it should stay that way.

That is not laziness about copying files. It is the property several rounds of
work were spent establishing: **both variants use the same estimator, so the
gap between a 21% American answer and a 64% Italian one is the country rather
than the method.** Both take the dividend yield from their own index, both take
real growth in earnings per share from the same hundred-year trend through
Shiller, both assume no repricing, and a test asserts the growth term is
identical to five decimal places rather than merely close.

Duplicate the model into two folders and that guarantee is gone within a month.
The two would be edited on different days, and every later comparison between
them would silently mix a country difference with a code difference.

## What each variant does differ in, and where it is argued

|  | United States | Italy |
|---|---|---|
| equity sleeve | S&P 500 | FTSE All-World |
| dividend yield | Shiller, trailing over today's price | MSCI ACWI in euro, same construction |
| real growth | 100-year Shiller trend | the same number, and `us_vs_global.py` measures what that substitution costs |
| safe asset | FRED DFII30, a traded 30-year real yield | ECB AAA 30-year curve less the market break-even |
| volatility | SPY, five years daily | VWCE, five years daily |
| pension | 40% replacement | 74%, from the OECD |
| tax | not modelled | modelled, `src/your_equity_share/taxes.py` |

## Refreshing

```bash
python update.py                      # rewrites variants/us/market_data.toml
python tools/refresh_italy.py --write # rewrites variants/it/market_data.toml
```

`update.py` refuses to touch the Italian file. It learned that the hard way:
run against it once, it wrote the United States TIPS in as the euro safe rate
and deleted the note saying which figures were still guesses.
