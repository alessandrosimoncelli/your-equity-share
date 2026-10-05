/**
 * The equity allocation model, ported from Python.
 *
 * Python is the reference implementation. It is what the 215 tests exercise and
 * what was validated against Choi's own spreadsheet. This file exists only
 * because a browser cannot run it fast enough: a Python interpreter compiled to
 * WebAssembly took about thirty seconds to start, and this takes none.
 *
 * The two are bound together by tests/golden.json, produced by the Python and
 * replayed through this file by tools/check_golden.mjs. Change one side without
 * the other and that check fails. Do not "improve" the arithmetic here: if a
 * formula is wrong it is wrong in src/your_equity_share/ first, and the fixture
 * is regenerated from there.
 *
 * Only the model is ported. Fetching market data, parsing providers and
 * estimating volatility and the expected return stay in Python, because they
 * run on the author's machine and not the reader's.
 *
 * No dependencies, no imports, no build step.
 */

// --- calibration ------------------------------------------------------------

/**
 * Values fixed inside the fitted approximation. Not user inputs. The earnings
 * defaults are Cocco, Gomes and Maenhout's estimates for the average American
 * college graduate; the 18.5% volatility and the 40% replacement rate are Choi,
 * Liu and Liu's, and the cap is this project's.
 */
export const CGM_CALIBRATION = Object.freeze({
  stockVolatility: 0.185,
  permanentShockVolatility: 0.13,
  temporaryShockVolatility: 0.242,
  // One quantity, used twice: it sets the retirement benefit as a share
  // of the final wage, and it is a regressor in the wage discount rate
  // (the paper's Table 1; equation (12) of the methodology). A second copy
  // called wageEquityBeta described a labour income to equity beta. The
  // paper has no such regressor: its beta belongs to the extension of its
  // section 5, equation (19), which neither the spreadsheet nor this model
  // uses, and its Table 1 row is the replacement rate.
  benefitReplacementRate: 0.4,
  // The earnings profile: age, age squared and age cubed in log earnings.
  ageProfile: Object.freeze([0.3194, -0.00577, 0.000033]),
  // Social Security's largest benefit at full retirement age in 2026, $4,152
  // a month, after tax at 0.8, the factor the guide uses for pre-tax
  // retirement money. Applied to the imputed pension
  // only; human_capital.py says why.
  benefitCap: 0.8 * 4152.0 * 12,
});

/**
 * An Italian private-sector employee, as human_capital.py documents: the
 * earnings process Daminato and Padula (2024) estimate on the Bank of Italy's
 * household survey, and the Italian Treasury's 66% pension, restated on the
 * wage-plus-TFR the page asks for: 0.66 / 1.075 = 0.614.
 */
export const ITALY_CALIBRATION = Object.freeze({
  stockVolatility: 0.185,
  permanentShockVolatility: Math.sqrt(0.015156),
  temporaryShockVolatility: Math.sqrt(0.023609),
  benefitReplacementRate: 0.614,
  ageProfile: Object.freeze([-0.001022, 0.000613, -0.000006]),
  benefitCap: null,
});

const FINAL_AGE = 100;
// Wages stop at this age: the last year worked is 66.
const RETIREMENT_AGE = 67;

// The gamble used in the user guide.
export const GUIDE_GAMBLE_HIGH = 100000.0;
export const GUIDE_GAMBLE_LOW = 50000.0;

// The log excess drifts Choi's approximation was fitted over. Outside this the
// fitted coefficients are an extrapolation with no standing.
export const CHOI_FITTED_LOG_PREMIUM_RANGE = Object.freeze([0.02, 0.04]);

// The other half of the same grid: log real risk-free rates of 0, 0.01 and
// 0.02. Choi's guide suggests the 30-year TIPS yield as a reasonable number
// to enter, which is above all three. The regressor carries +1.132 against -0.267 on the premium.
export const CHOI_FITTED_LOG_RISK_FREE_RANGE = Object.freeze([0.0, 0.02]);

