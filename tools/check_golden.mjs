/**
 * Replay the Python's answers through the JavaScript port.
 *
 *     node tools/check_golden.mjs
 *
 * Regenerate the fixture first with `python tools/make_golden.py` whenever the
 * Python model changes. This is the only thing standing between two
 * implementations of the same arithmetic and silent divergence.
 *
 * On tolerance. Exact equality is the wrong bar and would fail for a correct
 * port: log and exp are not required to be correctly rounded, and CPython uses
 * the platform's libm while V8 ships its own. A one-ulp difference in log,
 * compounded through eighty years of discounting, lands around 1e-14 relative.
 * The bar here is 1e-9 relative, which is far tighter than anything
 * economically meaningful and far looser than libm noise. The worst deviation
 * actually observed is printed, so a real drift shows as a jump in that number
 * long before it trips the threshold.
 */

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

import {
  certaintyEquivalent,
  gammaFromCertaintyEquivalent,
  benefitDiscountRate,
  humanCapital,
  imputedWage,
  makeHousehold,
  makePerson,
  mertonShare,
  projectEarnings,
  recommend,
  wageDiscountRate,
} from "../src/js/model.js";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const TOLERANCE = 1e-9;

const fixture = JSON.parse(readFileSync(join(ROOT, "tests", "golden.json"), "utf8"));

let checks = 0;
let worst = 0;
let worstWhere = "nothing compared yet";
const failures = [];

function compare(where, got, want) {
  checks += 1;
  if (typeof want === "boolean" || typeof got === "boolean") {
    if (got !== want) failures.push(`${where}: got ${got}, expected ${want}`);
    return;
  }
  if (!Number.isFinite(got)) {
    failures.push(`${where}: got ${got}, expected ${want}`);
    return;
  }
  const scale = Math.max(Math.abs(want), 1e-12);
  const relative = Math.abs(got - want) / scale;
  if (relative > worst) {
    worst = relative;
    worstWhere = where;
  }
  if (relative > TOLERANCE) {
    failures.push(`${where}: got ${got}, expected ${want}, relative ${relative.toExponential(3)}`);
  }
}

function person(payload) {
  return makePerson(payload.current_age, payload.current_wage, payload.current_benefit);
}

const cases = fixture.cases;

// --- the calibration must agree before anything else is meaningful ----------
{
  const c = fixture.calibration;
  compare("calibration.stock_volatility", 0.185, c.stock_volatility);
  compare("calibration.permanent_shock_volatility", 0.13, c.permanent_shock_volatility);
  compare("calibration.temporary_shock_volatility", 0.242, c.temporary_shock_volatility);
  compare("calibration.wage_equity_beta", 0.4, c.wage_equity_beta);
  compare("calibration.benefit_replacement_rate", 0.4, c.benefit_replacement_rate);
}

for (const [i, c] of cases.merton_share.entries()) {
  const [mu, rf, gamma, sigma] = c.args;
  compare(`merton_share[${i}]`, mertonShare(mu, rf, gamma, sigma), c.expect);
}

for (const [i, c] of cases.wage_discount_rate.entries()) {
  const [age, gamma, mu, rf] = c.args;
  compare(`wage_discount_rate[${i}]`, wageDiscountRate(age, gamma, mu, rf), c.expect);
}

for (const [i, c] of cases.benefit_discount_rate.entries()) {
  const [age, gamma, mu, rf] = c.args;
  compare(`benefit_discount_rate[${i}]`, benefitDiscountRate(age, gamma, mu, rf), c.expect);
}

for (const [i, c] of cases.imputed_wage.entries()) {
  const [age, currentAge, currentWage] = c.args;
  compare(`imputed_wage[${i}]`, imputedWage(age, currentAge, currentWage), c.expect);
}

for (const [i, c] of cases.certainty_equivalent.entries()) {
  compare(`certainty_equivalent[${i}]`, certaintyEquivalent(c.args[0]), c.expect);
}

for (const [i, c] of cases.gamma_from_certainty_equivalent.entries()) {
  compare(`gamma_from_certainty_equivalent[${i}]`, gammaFromCertaintyEquivalent(c.args[0]), c.expect);
}

