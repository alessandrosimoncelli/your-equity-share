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

- **The tool:** [alessandrosimoncelli.github.io/your-equity-share](https://alessandrosimoncelli.github.io/your-equity-share/), and in Italian at [/it/](https://alessandrosimoncelli.github.io/your-equity-share/it/), market data refreshed every Monday
- **What each input means:** [docs/inputs.md](docs/inputs.md)
- **Full derivation and sources:** [United States](https://alessandrosimoncelli.github.io/your-equity-share/methodology.html) and [Italy](https://alessandrosimoncelli.github.io/your-equity-share/it/methodology.html), from `variants/us/` and `variants/it/`
- **What is not done yet:** [further work](https://alessandrosimoncelli.github.io/your-equity-share/further-work.html)

**For** money you have invested and do not need on any particular date, meant
to last the rest of a life. Two variants share one model. The **United
States** variant holds the S&P 500 against 30-year TIPS. The **Italian**
variant holds a global equity fund against the euro real safe rate, after
Italian tax, for an Italian private-sector employee: Daminato and Padula's
(2024) earnings process, estimated on the Bank of Italy's household survey,
and the Italian Treasury's 66% pension. What neither variant changes is the
mortality table, American in both, because it sits inside the numerical
solution Choi fitted his coefficients to. Section 10 of the Italian
methodology lists what that leaves American.

In the American variant, following Choi, the earnings risk is the average for
**college graduates**; his spreadsheet declares the same assumption and this
one does not vary it, because the estimates behind it are a cross-section of
the 1970s to 1990s and there is no reason to think the relationship between
education and earnings risk is stable.

**Not for** money with a date on it, a house, or a business. Horizon does not
appear in the Merton share at all, which is a result rather than a
simplification, so a model without one cannot tell money needed in three years
from money needed in forty. Section 1.1 of the United States methodology has
the argument.

## The data refreshes itself

**Every Monday** GitHub Actions refreshes the market data of both variants,
runs every check in the project, commits the new figures here, and republishes
the site. The workflow is [.github/workflows/pages.yml](.github/workflows/pages.yml).
It is built to be left alone:

- **Both or neither.** The two variants share their growth term, so a week in
  which one refresh fails keeps last week's data for both rather than
  publishing a mismatched pair.
- **A failure never takes the site down, and is never quiet.** The site stays
  on the last good data, and the run ends red, which GitHub reports by email.
- **New data is committed only after the checks pass.** The commits also keep
  the schedule alive: GitHub switches off scheduled runs in a repository with
  no commits for sixty days.

The tool shows the date of its data on its own face, and warns once it is more
than 90 days old, which would mean the schedule has stopped.

To get the latest figures on your own machine, `git pull`. To refresh by hand,
for example in a copy that is not on GitHub, run both scripts, in this order,
because the Italian one takes its growth term from the Shiller data the
American one downloads. Windows users can double-click `update.bat`, which
does exactly that. Apart from these two and the analysis scripts in `tools/`,
nothing in the project touches the network, and the tool itself never does.

```bash
python update.py
python tools/refresh_italy.py --write
```

A hand refresh leaves the two market data files changed. Discard it with
`git checkout -- variants/` before pulling, or the pull will collide with the
Monday commit.

Part of a dry run of the American refresh, on 29 September 2026:

```
Fetching...
  real risk-free rate (30y TIPS)      3.28%   was  3.22%   +0.06 points
  stock volatility (SPY, 5y)         17.15%   was 17.16%   -0.01 points

  Expected real return on equities.
    building blocks                3.38%   <- used
      1.10% dividend yield plus 2.29% real earnings growth per share (100 year trend), no repricing
      Buybacks return a further 1.53% that this
      does not count as income, because per-share growth
      already carries it.

  Cross-checks, not used. See section 3 of the methodology
  for why each is worse for a lifetime horizon.
    implied premium                7.37%
    earnings anchor                3.13%
    valuation regression, 30y      5.32% +/- 0.74%

    as an arithmetic mean          4.91%   +1.53 from the volatility drag
    spread of the cross-checks     4.24%   <- how little is known here

Dry run, nothing saved. Run without --dry-run to apply.
```

**All three** numbers the American variant uses are fetched, from free sources
that need no key or account. The Italian sources are in
[variants/README.md](variants/README.md).

| Input | Source | Note |
| --- | --- | --- |
| real risk-free rate | US Treasury daily real yield curve, 30 years | a real yield already; FRED's DFII30 is the same series, used if the Treasury does not answer |
| stock volatility | Yahoo, daily **adjusted** closes | dividend and split adjusted, so total returns |
| expected stock return | Shiller: dividend yield plus 100-year real growth in earnings per share | Choi's own stated rationale, written as arithmetic |

The expected return is the number the answer is most sensitive to and the one
nobody can observe. Three further estimates are computed as cross-checks and
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
| Always 100% equities | 11.75% | 0.56% | 29.55% |

The tool elicits risk aversion with Choi's certainty-equivalent question, asked
as five quick choices with a final check, beside a 0 to 10 self-assessment,
rather than a questionnaire. The coin pays what the household lives on now or
half of it, the guide's own proportions. Risk aversion matters, but the
expected return matters more: the
answer to that question would have to be wrong by four points on a ten-point
scale to move the recommendation as far as the choice between expected-return
estimators does (section 3.1 of the methodology).

These costs are measured inside the ranges Choi solved his model over. Today's
inputs sit outside two of them: the 30-year real rate is above his 0% to 2%,
and the excess drift below his 2% to 4%. Section 3.6 of the methodology has the
detail, and the answer should be read as indicative until the approximation
is checked there.

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
| 7. Validated against ten published forecasts, and swept for properties | **done** |
| 8. Italian variant: global equity, euro real safe rate, Italian tax and pension | **done** |
| 9. Weekly refresh and publication, unattended | **done** |
| 10. Portfolio analytics and factor exposure | planned |

What is known to be missing is listed, with the reason for each, in
[docs/further-work.html](https://alessandrosimoncelli.github.io/your-equity-share/further-work.html).

### The published site

The site is built from this repository by GitHub Actions, on every push to
`main` and every Monday after the refresh, and served by GitHub Pages at
**[alessandrosimoncelli.github.io/your-equity-share](https://alessandrosimoncelli.github.io/your-equity-share/)**.
Nothing is published unless the tests, the check of the JavaScript against the
Python and the verifier have all passed first.

`python tools/build_web.py` writes the same thing locally to `web/`: the tool,
its model and its market data, about 75 KB, plus the three documents, about
300 KB in all. The Italian page in `web/it/` is not a second copy of the tool.
The build writes it from `src/web/index.html`, swapping the page's VARIANT
block (currency, number format, calibration, tax) for the Italian one and
translating the words with `src/web/it/translation.toml`. Every English
fragment the table translates must still be on the page, exactly once, or the
build stops, so a fix to the page reaches both versions and no edit to the
English can leave the Italian page half translated. It opens in well under a second and needs no backend, so nothing
a visitor enters is transmitted anywhere. Every link in it is relative, and a
test holds it so, because the site lives in a subfolder of the domain rather
than at its root.

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

Then open http://localhost:8600. A self-assessment, five quick choices and a
check set your risk aversion, and a slider for the expected return shows by
dragging how much the answer depends on it. The
recommendation with its working, a sensitivity curve, the answer at every level
of savings, and a box for typing your earnings year by year.

The same folder is what GitHub Pages serves. The build also packs it as
`your-equity-share-site.zip`, for any other static host that takes an upload.

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

The Italian variant runs the same way. Its answer is after Italian tax unless
you ask for the figures before it:

```python
from your_equity_share import ITALY_CALIBRATION

italy = load_market_data("variants/it/market_data.toml")  # apply_tax=False: before tax
result = recommend(
    Household(500_000, [Person(45, 100_000)], risk_aversion=5),
    italy.expected_stock_real_return,
    italy.real_risk_free_rate,
    italy.stock_volatility,
    ITALY_CALIBRATION,
)
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

## Licence

MIT, in [LICENSE](LICENSE). The model is the work of Choi, Liu and Liu (2025)
and, behind it, Cocco, Gomes and Maenhout (2005); this licence covers the
implementation and grants no rights in their papers.

## Sources

- Merton, R. C. (1969). Lifetime Portfolio Selection under Uncertainty. *Review of Economics and Statistics*, 51(3).
- Bodie, Z., Merton, R. C. and Samuelson, W. F. (1992). Labor Supply Flexibility and Portfolio Choice in a Life Cycle Model. *JEDC*, 16.
- Cocco, J. F., Gomes, F. J. and Maenhout, P. J. (2005). Consumption and Portfolio Choice over the Life Cycle. *RFS*, 18(2).
- Choi, J. J., Liu, C. and Liu, P. (2025). Practical Finance: An Approximate Solution to Lifecycle Portfolio Choice.

## Disclaimer

Educational and illustrative only. Not investment, financial, tax or legal
advice, and no advisory relationship is created by its use. Outputs depend
entirely on the assumptions documented in `variants/us/methodology.html` and
`variants/it/methodology.html`.