// And the third axis. The paper solves at 4, 5, 6, 7, 8, 9 and 10; the guide
// offers a table from 1 to 10. Below 4 is extrapolation, on the benign side.
export const CHOI_FITTED_RISK_AVERSION_RANGE = Object.freeze([4, 10]);

/** Volatility baked into the fitted coefficients. */
export const CALIBRATION_VOLATILITY = 0.185;

/**
 * Python's math.isclose. Note the default relative tolerance of 1e-9 is doing
 * the work here, not the absolute one: near gamma = 1 the threshold is about
 * 1e-9, not 1e-12. Getting this wrong would move where the logarithmic branch
 * is taken.
 */
function isClose(a, b, relTol = 1e-9, absTol = 0.0) {
  if (a === b) return true;
  return Math.abs(a - b) <= Math.max(relTol * Math.max(Math.abs(a), Math.abs(b)), absTol);
}

// --- layer one: the Merton share --------------------------------------------

/**
 * Equity share of TOTAL wealth. Merton (1969).
 *
 *     w* = [ln(1+mu) - ln(1+r)] / (gamma * sigma^2)
 *
 * The numerator is a difference of drifts, not of quoted returns. This is the
 * answer for someone with no future earnings, which almost nobody is, and that
 * is what layer two corrects.
 */
export function mertonShare(expectedStockRealReturn, realRiskFree, riskAversion, stockVolatility) {
  if (stockVolatility <= 0) throw new RangeError("stock volatility must be positive");
  if (riskAversion <= 0) throw new RangeError("risk aversion must be positive");
  if (expectedStockRealReturn <= -1 || realRiskFree <= -1) {
    throw new RangeError("returns below -100% are not meaningful");
  }
  const numerator = Math.log(1.0 + expectedStockRealReturn) - Math.log(1.0 + realRiskFree);
  return numerator / (riskAversion * stockVolatility ** 2);
}

// --- layer two: human capital -----------------------------------------------

/**
 * The regressor Choi calls the log equity premium (r minus r_f in the paper,
 * pi in the methodology): the log risk premium of the risky asset.
 *
 * The arithmetic mean was converted from a compound return at the held
 * asset's volatility, so it is undone at that same volatility, which recovers
 * ln(1 + compound) - ln(1 + safe rate). At Choi's 18.5% the two readings are
 * the same number. See _log_excess_drift in human_capital.py.
 */
function logExcessDrift(expectedStockRealReturn, realRiskFree, calibration, volatility = null) {
  const sigma = volatility == null ? calibration.stockVolatility : volatility;
  return (
    Math.log(1.0 + expectedStockRealReturn) -
    0.5 * sigma ** 2 -
    Math.log(1.0 + realRiskFree)
  );
}

/**
 * One-year-ahead discount rate applied to a wage received at `age`.
 *
 * Far above the risk-free rate, and not because wages track the market: for the
 * average household that correlation is about 0.007. The premium is the price
 * of a claim that cannot be diversified, sold, or borrowed against.
 */
export function wageDiscountRate(
  age,
  riskAversion,
  expectedStockRealReturn,
  realRiskFree,
  calibration = CGM_CALIBRATION,
  volatility = null,
) {
  const x = (age - 1) / 100.0;
  const pi = logExcessDrift(expectedStockRealReturn, realRiskFree, calibration, volatility);
  return (
    -0.02 +
    0.087 * (riskAversion / 10.0) -
    0.267 * pi +
    1.132 * Math.log(1.0 + realRiskFree) +
    4.332 * calibration.permanentShockVolatility ** 2 +
    0.028 * calibration.temporaryShockVolatility ** 2 +
    0.01 * calibration.benefitReplacementRate -
    0.149 * x +
    0.142 * x ** 2
  );
}

/**
 * One-year-ahead discount rate applied to a retirement benefit at `age`.
 *
 * Much lower than the wage rate, because Social Security is an inflation-indexed
 * claim on the federal government. The loading on risk aversion is 0.0003
 * against 0.087 for wages: a cautious household marks down a risky salary
 * sharply and a government annuity not at all.
 */
