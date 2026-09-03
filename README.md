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

## Before you use it, refresh the data

```bash
python update.py
```

That is the whole thing. It fetches the latest market data, saves it, and tells
you what changed. Windows users can double-click `update.bat` instead.

```
Updating market data for Your Equity Share
==============================================================

Fetching...
  real risk-free rate (30y TIPS)     2.98%   was  2.50%   +0.48 points
  stock volatility (SPY, 5y)        17.22%   was 18.50%   -1.28 points

Not fetched, this one is your judgement:
  expected stock real return         5.00%   set 93 days ago
  edit it in market_data.toml if your view has changed

Saved. Market data is now current to 2026-09-01.
```

**All three** numbers the model uses are fetched, from three free sources that
need no key or account:

| Input | Source | Note |
| --- | --- | --- |
| real risk-free rate | FRED, 30-year TIPS yield | a real yield already, no inflation adjustment |
| stock volatility | Yahoo, daily **adjusted** closes | dividend and split adjusted, so total returns |
| expected stock return | Damodaran implied ERP + the real rate | forward looking, published monthly |

Override the expected return with `--fixed-return 0.05` if you prefer your own
view. See [docs/inputs.md](docs/inputs.md) for the caveat on combining a
10-year-based premium with a 30-year real yield.

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
| 5. Streamlit front end | **done** |
| 6. Portfolio analytics and factor exposure | planned |

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

Then ask it the question. There are two front ends.

**In the browser:**

```bash
pip install -e ".[app]"
streamlit run app.py
```

Sliders for risk aversion and the expected return, so you can see by dragging
how much the answer depends on each. The recommendation, its working, a
sensitivity curve and a glide path across ages.

**In the terminal:**

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