for (const [i, c] of cases.project_earnings.entries()) {
  const years = projectEarnings(person(c.person));
  if (years.length !== c.expect.length) {
    failures.push(`project_earnings[${i}]: ${years.length} years, expected ${c.expect.length}`);
    continue;
  }
  for (let y = 0; y < years.length; y += 1) {
    compare(`project_earnings[${i}].year[${y}].age`, years[y].age, c.expect[y].age);
    compare(`project_earnings[${i}].year[${y}].wage`, years[y].wage, c.expect[y].wage);
    compare(`project_earnings[${i}].year[${y}].benefit`, years[y].benefit, c.expect[y].benefit);
  }
}

for (const [i, c] of cases.human_capital.entries()) {
  const [gamma, mu, rf] = c.args;
  compare(`human_capital[${i}]`, humanCapital(person(c.person), gamma, mu, rf), c.expect);
}

for (const [i, c] of cases.recommend.entries()) {
  const [mu, rf, sigma] = c.args;
  const household = makeHousehold(
    c.household.investable_net_worth,
    c.household.adults.map(person),
    c.household.risk_aversion,
  );
  const got = recommend(household, mu, rf, sigma);
  const want = c.expect;
  compare(`recommend[${i}].equity_share`, got.equityShare, want.equity_share);
  compare(`recommend[${i}].merton_share`, got.mertonShare, want.merton_share);
  compare(`recommend[${i}].human_capital`, got.humanCapital, want.human_capital);
  compare(`recommend[${i}].financial_wealth`, got.financialWealth, want.financial_wealth);
  compare(`recommend[${i}].uncapped_share`, got.uncappedShare, want.uncapped_share);
  compare(`recommend[${i}].human_capital_ratio`, got.humanCapitalRatio, want.human_capital_ratio);
  compare(`recommend[${i}].is_capped`, got.isCapped, want.is_capped);
  compare(`recommend[${i}].bond_share`, got.bondShare, want.bond_share);
  compare(`recommend[${i}].equity_dollars`, got.equityDollars, want.equity_dollars);
  for (let a = 0; a < want.per_adult_human_capital.length; a += 1) {
    compare(
      `recommend[${i}].per_adult_human_capital[${a}]`,
      got.perAdultHumanCapital[a],
      want.per_adult_human_capital[a],
    );
  }
}

// --- inputs the port must refuse --------------------------------------------
// A port that silently returns a number for these is wrong in a way no numeric
// comparison would catch.
for (const [i, c] of cases.must_reject.entries()) {
  let threw = false;
  try {
    if (c.fn === "merton_share") {
      mertonShare(...c.args);
    } else if (c.fn === "household") {
      const [wealth, age, wage, gamma] = c.args;
      makeHousehold(wealth, [makePerson(age, wage)], gamma);
    } else if (c.fn === "person") {
      makePerson(...c.args);
    } else if (c.fn === "gamma_from_certainty_equivalent") {
      gammaFromCertaintyEquivalent(...c.args);
    } else {
      failures.push(`must_reject[${i}]: unknown function ${c.fn}`);
      continue;
    }
  } catch {
    threw = true;
  }
  checks += 1;
  if (!threw) {
    failures.push(`must_reject[${i}]: ${c.fn}(${c.args.join(", ")}) returned instead of throwing`);
  }
}

// --- report -----------------------------------------------------------------

const counts = Object.entries(cases).map(([name, rows]) => `${rows.length} ${name}`);
console.log(`fixture generated ${fixture.generated_at}`);
console.log(`  ${counts.join(", ")}`);
console.log(`  ${checks.toLocaleString("en-US")} values compared`);
console.log(`  worst relative deviation ${worst.toExponential(3)} at ${worstWhere}`);
console.log(`  tolerance ${TOLERANCE.toExponential(0)}`);

if (failures.length > 0) {
  console.error(`\nFAILED: ${failures.length} mismatch(es)\n`);
  for (const line of failures.slice(0, 25)) console.error(`  ${line}`);
  if (failures.length > 25) console.error(`  ... and ${failures.length - 25} more`);
  process.exit(1);
}

console.log("\nThe JavaScript port reproduces the Python.");
