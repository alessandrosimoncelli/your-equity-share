# merton-share

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

Full derivation, sourced coefficients and declared deviations:
[docs/methodology.html](docs/methodology.html).

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
reports a range across plausible values rather than a single figure.

## Status

Built in stages, so the effect of each correction is measured rather than
asserted.

| Stage | State |
| --- | --- |
| 1. Faithful port of the source spreadsheet, with regression baseline | **done** |
| 2. Covariance matrix in place of the weighted average of variances | next |
| 3. Log excess returns, gamma rescaled to 1 to 10, inflation as an input | planned |
| 4. Human capital layer: discount rates, imputed earnings path | planned |
| 5. Glide path output and sensitivity across gamma and mu | planned |
| 6. Streamlit front end | planned |

### Stage 1: the baseline

`merton_share.legacy` reproduces the "Merton Share" worksheet of
`QUANTO DEVO INVESTIRE IN AZIONI.xlsx` exactly, **defects included**. It exists
to be a fixed reference point, not to give advice.

The expected values are not transcribed. `tools/extract_baseline.py` reads them
straight out of the workbook into `tests/baseline_cells.json`, and the tests
compare against that file. A passing run is therefore evidence that the port
matches the spreadsheet, rather than evidence that the port and the test agree
with the same typo. Comparison is exact equality, not a tolerance: the port
applies the same operations in the same order as each worksheet formula, so the
results are bit-identical doubles.

Cell `G4`, the Merton share, reproduces as `0.8156054116198155`.

Four defects are reproduced deliberately and pinned by their own tests, so that
fixing each one produces a visible, measured change:

| Defect | Effect | Fixed in |
| --- | --- | --- |
| Denominator averages the sleeves' variances instead of using `w'Sigma w`, ignoring correlations | Overstates risk, so understates the allocation by about 9 points | Stage 2 |
| Numerator uses the arithmetic excess return rather than a difference of drifts | Overstates the numerator by 3.6% on these inputs | Stage 3 |
| Gamma is the mean of three scores on a 2 to 5 scale | The layer two discount-rate equations expect 1 to 10 | Stage 3 |
| Expected inflation hardcoded at 2.5% inside the real rate | Not a supplied assumption | Stage 3 |

The worksheet's `(125 - age - 500 * r)/100` rule is ported too, so the baseline
covers the sheet completely. It is not part of the recommendation.

## Use

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"
.venv/Scripts/python -m pytest
```

```python
from merton_share import LegacyInputs, merton_share

merton_share(LegacyInputs())                      # 0.8156054116198155
merton_share(LegacyInputs(risk_need=5.0))         # a more risk-averse household
```

To regenerate the baseline after the source workbook changes:

```bash
python tools/extract_baseline.py "path/to/QUANTO DEVO INVESTIRE IN AZIONI.xlsx"
```

## Sources

- Merton, R. C. (1969). Lifetime Portfolio Selection under Uncertainty. *Review of Economics and Statistics*, 51(3).
- Bodie, Z., Merton, R. C. and Samuelson, W. F. (1992). Labor Supply Flexibility and Portfolio Choice in a Life Cycle Model. *JEDC*, 16.
- Cocco, J. F., Gomes, F. J. and Maenhout, P. J. (2005). Consumption and Portfolio Choice over the Life Cycle. *RFS*, 18(2).
- Choi, J. J., Liu, C. and Liu, P. (2025). Practical Finance: An Approximate Solution to Lifecycle Portfolio Choice.

## Disclaimer

Educational and illustrative only. Not investment, financial, tax or legal
advice, and no advisory relationship is created by its use. Outputs depend
entirely on the assumptions documented in `docs/methodology.html`.

## Market data

The model reads `config/market_data.toml` and never touches the network, so a
demo cannot fail because a provider is slow or gone. Refreshing is a separate
program, run deliberately:

```bash
python tools/refresh_market_data.py            # dry run, shows what would change
python tools/refresh_market_data.py --write    # apply
```

It estimates volatilities and correlations from daily closes (Stooq) and reads
the nominal risk-free rate and expected inflation from FRED. Forward P/E ratios
are not published by any free source, so they are hand-entered, survive a
refresh untouched, and their age is reported instead. Every field in the file
records its own observation date for that reason.

The run aborts rather than writing a corrupted covariance matrix. Each series is
checked for length, non-positive prices, duplicate or unordered dates, and
single-day moves beyond 25%, which almost always mean an unadjusted split or a
currency change part-way through a series rather than a real market move.
`--force` overrides and says so.

The file shipped in this repository is a **seed**: volatilities and forward P/E
come from the source spreadsheet, and the correlation matrix is a flat 0.80
placeholder that has not been estimated. `observations = 0` records this, and
the loader reports it as stale. Run the refresh before drawing conclusions from
the covariance matrix.