export function benefitDiscountRate(
  age,
  riskAversion,
  expectedStockRealReturn,
  realRiskFree,
  calibration = CGM_CALIBRATION,
  volatility = null,
) {
  const x = (age - 1) / 100.0;
  const pi = logExcessDrift(expectedStockRealReturn, realRiskFree, calibration, volatility);
  const rate =
    -0.166 +
    0.0003 * (riskAversion / 10.0) -
    0.217 * pi +
    0.893 * Math.log(1.0 + realRiskFree) +
    0.476 * x -
    0.295 * x ** 2;
  // Floored at the safe rate. Choi fits this on retirement years only (his
  // Table 2: rates at 66 to 99, applied to income received at 67 to 100),
  // and at 30 it returns -2.7%, which values a future payment above
  // its face amount. A government indexed annuity cannot be worth more than a
  // risk-free bond paying the same schedule. See benefit_discount_rate in
  // human_capital.py for the measurement.
  return Math.max(rate, realRiskFree);
}

/**
 * Expected wage at `age`, projected from one salary today.
 *
 * The cubic in age is the calibration's earnings profile. Cocco, Gomes and
 * Maenhout's for an American graduate rises steeply through the thirties,
 * peaks in the mid forties and then falls; the Italian one keeps rising,
 * slowly, to retirement.
 *
 * The leading term is a statistical correction rather than a feature of
 * careers. Wage shocks are multiplicative, so projected wages are lognormal,
 * and a lognormal's mean sits above its median by half its variance. Adding
 * that half variance turns the typical path into the expected path, which is
 * what a present value needs.
 */
export function imputedWage(age, currentAge, currentWage, calibration = CGM_CALIBRATION) {
  if (age >= RETIREMENT_AGE) return 0.0;
  const elapsed = age - currentAge;
  const [linear, square, cube] = calibration.ageProfile;
  return (
    currentWage *
    Math.exp(
      0.5 *
        (elapsed * calibration.permanentShockVolatility ** 2 +
          calibration.temporaryShockVolatility ** 2) +
        linear * elapsed +
        square * (age ** 2 - currentAge ** 2) +
        cube * (age ** 3 - currentAge ** 3),
    )
  );
}

/**
 * One adult. `currentBenefit` is a pension whose amount is already fixed,
 * paid now or from `benefitStart`; `benefitIsState` says it is the person's
 * state pension, which then replaces the imputed one; `claimsSpousal` marks
 * a second adult who claims half of the first adult's Social Security.
 * See Person in human_capital.py.
 */
export function makePerson(currentAge, currentWage, currentBenefit = 0.0, wages = null,
                           benefits = null,
                           { benefitStart = null, benefitIsState = false, claimsSpousal = false } = {}) {
  if (!(currentAge >= 20 && currentAge <= 99)) {
    throw new RangeError(
      `current age ${currentAge} is outside the 20 to 99 range Choi's guide accepts`,
    );
  }
  if (currentWage < 0 || currentBenefit < 0) {
    throw new RangeError("wages and benefits cannot be negative");
  }
  if (benefitStart != null && benefitStart > FINAL_AGE) {
    throw new RangeError(`a pension starting at ${benefitStart} is never paid`);
  }
  return { currentAge, currentWage, currentBenefit, wages, benefits,
           benefitStart, benefitIsState, claimsSpousal };
}

/** The pension in `currentBenefit` paid at `age`: zero before it starts. */
export function pensionPaid(person, age) {
  return age >= pensionStart(person) ? person.currentBenefit : 0.0;
}

function pensionStart(person) {
  return person.benefitStart == null
    ? person.currentAge + 1 : Math.max(person.currentAge + 1, person.benefitStart);
}

/**
 * Riskless: already being paid, or not the state pension (a fixed pension from
 * an earlier job). A state pension that starts later is an estimate the rest
 * of the career can still move, as in human_capital.py.
 */
