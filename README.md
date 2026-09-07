# your-equity-share

How much of a household's portfolio belongs in equities, from the Merton share
and a human capital multiplier.

The model has two layers. Layer one gives the equity share of **total** wealth
(Merton, 1969). Layer two accounts for the fact that most of a working
household's total wealth is future wages, which cannot be sold, and converts
that into an instruction about the tradeable portion (Bodie, Merton and
Samuelson, 1992), using the approximation of Choi, Liu and Liu (2025).

```
w_fin = clip( [ln(1+mu) - ln(1+r)] / (gamma * sigma^2) * (1 + HC/W), 0, 1 )
```

- **What each input means:** [docs/inputs.md](docs/inputs.md)
- **Full derivation and sources:** [docs/methodology.html](docs/methodology.html)

**For** money you have invested and do not need on any particular date, meant
to last the rest of a life. United States only: the earnings profile, the
mortality table and the retirement benefit are all American. Following Choi,
the earnings risk is the average for **college graduates**; his spreadsheet
declares the same assumption and this one does not vary it, because the
estimates behind it are a cross-section of the 1970s to 1990s and there is no
reason to think the relationship between education and earnings risk is
stable.

**Not for** money with a date on it, a house, or a business. Horizon does not
appear in the Merton share at all, which is a result rather than a
simplification, so a model without one cannot tell money needed in three years
from money needed in forty. Section 1.1 of the methodology has the argument.

## Before you use it, refresh the data

**Run it monthly.** The tool warns on its own face once the data is more than
90 days old, and the underlying sources move at different speeds: the TIPS
yield daily, Damodaran's premium monthly, Shiller's history monthly but always
a quarter behind, because earnings arrive after the prices they belong to.
Double-click `update.bat`, or run `python update.py`. Nothing else in the
project touches the network.

```bash
python update.py
```

That is the whole thing. It fetches the latest market data, saves it, and tells
you what changed. Windows users can double-click `update.bat` instead.

```
Updating market data for Your Equity Share
==============================================================

Fetching...
  real risk-free rate (30y TIPS)      2.96%   was  2.96%   unchanged
  stock volatility (SPY, 5y)         17.18%   was 17.18%   unchanged

  Expected real return on equities.
    building blocks                3.38%   <- used
      1.10% dividend yield plus 2.29% real earnings growth
      per share (100 year trend), no repricing
      Buybacks return a further 1.53% that this does not
      count as income, because per-share growth already
      carries it.

  Cross-checks, not used.
    implied premium                7.05%
    valuation regression, 30y      5.32% +/- 0.74%
    spread of the cross-checks     3.67%   <- how little is known here

    as an arithmetic mean          4.92%   +1.54 from the volatility drag

Saved. Market data is now current to 2026-09-03.
```

**All three** numbers the model uses are fetched, from free sources that need no
key or account:

| Input | Source | Note |
| --- | --- | --- |
| real risk-free rate | FRED, 30-year TIPS yield | a real yield already, no inflation adjustment |
| stock volatility | Yahoo, daily **adjusted** closes | dividend and split adjusted, so total returns |
| expected stock return | Shiller: dividend yield plus 100-year real growth in earnings per share | Choi's own stated rationale, written as arithmetic |

The expected return is the number the answer is most sensitive to and the one
nobody can observe. Two further estimates are computed as cross-checks and
reported alongside, precisely because they disagree by several points. Override
it with `--fixed-return 0.05` if you prefer your own view. See
[docs/inputs.md](docs/inputs.md) for why buybacks are deliberately not added to
the yield, and for the caveat on combining a 10-year-based premium with a
30-year real yield.

Options:

```bash
python update.py --dry-run    # show what would change, save nothing
python update.py --years 10   # estimate volatility over ten years
python update.py --fixed-return 0.05   # set the expected return by hand
python update.py --force      # save even if a price series fails its checks
```

If a provider is unreachable the script says so, leaves the file untouched, and
exits non-zero. **The tool itself never touches the network**, so a slow or dead
provider can never break a demonstration; it simply runs on the data it has.

## Why this approach

Choi, Liu and Liu solved the underlying life-cycle model for 5,103 parameter
sets and measured what each portfolio rule costs, as the reduction in lifetime
consumption that produces the same loss of expected utility:

| Rule | All parameter sets | gamma = 4 | gamma = 10 |
| --- | --- | --- | --- |
| This approximation | **0.06%** | 0.03% | 0.07% |
| 100 minus your age in equities | 2.00% | 2.11% | 4.11% |
| Constant 60% equities | 3.75% | 1.58% | 9.27% |
| Never hold equities | 7.86% | 7.93% | 7.09% |
| Always 100% equities | 11.85% | 0.56% | 29.55% |

Risk aversion decides the answer more than anything else, which is why the tool
elicits it with Choi's certainty-equivalent question rather than a questionnaire,
and reports a range across plausible values.

## Status

Built in stages, so the effect of each correction is measured rather than
asserted.

