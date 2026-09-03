"""Streamlit front end for the equity allocation tool.

    streamlit run app.py

Market data comes from config/market_data.toml. Refresh it with
`python update.py`; this page reports its age and never fetches anything itself.
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from merton_share.allocation import Household, recommend  # noqa: E402
from merton_share.expected_return import (  # noqa: E402
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    log_premium,
)
from merton_share.human_capital import Person  # noqa: E402
from merton_share.market_data import load_market_data  # noqa: E402
from merton_share.risk_aversion import (  # noqa: E402
    certainty_equivalent,
    gamma_from_certainty_equivalent,
)

NAVY = "#1F3864"
GREEN = "#375623"
RULE = "#A6A6A6"

st.set_page_config(page_title="The Merton Share", layout="wide")

st.markdown(
    f"""
    <style>
      html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li {{
          font-family: Aptos, Calibri, "Segoe UI", Arial, Helvetica, sans-serif;
          color: #000000;
      }}
      .block-container {{ padding-top: 2.4rem; max-width: 62rem; }}
      h1 {{ font-size: 1.6rem !important; font-weight: 700; color: {NAVY};
            margin-bottom: 0.2rem; }}
      h2 {{ font-size: 1.1rem !important; font-weight: 700; color: {NAVY};
            margin-top: 2.2rem; margin-bottom: 0.5rem; }}
      h3 {{ font-size: 0.98rem !important; font-weight: 700; color: #000000;
            margin-top: 1.4rem; }}
      hr {{ border: 0; border-top: 1.5px solid {NAVY}; margin: 0.6rem 0 1.6rem; }}
      table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
      th {{ text-align: left; font-weight: 700; color: {NAVY};
            border-bottom: 1px solid {NAVY}; padding: 0.4rem 0.9rem 0.4rem 0; }}
      td {{ padding: 0.42rem 0.9rem 0.42rem 0;
            border-bottom: 1px solid #DCDCDC; vertical-align: top; }}
      td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums;
                    padding-right: 0; }}
      .headline {{ font-size: 2.4rem; font-weight: 700; color: {NAVY};
                   line-height: 1.1; }}
      .sub {{ font-size: 0.95rem; color: #000000; }}
      .note {{ font-size: 0.85rem; color: #000000; border-top: 1px solid {RULE};
               padding-top: 0.8rem; margin-top: 2.4rem; }}
      .warn {{ font-size: 0.88rem; color: #000000; border-left: 3px solid {GREEN};
               padding: 0.1rem 0 0.1rem 0.9rem; margin: 0.9rem 0; }}
      section[data-testid="stSidebar"] {{ background: #F7F7F7; }}
      section[data-testid="stSidebar"] .block-container {{ padding-top: 1.4rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)


def money(x: float) -> str:
    return f"${x:,.0f}"


@st.cache_data(show_spinner=False)
def _market():
    return load_market_data()


try:
    market = _market()
except FileNotFoundError as exc:
    st.error(f"{exc}")
    st.stop()


# --- inputs ----------------------------------------------------------------

with st.sidebar:
    st.markdown("### Your household")
    age = st.number_input("Age", min_value=20, max_value=99, value=45, step=1)
    wage = st.number_input(
        "Current after-tax annual wage", min_value=0, value=100_000, step=5_000,
        help="After tax and in today's money. Include an employer pension match, "
             "reduced by about 20% if it goes in before tax.",
    )
    wealth = st.number_input(
        "Investable net worth", min_value=1_000, value=500_000, step=10_000,
        help="Non-housing assets less non-mortgage debt, reduced for tax owed "
             "on withdrawal. Housing is excluded entirely.",
    )
    benefit = st.number_input(
        "Retirement benefit already received", min_value=0, value=0, step=1_000,
        help="Leave at zero if you are still working.",
    )

    partnered = st.checkbox("Second adult in the household")
    partner_age = partner_wage = None
    if partnered:
        partner_age = st.number_input(
            "Their age", min_value=20, max_value=99, value=42, step=1
        )
        partner_wage = st.number_input(
            "Their after-tax annual wage", min_value=0, value=80_000, step=5_000
        )

    st.markdown("### Risk aversion")
    st.markdown(
        '<div class="sub">A coin is flipped. Heads, you live on $100,000 for the '
        "next year. Tails, $50,000. You must spend it all and cannot borrow. "
        "What guaranteed amount would leave you exactly indifferent?</div>",
        unsafe_allow_html=True,
    )
    answer = st.slider(
        "Guaranteed amount", min_value=54_000, max_value=70_000,
        value=58_566, step=100, format="$%d", label_visibility="collapsed",
    )
    gamma = gamma_from_certainty_equivalent(float(answer))
    st.markdown(
        f'<div class="sub">Implied risk aversion <b>{gamma:.1f}</b>. '
        "A lower amount means you dislike risk more.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### Market assumptions")
    override = st.checkbox("Override the expected return")
    expected = market.expected_stock_real_return
    if override:
        expected = st.slider(
            "Expected real return on equities, arithmetic",
            min_value=0.02, max_value=0.10,
            value=float(market.expected_stock_real_return),
            step=0.0005, format="%.2f%%",
        )


# --- the recommendation -----------------------------------------------------

adults = [Person(int(age), float(wage), float(benefit))]
if partnered and partner_age is not None:
    adults.append(Person(int(partner_age), float(partner_wage or 0.0)))

household = Household(float(wealth), adults, gamma)
result = recommend(
    household, expected, market.real_risk_free_rate, market.stock_volatility
)

st.markdown("# The Merton Share")
st.markdown(
    '<div class="sub">How much of your portfolio belongs in equities. '
    "Merton (1969), with the human capital adjustment of Choi, Liu and Liu "
    "(2025).</div>",
    unsafe_allow_html=True,
)
st.markdown("<hr>", unsafe_allow_html=True)

left, right = st.columns([1, 1.35], gap="large")

with left:
    st.markdown(
        f'<div class="headline">{result.equity_share:.0%}</div>'
        f'<div class="sub">in equities, which is '
        f"{money(result.equity_dollars())} of {money(result.financial_wealth)}."
        f"{'' if result.bond_share < 0.005 else f' The remaining {result.bond_share:.0%} goes in the safe asset.'}"
        "</div>",
        unsafe_allow_html=True,
    )
    if result.is_capped:
        st.markdown(
            '<div class="warn">The model asks for '
            f"{result.uncapped_share:.0%}, meaning it would borrow to invest. "
            "The cap at 100% is imposed from outside; the model did not "
            "produce it.</div>",
            unsafe_allow_html=True,
        )

with right:
    total = result.financial_wealth + result.human_capital
    rows = [
        ("Investable today", money(result.financial_wealth),
         f"{result.financial_wealth / total:.0%}"),
        ("Future earnings", money(result.human_capital),
         f"{result.human_capital / total:.0%}"),
        ("Total wealth", money(total), ""),
    ]
    body = "".join(
        f"<tr><td>{a}</td><td class='n'>{b}</td><td class='n'>{c}</td></tr>"
        for a, b, c in rows
    )
    st.markdown(
        "<table><thead><tr><th>Where your wealth is</th>"
        "<th class='n'>Amount</th><th class='n'>Share</th></tr></thead>"
        f"<tbody>{body}</tbody></table>",
        unsafe_allow_html=True,
    )

st.markdown("## How this was reached")

steps = [
    ("Equity share of <b>total</b> wealth", f"{result.merton_share:.1%}",
     "Merton (1969), the reward for risk divided by risk and your dislike of it"),
    (f"Multiplied by 1 + {result.human_capital_ratio:.2f}",
     f"{result.uncapped_share:.1%}",
     "your future earnings cannot be traded, so the tradeable part carries the "
     "whole equity position"),
]
if result.is_capped:
    steps.append(("Capped, no leverage", f"{result.equity_share:.1%}",
                  "a constraint imposed from outside the model"))
body = "".join(
    f"<tr><td>{a}</td><td class='n'>{b}</td><td>{c}</td></tr>" for a, b, c in steps
)
st.markdown(
    "<table><thead><tr><th>Step</th><th class='n'>Result</th>"
    f"<th>Why</th></tr></thead><tbody>{body}</tbody></table>",
    unsafe_allow_html=True,
)


# --- sensitivity ------------------------------------------------------------

st.markdown("## What the answer depends on")
st.markdown(
    '<div class="sub">The expected return is the least certain input and the '
    "one the answer moves most with. The three estimators behind it currently "
    "span nearly two percentage points.</div>",
    unsafe_allow_html=True,
)

grid = []
for mu in [x / 1000 for x in range(20, 101, 2)]:
    if mu <= market.real_risk_free_rate:
        continue
    grid.append(
        {
            "Expected real return": mu,
            "Equity share": recommend(
                household, mu, market.real_risk_free_rate, market.stock_volatility
            ).equity_share,
        }
    )
sens = pd.DataFrame(grid)

base = alt.Chart(sens).mark_line(color=NAVY, strokeWidth=2).encode(
    x=alt.X("Expected real return:Q", axis=alt.Axis(format="%", title="Expected real return on equities", grid=False)),
    y=alt.Y("Equity share:Q", axis=alt.Axis(format="%", title="Recommended equity share", grid=True), scale=alt.Scale(domain=[0, 1])),
)
marker = alt.Chart(pd.DataFrame({"x": [expected]})).mark_rule(
    color=GREEN, strokeDash=[4, 3]
).encode(x="x:Q")
st.altair_chart(
    (base + marker).properties(height=260).configure_view(strokeWidth=0)
    .configure_axis(labelFontSize=12, titleFontSize=12, labelColor='#000000',
                    titleColor='#000000', domainColor=RULE, tickColor=RULE,
                    labelFont='Calibri, Arial, sans-serif',
                    titleFont='Calibri, Arial, sans-serif'),
    use_container_width=True,
)
st.markdown(
    f'<div class="sub">The dashed line is the figure in use, '
    f"{expected:.2%}.</div>",
    unsafe_allow_html=True,
)


# --- glide path -------------------------------------------------------------

st.markdown("## Across a lifetime")
path = []
for a in range(max(20, 25), 96):
    try:
        trial = Household(
            float(wealth),
            [Person(a, float(wage), float(benefit))],
            gamma,
        )
    except ValueError:
        continue
    r = recommend(trial, expected, market.real_risk_free_rate, market.stock_volatility)
    path.append({"Age": a, "Equity share": r.equity_share,
                 "Human capital": r.human_capital})
glide = pd.DataFrame(path)

st.altair_chart(
    alt.Chart(glide).mark_line(color=NAVY, strokeWidth=2).encode(
        x=alt.X("Age:Q", axis=alt.Axis(title="Age", grid=False)),
        y=alt.Y("Equity share:Q", axis=alt.Axis(format="%", title="Equity share"),
                scale=alt.Scale(domain=[0, 1])),
    ).properties(height=240).configure_view(strokeWidth=0)
    .configure_axis(labelFontSize=12, titleFontSize=12, labelColor='#000000',
                    titleColor='#000000', domainColor=RULE, tickColor=RULE,
                    labelFont='Calibri, Arial, sans-serif',
                    titleFont='Calibri, Arial, sans-serif'),
    use_container_width=True,
)
st.markdown(
    '<div class="sub">Wealth and salary are held fixed here, which no real saver '
    "does, so read this as the effect of age alone. What moves the share is "
    "future earnings shrinking against savings, not the horizon shortening.</div>",
    unsafe_allow_html=True,
)


# --- market data ------------------------------------------------------------

st.markdown("## Market data")

pi = log_premium(expected, market.real_risk_free_rate)
low, high = CHOI_FITTED_LOG_PREMIUM_RANGE
method = market.provenance.get("expected_return_method", "set by hand")
label = {"consensus": "median of three estimators", "implied": "market implied",
         "fixed": "set by hand"}.get(method, method)

rows = [
    ("Expected real return on equities", f"{expected:.2%}",
     "overridden by hand" if override else label),
    ("Real risk-free rate", f"{market.real_risk_free_rate:.2%}",
     "30-year TIPS yield, FRED"),
    ("Stock volatility", f"{market.stock_volatility:.2%}",
     f"{market.market_ticker}, "
     f"{market.provenance.get('volatility_window_years', '?')} years of adjusted closes"),
    ("Risk aversion", f"{gamma:.1f}", "your answer to the coin question"),
    ("Log excess drift", f"{pi:.2%}",
     f"inside Choi's {low:.0%} to {high:.0%} fitted band"
     if low <= pi <= high
     else f"{(low - pi if pi < low else pi - high):.2%} outside that band"),
]
body = "".join(
    f"<tr><td>{a}</td><td class='n'>{b}</td><td>{c}</td></tr>" for a, b, c in rows
)
st.markdown(
    "<table><thead><tr><th>Input</th><th class='n'>Value</th>"
    f"<th>Source</th></tr></thead><tbody>{body}</tbody></table>",
    unsafe_allow_html=True,
)

if market.expected_return_estimates:
    st.markdown(
        f'<div class="sub">Estimators: {market.expected_return_estimates}. '
        f"They span {market.expected_return_spread:.2%}.</div>",
        unsafe_allow_html=True,
    )

if not low <= pi <= high:
    st.markdown(
        '<div class="warn">The log excess drift sits outside the band Choi '
        "fitted his approximation over. Above the band is benign, since "
        "allocations saturate at 100%. Below it the coefficients are an "
        "extrapolation, which today's high real rates make likely. Read the "
        "answer as indicative.</div>",
        unsafe_allow_html=True,
    )

age_days = (datetime.now(timezone.utc).date() - market.as_of).days
day_word = "day" if age_days == 1 else "days"
st.markdown(
    f'<div class="sub">Data as of {market.as_of}, {age_days} {day_word} old. '
    "Refresh with <code>python update.py</code>.</div>",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="note">Educational and illustrative only. Not investment, '
    "financial, tax or legal advice, and no advisory relationship is created "
    "by its use. Every output depends on the assumptions documented in "
    "docs/methodology.html, several of which are estimates that competent "
    "practitioners would set differently.</div>",
    unsafe_allow_html=True,
)