export function pensionIsCertain(person) {
  return !person.benefitIsState || pensionStart(person) <= person.currentAge + 1;
}

/**
 * Wages and benefits for every year from next year to age 100.
 *
 * Uses whatever the person supplied year by year and imputes the rest. The
 * pension in `currentBenefit` is paid every year from its start. The
 * retirement benefit for the person's own career is a fixed share of the wage
 * in the last year of work, paid from the year after it, on top of that
 * pension unless it is the state one; a break typed before work ends pays
 * none of it. See project_earnings in human_capital.py.
 */
export function projectEarnings(person, calibration = CGM_CALIBRATION) {
  const ages = [];
  for (let age = person.currentAge + 1; age <= FINAL_AGE; age += 1) ages.push(age);
  const wages = {};
  let lastWork = null;
  for (const age of ages) {
    wages[age] = person.wages != null && Object.prototype.hasOwnProperty.call(person.wages, age)
      ? person.wages[age]
      : imputedWage(age, person.currentAge, person.currentWage, calibration);
    if (wages[age] > 0) lastWork = age;
  }

  // Fixed once, off the wage in the last year of work, as in human_capital.py:
  // today's wage when none is left to project, none for a retiree, none when
  // the pension typed is the state one or the person claims the spousal one.
  let careerBenefit = 0.0;
  if (!(person.benefitIsState || person.claimsSpousal)) {
    const base = lastWork !== null ? wages[lastWork] : person.currentWage;
    careerBenefit = base * calibration.benefitReplacementRate;
    if (calibration.benefitCap != null) {
      careerBenefit = Math.min(careerBenefit, calibration.benefitCap);
    }
  }

  const years = [];
  for (const age of ages) {
    const paid = pensionPaid(person, age);
    let benefit;
    if (person.benefits != null && Object.prototype.hasOwnProperty.call(person.benefits, age)) {
      benefit = person.benefits[age];
    } else if (lastWork !== null && age <= lastWork) {
      benefit = paid;
    } else {
      benefit = paid + careerBenefit;
    }
    years.push({ age, wage: wages[age], benefit });
  }
  return years;
}

/**
 * Present value today of one person's future wages and benefits.
 *
 * One discount path, as in Choi's paper: the wage rate through the last year
 * with wages, the benefit rate after it. His spreadsheet switches in every
 * year a benefit is entered instead, which gives the same path when the
 * benefit starts the year after the last wage. A pension already being paid while the
 * person still works is riskless, so it is divided by the benefit rates from
 * today instead. See human_capital in human_capital.py.
 */
export function humanCapital(
  person,
  riskAversion,
  expectedStockRealReturn,
  realRiskFree,
  calibration = CGM_CALIBRATION,
  volatility = null,
  spousalFromAge = null,
) {
  const years = projectEarnings(person, calibration);
  let lastWork = 0;
  for (const year of years) if (year.wage > 0) lastWork = year.age;
  let total = 0.0;
  let chain = 1.0;
  let safeChain = 1.0;
  for (const year of years) {
    const benefitRate = benefitDiscountRate(
      year.age, riskAversion, expectedStockRealReturn, realRiskFree, calibration, volatility);
    const rate = year.age <= lastWork
      ? wageDiscountRate(year.age, riskAversion, expectedStockRealReturn, realRiskFree, calibration, volatility)
      : benefitRate;
    chain *= 1.0 + rate;
    safeChain *= 1.0 + benefitRate;
    // Typed or not, as in human_capital.py: the page passes its prefilled
    // path as typed once the year-by-year box is ticked.
    const paid = pensionIsCertain(person) ? pensionPaid(person, year.age) : 0.0;
    const pension = Math.min(paid, year.benefit);
    total += (year.wage + year.benefit - pension) / chain + pension / safeChain;
    if (spousalFromAge != null && year.age >= spousalFromAge) {
      const fixed = person.benefitIsState ? pension : 0.0;
      total += 0.5 * (year.benefit - pension) / chain + 0.5 * fixed / safeChain;
    }
  }
  return total;
}

