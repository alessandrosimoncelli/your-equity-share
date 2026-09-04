"""Streamlit front end for the equity allocation tool.

    streamlit run app.py

Market data comes from config/market_data.toml. Refresh it with
`python update.py`; this page reports its age and never fetches anything itself.

On the visual design. Navy is structure, blue is data: headings and rules wear
the document's navy ink, and every mark that encodes a number wears #2a78d6,
which passes the lightness, chroma, contrast and colour-vision checks that the
navy does not. A heading colour is not a chart colour.

The equity share is one number, so it gets a meter rather than a chart. Both
segments are labelled directly, so the split never depends on colour alone.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

# Pyodide reports this platform. The browser build is the same file running
# in WebAssembly, so the only thing that differs is what a visitor can be
# told to do: they have no terminal and no copy of the repository.
IN_BROWSER = sys.platform == "emscripten"

from your_equity_share.allocation import Household, recommend  # noqa: E402
from your_equity_share.expected_return import (  # noqa: E402
    CHOI_FITTED_LOG_PREMIUM_RANGE,
    log_premium,
)
from your_equity_share.human_capital import Person  # noqa: E402
from your_equity_share.market_data import load_market_data  # noqa: E402
from your_equity_share.risk_aversion import gamma_from_certainty_equivalent  # noqa: E402

# Structure
NAVY = "#1F3864"
INK = "#0B0B0B"
INK_2 = "#52514E"
RULE = "#C3C2B7"
HAIRLINE = "#E1E0D9"
# Data. Validated: lightness band, chroma floor, contrast, colour-vision.
BLUE = "#2A78D6"
BLUE_FILL = "#CDE2FB"
TRACK = "#E7E6DF"
GOOD = "#006300"
WARN = "#8A6314"

st.set_page_config(page_title="Your Equity Share", layout="wide")

st.markdown(
    f"""
    <style>
      html, body, [class*="css"], .stMarkdown, .stMarkdown p, .stMarkdown li {{
          font-family: Aptos, Calibri, "Segoe UI", Arial, Helvetica, sans-serif;
          color: {INK};
          font-size: 16px;
      }}
      .block-container {{ padding-top: 2.2rem; max-width: 68rem; }}
      h1 {{ font-size: 2.1rem !important; font-weight: 700; color: {NAVY};
            margin-bottom: 0.3rem; letter-spacing: -0.01em; }}
      h2 {{ font-size: 1.3rem !important; font-weight: 700; color: {NAVY};
            margin-top: 2.6rem; margin-bottom: 0.6rem;
            border-bottom: 1px solid {HAIRLINE}; padding-bottom: 0.35rem; }}
      hr {{ border: 0; border-top: 2px solid {NAVY}; margin: 0.7rem 0 1.8rem; }}

      table {{ border-collapse: collapse; width: 100%; font-size: 1rem; }}
      th {{ text-align: left; font-weight: 700; color: {NAVY}; font-size: 0.92rem;
            letter-spacing: 0.02em; text-transform: uppercase;
            border-bottom: 1.5px solid {NAVY}; padding: 0.5rem 1rem 0.5rem 0; }}
      td {{ padding: 0.62rem 1rem 0.62rem 0; border-bottom: 1px solid {HAIRLINE};
            vertical-align: top; }}
      td.n, th.n {{ text-align: right; font-variant-numeric: tabular-nums;
                    padding-right: 0; white-space: nowrap; }}
      td.k {{ white-space: nowrap; }}
      td.why {{ color: {INK_2}; font-size: 0.95rem; }}

      .headline {{ font-size: 4.2rem; font-weight: 700; color: {BLUE};
                   line-height: 1; letter-spacing: -0.02em; }}
      .headline-sub {{ font-size: 1.05rem; margin-top: 0.3rem; }}
      .lede {{ font-size: 1.05rem; color: {INK_2}; }}
      .sub {{ font-size: 0.95rem; color: {INK_2}; }}
      .note {{ font-size: 0.88rem; color: {INK_2};
               border-top: 1px solid {RULE}; padding-top: 0.9rem;
               margin-top: 2.6rem; }}
      .flag {{ font-size: 0.95rem; border-left: 4px solid {WARN};
               background: #FBF7EE; padding: 0.7rem 0.9rem; margin: 1rem 0; }}
      .ok {{ font-size: 0.95rem; border-left: 4px solid {GOOD};
             background: #F1F7F1; padding: 0.7rem 0.9rem; margin: 1rem 0; }}

      .meter {{ display: flex; width: 100%; height: 2.6rem; margin: 0.9rem 0 0.4rem;
                gap: 2px; }}
      .meter div {{ display: flex; align-items: center; padding: 0 0.7rem;
                    font-size: 0.95rem; font-weight: 700; white-space: nowrap;
                    overflow: hidden; }}
      .meter .eq {{ background: {BLUE}; color: #FFFFFF; }}
      .meter .sf {{ background: {TRACK}; color: {INK}; }}

      section[data-testid="stSidebar"] {{ background: #F7F7F5;
                                          border-right: 1px solid {HAIRLINE}; }}
      section[data-testid="stSidebar"] * {{ font-size: 15px; }}
      section[data-testid="stSidebar"] h3 {{ font-size: 1.02rem !important;
            font-weight: 700; color: {NAVY}; margin-top: 1.5rem;
            border-bottom: 1px solid {HAIRLINE}; padding-bottom: 0.3rem; }}
    </style>
    """,
    unsafe_allow_html=True,
)

AXIS = dict(labelFontSize=13, titleFontSize=13, labelColor=INK_2,
            titleColor=INK_2, domainColor=RULE, tickColor=RULE,
            labelFont="Calibri, Arial, sans-serif",
            titleFont="Calibri, Arial, sans-serif", labelPadding=6)


def money(x: float) -> str:
    return f"${x:,.0f}"


def table(header: list[str], rows: list[tuple], classes: list[str]) -> str:
    head = "".join(
        f"<th class='{c if c=='n' else ''}'>{h}</th>" for h, c in zip(header, classes)
    )
    body = "".join(
        "<tr>" + "".join(f"<td class='{c}'>{v}</td>" for v, c in zip(r, classes))
        + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


@st.cache_data(show_spinner=False)
def _market():
    return load_market_data()


try:
    market = _market()
except FileNotFoundError as exc:
    st.error(str(exc))
    st.stop()


# --- inputs -----------------------------------------------------------------

with st.sidebar:
    st.markdown("### Your household")
    age = st.number_input("Age", 20, 99, 45, 1)
    wage = st.number_input(
        "After-tax annual wage", 0, value=100_000, step=5_000,
        help="After tax and in today's money. Include an employer pension "
             "match, reduced by about 20% if it goes in before tax.",
    )
    wealth = st.number_input(
        "Investable net worth", 1_000, value=500_000, step=10_000,
        help="Non-housing assets less non-mortgage debt, reduced for tax owed "
             "on withdrawal. Housing is excluded entirely.",
    )
    benefit = st.number_input(
        "Pension already received", 0, value=0, step=1_000,
        help="Leave at zero if you are still working.",
    )

    partnered = st.checkbox("Second adult in the household")
    partner_age = partner_wage = None
    if partnered:
        partner_age = st.number_input("Their age", 20, 99, 42, 1)
        partner_wage = st.number_input(
            "Their after-tax wage", 0, value=80_000, step=5_000
        )

    st.markdown("### How much you dislike risk")
    st.markdown(
        '<div class="sub">A coin is flipped. Heads, you live on $100,000 for '
        "the next year. Tails, $50,000. You must spend it all and cannot "
        "borrow.<br><br><b>What guaranteed amount would leave you exactly "
        "indifferent?</b></div>",
        unsafe_allow_html=True,
    )
    answer = st.slider(
        # The ends are the guide's own answers for risk aversion 10 and 1,
        # so the whole stated scale is reachable. Step 1 keeps 58,566, the
        # anchor for 5, on the grid; at step 100 it was not, and the first
        # drag snapped the answer off it.
        "Guaranteed amount", 53_991, 70_711, 58_566, 1,
        format="$%d", label_visibility="collapsed",
    )
    gamma = gamma_from_certainty_equivalent(float(answer))
    st.markdown(
        f'<div class="sub">Risk aversion <b style="color:{BLUE};font-size:1.15rem">'
        f"{gamma:.1f}</b> out of 10. A lower amount means you dislike risk "
        "more.</div>",
        unsafe_allow_html=True,
    )

    st.markdown("### Market assumptions")
    override = st.checkbox("Set the expected return myself")
    expected = market.expected_stock_real_return
    if override:
        expected = st.slider(
            "Expected real return on equities", 0.02, 0.10,
            float(market.expected_stock_real_return), 0.0005, format="%.2f%%",
        )


# --- model ------------------------------------------------------------------

adults = [Person(int(age), float(wage), float(benefit))]
if partnered and partner_age is not None:
    adults.append(Person(int(partner_age), float(partner_wage or 0.0)))

household = Household(float(wealth), adults, gamma)
result = recommend(
    household, expected, market.real_risk_free_rate, market.stock_volatility
)

st.markdown("# Your Equity Share")
st.markdown(
    '<div class="lede">How much of your portfolio belongs in equities. '
    "Merton (1969), with the human capital adjustment of Choi, Liu and Liu "
    "(2025).</div>",
    unsafe_allow_html=True,
)
st.markdown("<hr>", unsafe_allow_html=True)

left, right = st.columns([1, 1.25], gap="large")

with left:
    st.markdown(
        f'<div class="headline">{result.equity_share:.0%}</div>'
        f'<div class="headline-sub">of your portfolio in equities, which is '
        f"<b>{money(result.equity_dollars())}</b> of "
        f"{money(result.financial_wealth)}.</div>",
        unsafe_allow_html=True,
    )
    eq = max(result.equity_share, 0.0001)
    sf = max(result.bond_share, 0.0)
    segments = f'<div class="eq" style="flex:{eq}">Equities {eq:.0%}</div>'
    if sf > 0.02:
        segments += f'<div class="sf" style="flex:{sf}">Safe asset {sf:.0%}</div>'
    st.markdown(f'<div class="meter">{segments}</div>', unsafe_allow_html=True)

    if result.is_capped:
        st.markdown(
            f'<div class="flag">The model asks for '
            f"<b>{result.uncapped_share:.0%}</b>, meaning it would borrow to "
            "invest. The cap at 100% is imposed from outside; the model did "
            "not produce it.</div>",
            unsafe_allow_html=True,
        )

with right:
    total = result.financial_wealth + result.human_capital
    st.markdown(
        table(
            ["Where your wealth is", "Amount", "Share"],
            [
                ("Investable today", money(result.financial_wealth),
                 f"{result.financial_wealth / total:.0%}"),
                ("Future earnings", money(result.human_capital),
                 f"{result.human_capital / total:.0%}"),
                ("<b>Total wealth</b>", f"<b>{money(total)}</b>", ""),
            ],
            ["k", "n", "n"],
        ),
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="sub">Most of what you own is not in the account. That is '
        "the whole reason the answer is not simply the Merton share.</div>",
        unsafe_allow_html=True,
    )

st.markdown("## How this was reached")

steps = [
    ("Equity share of <b>total</b> wealth", f"{result.merton_share:.1%}",
     "Merton (1969): the reward for risk, divided by risk and by your dislike "
     "of it"),
    (f"Times 1 + {result.human_capital_ratio:.2f}", f"{result.uncapped_share:.1%}",
     "future earnings cannot be traded, so the tradeable part has to carry the "
     "whole equity position"),
]
if result.is_capped:
    steps.append(("Capped at 100%", f"{result.equity_share:.1%}",
                  "no leverage, a constraint imposed from outside the model"))
st.markdown(
    table(["Step", "Result", "Why"], steps, ["k", "n", "why"]),
    unsafe_allow_html=True,
)


# --- sensitivity ------------------------------------------------------------

st.markdown("## What the answer depends on")
st.markdown(
    '<div class="lede">The expected return is the least certain input and the '
    "one the answer moves most with. Drag the slider in the sidebar and watch "
    "this line.</div>",
    unsafe_allow_html=True,
)

grid = [
    {"mu": mu,
     "share": recommend(household, mu, market.real_risk_free_rate,
                        market.stock_volatility).equity_share}
    for mu in [x / 1000 for x in range(20, 101, 1)]
    if mu > market.real_risk_free_rate
]
sens = pd.DataFrame(grid)

area = alt.Chart(sens).mark_area(color=BLUE_FILL, opacity=0.55).encode(
    x=alt.X("mu:Q", axis=alt.Axis(format="%", title="Expected real return on equities",
                                  grid=False, tickCount=8)),
    y=alt.Y("share:Q", axis=alt.Axis(format="%", title=None,
                                     gridColor=HAIRLINE, tickCount=5),
            scale=alt.Scale(domain=[0, 1])),
)
line = area.mark_line(color=BLUE, strokeWidth=2.5)
here = alt.Chart(pd.DataFrame({"mu": [expected]})).mark_rule(
    color=NAVY, strokeWidth=1.5, strokeDash=[5, 4]
).encode(x="mu:Q")
dot = alt.Chart(
    pd.DataFrame({"mu": [expected], "share": [result.equity_share]})
).mark_point(color=NAVY, size=110, filled=True).encode(x="mu:Q", y="share:Q")

st.altair_chart(
    (area + line + here + dot).properties(height=300, padding={"left": 4, "right": 12, "top": 8, "bottom": 4})
    .configure_view(strokeWidth=0).configure_axis(**AXIS),
    width="stretch",
)
st.markdown(
    f'<div class="sub">The marker is where you are now: {expected:.2%} '
    f"expected return gives {result.equity_share:.0%} in equities.</div>",
    unsafe_allow_html=True,
)


# --- glide path -------------------------------------------------------------

st.markdown("## Across a lifetime")
path = []
for a in range(25, 96):
    trial = Household(float(wealth),
                      [Person(a, float(wage), float(benefit))], gamma)
    r = recommend(trial, expected, market.real_risk_free_rate,
                  market.stock_volatility)
    path.append({"age": a, "share": r.equity_share})
glide = pd.DataFrame(path)

g_area = alt.Chart(glide).mark_area(color=BLUE_FILL, opacity=0.55).encode(
    x=alt.X("age:Q", axis=alt.Axis(title="Age", grid=False, tickCount=8),
            scale=alt.Scale(domain=[25, 95], nice=False)),
    y=alt.Y("share:Q", axis=alt.Axis(format="%", title=None,
                                     gridColor=HAIRLINE, tickCount=5),
            scale=alt.Scale(domain=[0, 1])),
)
you = alt.Chart(pd.DataFrame({"age": [int(age)]})).mark_rule(
    color=NAVY, strokeWidth=1.5, strokeDash=[5, 4]
).encode(x="age:Q")
st.altair_chart(
    (g_area + g_area.mark_line(color=BLUE, strokeWidth=2.5) + you)
    .properties(height=280, padding={"left": 4, "right": 12, "top": 8, "bottom": 4}).configure_view(strokeWidth=0).configure_axis(**AXIS),
    width="stretch",
)
st.markdown(
    '<div class="sub">Wealth and salary are held fixed here, which no real '
    "saver does, so read this as the effect of age alone. What moves the share "
    "is future earnings shrinking against savings, not the horizon "
    "shortening.</div>",
    unsafe_allow_html=True,
)


# --- market data ------------------------------------------------------------

st.markdown("## The numbers behind it")

pi = log_premium(expected, market.real_risk_free_rate)
low, high = CHOI_FITTED_LOG_PREMIUM_RANGE
inside = low <= pi <= high
method = market.provenance.get("expected_return_method", "set by hand")
label = {"building blocks": "payout yield plus long-run growth",
         "consensus": "median of three estimators", "implied": "market implied",
         "fixed": "set by hand"}.get(method, method)
window = market.provenance.get("volatility_window_years", "?")

st.markdown(
    table(
        ["Input", "Value", "Where it comes from"],
        [
            ("Expected real return on equities", f"{expected:.2%}",
             "you set this" if override else label),
            ("Real risk-free rate", f"{market.real_risk_free_rate:.2%}",
             "30-year TIPS yield, from FRED"),
            ("Stock volatility", f"{market.stock_volatility:.2%}",
             f"{market.market_ticker}, {window} years of dividend-adjusted closes"),
            ("Your risk aversion", f"{gamma:.1f}", "your answer to the coin question"),
            ("Log excess drift", f"{pi:.2%}",
             f"inside the {low:.0%} to {high:.0%} band Choi fitted"
             if inside else
             f"{(low - pi if pi < low else pi - high):.2%} outside that band"),
        ],
        ["k", "n", "why"],
    ),
    unsafe_allow_html=True,
)

if market.expected_return_estimates:
    st.markdown(
        f'<div class="sub">One estimator decides this: payout yield plus '
        f"long-run real earnings growth, which is Choi's own stated rationale "
        f"for his 5% default. The others are cross-checks, not used. "
        f"{market.expected_return_estimates}. They span "
        f"<b>{market.expected_return_spread:.2%}</b>, which is the honest "
        "measure of how little is known about this input.</div>",
        unsafe_allow_html=True,
    )

st.markdown(
    (f'<div class="ok">The log excess drift sits inside the band Choi fitted '
     "his approximation over, so the coefficients are being used as "
     "intended.</div>")
    if inside else
    (f'<div class="flag">The log excess drift sits <b>outside</b> the band '
     "Choi fitted his approximation over. Above the band is benign, since "
     "allocations saturate at 100%. Below it the coefficients are an "
     "extrapolation, which today's high real rates make likely. Read the "
     "answer as indicative.</div>"),
    unsafe_allow_html=True,
)

age_days = (datetime.now(timezone.utc).date() - market.as_of).days
st.markdown(
    f'<div class="sub">Data as of <b>{market.as_of}</b>, '
    f"{age_days} day{'' if age_days == 1 else 's'} old."
    + ("" if IN_BROWSER else " Refresh it by running <code>python update.py</code>.")
    + "</div>",
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="note">Educational and illustrative only. Not investment, '
    "financial, tax or legal advice, and no advisory relationship is created "
    "by its use. Every output depends on the assumptions documented in "
    + ('<a href="./methodology.html" target="_blank">the methodology</a>'
       if IN_BROWSER else "docs/methodology.html")
    + ", several of which are estimates that competent practitioners would "
    "set differently.</div>",
    unsafe_allow_html=True,
)
