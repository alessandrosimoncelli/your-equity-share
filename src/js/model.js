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
 * Only the model is ported. Fetching market data, parsing providers, estimating
 * volatility and the expected return, and the frozen spreadsheet baseline all
 * stay in Python, because they run on the author's machine and not the reader's.
 *
 * No dependencies, no imports, no build step.
 */

// --- calibration ------------------------------------------------------------

/**
 * Values fixed inside the fitted approximation. Not user inputs. They come from
 * the Cocco, Gomes and Maenhout calibration to United States household
 * earnings, for the average college graduate.
 */
export const CGM_CALIBRATION = Object.freeze({
  stockVolatility: 0.185,
  permanentShockVolatility: 0.13,
  temporaryShockVolatility: 0.242,
  wageEquityBeta: 0.4,
  benefitReplacementRate: 0.4,
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
// 0.02. Choi's guide tells a reader to enter the 30-year TIPS yield, which is
// above all three. The regressor carries +1.132 against -0.267 on the premium.
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
 * The regressor Choi writes as pi: the log excess drift of equities.
 *
 * Uses the calibration's 18.5% volatility, not the user's. The coefficients
 * were fitted with that value in place and have no standing away from it.
 */
function logExcessDrift(expectedStockRealReturn, realRiskFree, calibration) {
  return (
    Math.log(1.0 + expectedStockRealReturn) -
    0.5 * calibration.stockVolatility ** 2 -
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
) {
  const x = (age - 1) / 100.0;
  const pi = logExcessDrift(expectedStockRealReturn, realRiskFree, calibration);
  return (
    -0.02 +
    0.087 * (riskAversion / 10.0) -
    0.267 * pi +
    1.132 * Math.log(1.0 + realRiskFree) +
    4.332 * calibration.permanentShockVolatility ** 2 +
    0.028 * calibration.temporaryShockVolatility ** 2 +
    0.01 * calibration.wageEquityBeta -
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
) {
  const x = (age - 1) / 100.0;
  const pi = logExcessDrift(expectedStockRealReturn, realRiskFree, calibration);
  return (
    -0.166 +
    0.0003 * (riskAversion / 10.0) -
    0.217 * pi +
    0.893 * Math.log(1.0 + realRiskFree) +
    0.476 * x -
    0.295 * x ** 2
  );
}

/**
 * Expected wage at `age`, projected from one salary today.
 *
 * The cubic in age is the Cocco, Gomes and Maenhout earnings profile: rising
 * steeply through the thirties, peaking near fifty, then flattening.
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
  return (
    currentWage *
    Math.exp(
      0.5 *
        (elapsed * calibration.permanentShockVolatility ** 2 +
          calibration.temporaryShockVolatility ** 2) +
        0.3194 * elapsed -
        0.00577 * (age ** 2 - currentAge ** 2) +
        0.000033 * (age ** 3 - currentAge ** 3),
    )
  );
}

/**
 * One adult in the household. `currentBenefit` covers someone already drawing a
 * retirement income; leave it at zero for anyone still working and the benefit
 * is imputed from the final wage instead.
 */
export function makePerson(currentAge, currentWage, currentBenefit = 0.0, wages = null, benefits = null) {
  if (!(currentAge >= 20 && currentAge <= 99)) {
    throw new RangeError(
      `current age ${currentAge} is outside the 20 to 99 range the approximation was fitted over`,
    );
  }
  if (currentWage < 0 || currentBenefit < 0) {
    throw new RangeError("wages and benefits cannot be negative");
  }
  return { currentAge, currentWage, currentBenefit, wages, benefits };
}

/**
 * Wages and benefits for every year from next year to age 100.
 *
 * Uses whatever the person supplied year by year and imputes the rest. The
 * benefit, where not given, is a fixed share of the final wage earned, paid from
 * the first year without wages onward.
 */
export function projectEarnings(person, calibration = CGM_CALIBRATION) {
  const years = [];
  let finalWage = 0.0;
  let runningBenefit = person.currentBenefit;

  for (let age = person.currentAge + 1; age <= FINAL_AGE; age += 1) {
    let wage;
    if (person.wages != null && Object.prototype.hasOwnProperty.call(person.wages, age)) {
      wage = person.wages[age];
    } else {
      wage = imputedWage(age, person.currentAge, person.currentWage, calibration);
    }

    let benefit;
    if (person.benefits != null && Object.prototype.hasOwnProperty.call(person.benefits, age)) {
      benefit = person.benefits[age];
    } else if (person.currentBenefit > 0) {
      benefit = person.currentBenefit;
    } else if (wage > 0) {
      benefit = 0.0;
    } else {
      // First year without wages: fix the benefit off the last wage earned,
      // then hold it for life.
      if (runningBenefit === 0.0) {
        const base = finalWage > 0 ? finalWage : person.currentWage;
        runningBenefit = base * calibration.benefitReplacementRate;
      }
      benefit = runningBenefit;
    }

    if (wage > 0) finalWage = wage;
    years.push({ age, wage, benefit });
  }
  return years;
}

/**
 * Present value today of one person's future wages and benefits.
 *
 * One discount path, switching from the wage rate to the benefit rate in the
 * first year a benefit is drawn, and both income types divided by the same
 * running product.
 */
export function humanCapital(
  person,
  riskAversion,
  expectedStockRealReturn,
  realRiskFree,
  calibration = CGM_CALIBRATION,
) {
  let total = 0.0;
  let cumulative = 1.0;
  for (const year of projectEarnings(person, calibration)) {
    const rate =
      year.benefit > 0
        ? benefitDiscountRate(year.age, riskAversion, expectedStockRealReturn, realRiskFree, calibration)
        : wageDiscountRate(year.age, riskAversion, expectedStockRealReturn, realRiskFree, calibration);
    cumulative *= 1.0 + rate;
    total += (year.wage + year.benefit) / cumulative;
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
    throw new RangeError("the approximation was fitted for households of one or two adults");
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
 * The clip is a no-leverage, no-shorting constraint imposed from outside. It is
 * not a result of the model, so the uncapped figure is reported alongside.
 *
 * `stockVolatility` is the volatility of the portfolio actually held, used in
 * the Merton term. The discount rates inside layer two keep the calibration's
 * 18.5% regardless, because their coefficients were fitted with that in place.
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

  const perAdult = household.adults.map((adult) =>
    humanCapital(adult, household.riskAversion, expectedStockRealReturn, realRiskFree, calibration),
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