| Stage | State |
| --- | --- |
| 1. Faithful port of the source spreadsheet, with regression baseline | **done** |
| 2. Market data pipeline and risk-aversion elicitation | **done** |
| 3. Choi's formula: human capital, discount rates, imputed earnings | **done** |
| 4. Validated against Choi's own spreadsheet, both tabs | **done** |
| 5. Browser front end | **done** |
| 6. Published as a static site, model ported to JavaScript | **done** |
| 7. Validated against twelve published forecasts, and swept for properties | **done** |
| 8. Portfolio analytics and factor exposure | planned |

### The published site

`python tools/build_web.py` writes `web/`, four files and about 100 KB, which
any static host serves. It opens in well under a second and needs no server,
so nothing a visitor enters is transmitted anywhere.

The page runs `src/js/model.js`, a port of the model. **Python remains the
reference implementation.** The two are held together by `tests/golden.json`,
written by `tools/make_golden.py` and replayed through the port by
`tools/check_golden.mjs`, which `pytest` also runs. Only the model crossed
over: fetching, parsing, volatility, the expected-return estimators and the
frozen spreadsheet baseline all stay in Python, because they run here and not
in a reader's browser.

Two earlier versions are gone. The first shipped Streamlit compiled to
WebAssembly: faithful, and about thirty seconds to start, because the cost is
the Python interpreter booting rather than downloading. The second was a
Streamlit app run locally, retired once the browser build replaced everything
it did. Keeping two front ends meant keeping two of them current, and the
second had already drifted.

### Stage 1: the baseline

`your_equity_share.legacy` reproduces the "Merton Share" worksheet of
`QUANTO DEVO INVESTIRE IN AZIONI.xlsx` exactly, **defects included**. It exists
to be a fixed reference point, not to give advice.

Expected values are not transcribed. `tools/extract_baseline.py` reads them
straight out of the workbook into `tests/baseline_cells.json`. A passing run is
therefore evidence that the port matches the spreadsheet, rather than evidence
that the port and the test share a typo. Comparison is exact equality: the port
applies the same operations in the same order as each worksheet formula, so the
results are bit-identical doubles.

Cell `G4`, the Merton share, reproduces as `0.8156054116198155`.

Four defects are reproduced deliberately and pinned by their own tests, so that
fixing each produces a visible, measured change:

| Defect | Effect | Fixed in |
| --- | --- | --- |
| Denominator averages the sleeves' variances instead of using `w'Sigma w` | Overstates risk, understates allocation by 8.3 points on measured correlations | Stage 3 |
| Numerator uses the arithmetic excess return, not a difference of drifts | Overstates the numerator by 3.6% on these inputs | Stage 3 |
| Gamma is the mean of three scores on a 2 to 5 scale | Layer two expects 1 to 10 | Stage 3 |
| Expected inflation hardcoded at 2.5% inside the real rate | Not a supplied assumption | Stage 3 |

## Use

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

Then ask it the question. There are two ways in.

**In a browser**, which is the tool proper:

```bash
python tools/build_web.py
python -m http.server 8600 --directory web
```

Then open http://localhost:8600. Sliders for risk aversion and the expected
return, so you can see by dragging how much the answer depends on each. The
recommendation with its working, a sensitivity curve, the answer at every level
of savings, and a box for typing your earnings year by year.

The same folder is what gets published: drop `your-equity-share-site.zip` on a
static host and that is the whole deployment.

**In the terminal**, for a quick answer or for scripting:

```bash
python recommend.py                                          # asks you the inputs
python recommend.py --age 45 --wage 100000 --wealth 500000   # or pass them
python recommend.py --age 45 --wage 100000 --wealth 500000 --glide
```

From Python:

```python
from your_equity_share import Household, Person, recommend
from your_equity_share.market_data import load_market_data

market = load_market_data()
result = recommend(
    Household(500_000, [Person(45, 100_000)], risk_aversion=5),
    market.expected_stock_real_return,
    market.real_risk_free_rate,
    market.stock_volatility,
)
result.equity_share          # the recommendation
result.uncapped_share        # before the no-leverage cap
result.human_capital         # present value of future earnings
```

### Validation

Both tabs of Choi's published spreadsheet are reproduced exactly, which is the
regression baseline for stage 3:

| Case | Quantity | Spreadsheet | This code |
| --- | --- | --- | --- |
| Wage imputed | human capital | 2,133,150.455 | matches to the cent |
| Wage imputed | equity share | 0.8920794261 | matches to 1e-9 |
| Full inputs | human capital | 2,199,507.502 | matches to the cent |
| Full inputs | equity share | 0.9145603885 | matches to 1e-9 |

## Sources

- Merton, R. C. (1969). Lifetime Portfolio Selection under Uncertainty. *Review of Economics and Statistics*, 51(3).
- Bodie, Z., Merton, R. C. and Samuelson, W. F. (1992). Labor Supply Flexibility and Portfolio Choice in a Life Cycle Model. *JEDC*, 16.
- Cocco, J. F., Gomes, F. J. and Maenhout, P. J. (2005). Consumption and Portfolio Choice over the Life Cycle. *RFS*, 18(2).
- Choi, J. J., Liu, C. and Liu, P. (2025). Practical Finance: An Approximate Solution to Lifecycle Portfolio Choice.

## Disclaimer

Educational and illustrative only. Not investment, financial, tax or legal
advice, and no advisory relationship is created by its use. Outputs depend
entirely on the assumptions documented in `docs/methodology.html`.