// --- risk aversion ----------------------------------------------------------

/**
 * The guaranteed amount worth the same as a 50/50 gamble between `high` and
 * `low`, under constant relative risk aversion.
 *
 * Evaluated in logs. Written directly, high**(1-gamma) underflows to zero once
 * gamma passes about a hundred and the outer power then divides by zero.
 * Factoring out the larger term keeps every intermediate inside range, and the
 * result tends to the worse outcome as gamma grows, which is the right limit.
 */
export function certaintyEquivalent(gamma, high = GUIDE_GAMBLE_HIGH, low = GUIDE_GAMBLE_LOW) {
  if (high <= 0 || low <= 0) throw new RangeError("both outcomes must be positive");
  if (gamma < 0) throw new RangeError("risk aversion cannot be negative");

  if (isClose(gamma, 1.0, 1e-9, 1e-12)) return Math.sqrt(high * low);

  const power = 1.0 - gamma;
  const a = power * Math.log(high);
  const b = power * Math.log(low);
  const bigger = a > b ? a : b;
  const scaled = 0.5 * Math.exp(a - bigger) + 0.5 * Math.exp(b - bigger);
  return Math.exp((bigger + Math.log(scaled)) / power);
}

/**
 * Invert `certaintyEquivalent`: the risk aversion implied by answering
 * `amount`. The certainty equivalent falls monotonically in gamma, so a
 * bisection is reliable and needs no starting guess.
 */
export function gammaFromCertaintyEquivalent(
  amount,
  high = GUIDE_GAMBLE_HIGH,
  low = GUIDE_GAMBLE_LOW,
  tolerance = 1e-10,
) {
  const midpoint = 0.5 * (high + low);
  if (amount >= midpoint) {
    throw new RangeError(
      `an answer of ${amount} is at or above the average outcome of ${midpoint}, ` +
        `which means no aversion to the risk at all`,
    );
  }
  if (amount <= Math.min(high, low)) {
    throw new RangeError(
      `an answer of ${amount} is at or below the worst outcome of ${Math.min(high, low)}, ` +
        `which no risk aversion can justify`,
    );
  }

  let lower = 0.0;
  let upper = 1.0;
  while (certaintyEquivalent(upper, high, low) > amount) {
    upper *= 2.0;
    if (upper > 1e6) throw new RangeError("could not bracket a solution");
  }
  while (upper - lower > tolerance) {
    const middle = 0.5 * (lower + upper);
    if (certaintyEquivalent(middle, high, low) > amount) {
      lower = middle;
    } else {
      upper = middle;
    }
  }
  return 0.5 * (lower + upper);
}

/** The lookup table printed in the user guide, computed rather than copied. */
export function guideTable(high = GUIDE_GAMBLE_HIGH, low = GUIDE_GAMBLE_LOW) {
  const table = {};
  for (let g = 1; g <= 10; g += 1) table[g] = certaintyEquivalent(g, high, low);
  return table;
}

// --- the question as five choices -------------------------------------------
//
// The staircase of risk_aversion.py: five choices between the coin and a sure
// amount, each amount depending on the answer before, the coin paying what
// the household lives on now or half of it. Mirrors the Python function for
// function; tests/golden.json holds every path of answers at five incomes.

export const STAIRCASE_CHOICES = 5;
export const SMALLEST_COIN = 1000.0;

/**
 * The coin's good outcome: the household's after-tax income now, wages and
 * any pension already being received added up, as the Health and Retirement
 * Study frames its gamble on current total family income. Below
 * SMALLEST_COIN nothing is coming in, and the guide's own $100,000 is asked.
 */
export function coinIncome(wage, partnerWage = 0.0, pension = 0.0) {
  if (!(Math.min(wage, partnerWage, pension) >= 0)) {
    throw new RangeError("incomes cannot be negative");
  }
  const household = wage + partnerWage + pension;
  if (household < SMALLEST_COIN) return GUIDE_GAMBLE_HIGH;
  return Math.floor(household + 0.5);
}

/** Before any answer: the whole range the guide describes, 1 to 10. */
export function staircaseStart() {
  return Object.freeze({ low: 1.0, high: 10.0, answered: 0 });
}

export function staircaseDone(state) {
  return state.answered >= STAIRCASE_CHOICES;
}

/** The middle of the bracket in ratio terms: its geometric mean. */
export function staircaseEstimate(state) {
  return Math.sqrt(state.low * state.high);
}

/** What sure amounts are rounded to: $100 on an income in six figures. */
export function offerStep(income) {
  if (income < 1) throw new RangeError("the income behind the question must be at least 1");
  const digits = String(Math.trunc(income)).length;
  return Math.max(1.0, 10.0 ** (digits - 1) / 1000.0);
}

/** The sure amount to set against the coin next. */
export function staircaseOffer(state, income) {
  if (staircaseDone(state)) throw new RangeError("all the choices have been answered");
  const exact = certaintyEquivalent(staircaseEstimate(state), income, income / 2.0);
  const step = offerStep(income);
  return Math.floor(exact / step + 0.5) * step;
}

/**
 * Narrow the bracket by one answer. Taking the sure amount says the coin is
 * worth less than the offer, so risk aversion is at least the value at which
 * the offer is the coin's exact worth; choosing the coin says at most that.
 */
export function staircaseAnswer(state, income, offer, tookSure) {
  if (staircaseDone(state)) throw new RangeError("all the choices have been answered");
  let split = gammaFromCertaintyEquivalent(offer, income, income / 2.0);
  split = Math.min(Math.max(split, state.low), state.high);
  return Object.freeze(tookSure
    ? { low: split, high: state.high, answered: state.answered + 1 }
    : { low: state.low, high: split, answered: state.answered + 1 });
}

/**
 * True when the 0 to 10 self-assessment and the choices point opposite ways:
 * very willing yet cautious, or very unwilling yet relaxed. It never changes
 * gamma, because nothing converts one scale into the other.
 */
export function answersDisagree(willingness, gamma) {
  if (!(willingness >= 0 && willingness <= 10)) {
    throw new RangeError("willingness is on a scale from 0 to 10");
  }
  const willing = willingness >= 7;
  const unwilling = willingness <= 3;
  const cautious = gamma >= 7.0;
  const relaxed = gamma < 4.0;
  return (willing && cautious) || (unwilling && relaxed);
}

// --- the recommendation -----------------------------------------------------

/**
 * Everything the model needs about the people. Market inputs come separately.
 */
export function makeHousehold(investableNetWorth, adults, riskAversion = 5.0) {
  if (investableNetWorth <= 0) {
    throw new RangeError(
      "investable net worth must be positive: the recommendation is a share of it, " +
        "so there is nothing to allocate at zero",
    );
  }
  if (!adults || adults.length === 0) throw new RangeError("a household needs at least one adult");
  if (adults.length > 2) {
    throw new RangeError("Choi's spreadsheet takes households of one or two adults");
  }
  if (!(riskAversion >= 1.0 && riskAversion <= 10.0)) {
    throw new RangeError(
      `risk aversion ${riskAversion} is outside the 1 to 10 scale Choi's guide ` +
        `uses. His model was solved over 4 to 10; below 4 is accepted here ` +
        `because it is the side where the answer saturates at 100%.`,
    );
  }
  return { investableNetWorth, adults, riskAversion };
}

/**
 * Run both layers and return the recommendation with its working.
 *
 *     w_fin = clip( beta * (1 + HC/W), 0, 1 )
 *
 * The clip is the no-borrowing and no-short-selling constraint of the model
 * the formula approximates, which Choi's equation (9) carries. The formula
 * alone does not respect it, so the uncapped figure is reported alongside.
 *
 * `stockVolatility` is the volatility of the asset held, a fixed long-run
 * figure. It sets the Merton term and also turns the arithmetic return back
 * into the log risk premium the discount rates take, so both layers read one
 * asset. See recommend in allocation.py.
 */
export function recommend(
  household,
  expectedStockRealReturn,
  realRiskFree,
  stockVolatility,
  calibration = CGM_CALIBRATION,
) {
  const beta = mertonShare(
    expectedStockRealReturn,
    realRiskFree,
    household.riskAversion,
    stockVolatility,
  );

  // Choi's spousal switch, as in allocation.py.
  let spousalFrom = null;
  if (household.adults.length === 2 && household.adults[1].claimsSpousal) {
    const [earner, partner] = household.adults;
    spousalFrom = earner.currentAge + Math.max(1, 62 - partner.currentAge);
  }
  const perAdult = household.adults.map((adult, i) =>
    humanCapital(adult, household.riskAversion, expectedStockRealReturn, realRiskFree, calibration,
                 stockVolatility, i === 0 ? spousalFrom : null),
  );
  // Summed in the same order as Python's sum() over the tuple, because floating
  // point addition is not associative and the fixture pins the result.
  let totalHc = 0.0;
  for (const value of perAdult) totalHc += value;

  const uncapped = beta * (1.0 + totalHc / household.investableNetWorth);
  const equityShare = Math.max(0.0, Math.min(1.0, uncapped));

  return {
    equityShare,
    mertonShare: beta,
    humanCapital: totalHc,
    financialWealth: household.investableNetWorth,
    uncappedShare: uncapped,
    perAdultHumanCapital: perAdult,
    // HC/W. This, not age, is what drives the recommendation.
    humanCapitalRatio: totalHc / household.investableNetWorth,
    // True when the model wanted leverage and the constraint bound.
    isCapped: uncapped > 1.0,
    bondShare: 1.0 - equityShare,
    equityDollars: equityShare * household.investableNetWorth,
  };
}

// --- reporting helpers the page needs ---------------------------------------

/**
 * Convert a compound (geometric) return into an arithmetic mean.
 *
 * Ported from arithmetic_from_compound in expected_return.py. Every
 * forward-looking estimate of equity returns is naturally compound: a
 * discounted cash flow gives an internal rate of return, Gordon's formula
 * gives a discount rate. Choi's input slot is arithmetic, which is visible in
 * his own regressor subtracting sigma^2/2.
 */
export function arithmeticFromCompound(compound, volatility) {
  return Math.exp(Math.log(1.0 + compound) + 0.5 * volatility ** 2) - 1.0;
}

/** The inverse. What the page shows a reader, since it is what others quote. */
export function compoundFromArithmetic(arithmetic, volatility) {
  return Math.exp(Math.log(1.0 + arithmetic) - 0.5 * volatility ** 2) - 1.0;
}

/** The quantity Choi's grid is expressed in, and his regressions consume. */
export function logPremium(expectedRealReturn, realRiskFree, volatility = CALIBRATION_VOLATILITY) {
  return Math.log(1.0 + expectedRealReturn) - 0.5 * volatility ** 2 - Math.log(1.0 + realRiskFree);
}

/** The safe rate as Choi's regressions take it, which is in logs. */
export function logRiskFree(realRiskFree) {
  return Math.log(1.0 + realRiskFree);
}

/** Whether the safe rate sits inside the grid the coefficients were fitted on. */
export function withinFittedRiskFree(realRiskFree) {
  const [low, high] = CHOI_FITTED_LOG_RISK_FREE_RANGE;
  const r = logRiskFree(realRiskFree);
  return low <= r && r <= high;
}

export function withinFittedRange(expectedRealReturn, realRiskFree, volatility = CALIBRATION_VOLATILITY) {
  const [low, high] = CHOI_FITTED_LOG_PREMIUM_RANGE;
  const pi = logPremium(expectedRealReturn, realRiskFree, volatility);
  return low <= pi && pi <= high;
}
