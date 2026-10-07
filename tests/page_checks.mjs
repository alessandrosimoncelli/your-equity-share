// The page's own input logic, run in node on the built page.
//
//   node tests/page_checks.mjs web
//
// tests/test_page_logic.py runs this after a build. The model behind the page
// is held to the Python by check_golden.mjs; this holds the code around it:
// how the fields, the ticks and the year-by-year box become the households
// the model is given, and what the page shows when there is no answer. Each
// check here is a defect that once shipped or that a review reproduced.
//
// The DOM is a stub: every element with an id in the page becomes an object
// with the properties the script reads and writes, and the page's module
// script runs as written, with its last line, boot(), exposing the functions
// checked here.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

const WEB = path.resolve(process.argv[2] || "web");
let counter = 0;

class El {
  constructor(id, tag, attrs) {
    Object.assign(this, { id, tagName: tag, attrs, listeners: {}, dataset: {}, style: {} });
    this.value = attrs.value ?? "";
    this.checked = "checked" in attrs;
    this.hidden = "hidden" in attrs;
    this.disabled = "disabled" in attrs;
    this.innerHTML = this.textContent = "";
    this.clientWidth = 640;
    for (const [k, v] of Object.entries(attrs)) if (k.startsWith("data-")) this.dataset[k.slice(5)] = v;
  }
  addEventListener(ev, fn) { (this.listeners[ev] ||= []).push(fn); }
  fire(ev) { for (const fn of this.listeners[ev] || []) fn({ target: this, type: ev }); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  querySelector() { return new El(`anon${counter++}`, "g", {}); }
  getBoundingClientRect() { return { width: 640, height: 300, left: 0, top: 0 }; }
  focus() {}
}

function attributes(s) {
  const attrs = {};
  for (const m of s.matchAll(/([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'>]+)))?/g)) {
    attrs[m[1].toLowerCase()] = m[2] ?? m[3] ?? m[4] ?? "";
  }
  return attrs;
}

async function load(page) {
  const file = path.join(WEB, page);
  const html = fs.readFileSync(file, "utf8");
  const els = {};
  for (const m of html.matchAll(/<([a-zA-Z][a-zA-Z0-9]*)\s([^>]*?\bid="([^"]+)"[^>]*)>/g)) {
    els[m[3]] = new El(m[3], m[1].toLowerCase(), attributes(m[2]));
  }
  const many = (re, name) => [...html.matchAll(re)].map((m) => new El(`${name}${m[1]}`, "button", { [`data-${name}`]: m[1] }));
  const scale = many(/<button type="button" class="scale" data-w="(\d+)">/g, "w");
  const resets = many(/data-reset="(\d)"/g, "reset");
  const exhibits = new El("exhibits", "section", {});
  globalThis.document = {
    getElementById: (id) => { if (!els[id]) throw new Error(`no element #${id}`); return els[id]; },
    querySelector: (sel) => (sel === ".section-exhibits" ? exhibits : scale[0]),
    querySelectorAll: (sel) => (sel === "[data-reset]" ? resets : scale),
    addEventListener() {},
  };
  globalThis.window = { addEventListener() {} };
  globalThis.matchMedia = () => ({ matches: false, addEventListener() {} });
  globalThis.IntersectionObserver = class { observe() {} };
  globalThis.requestAnimationFrame = () => 0;
  globalThis.cancelAnimationFrame = () => {};
  const market = JSON.parse(fs.readFileSync(path.join(path.dirname(file), "market.json"), "utf8"));
  globalThis.fetch = async () => ({ ok: true, status: 200, json: async () => market });

  let code = html.match(/<script type="module">([\s\S]*?)<\/script>/)[1];
  code = code.replace(/from "(\.\.?\/model\.js)"/, (_, rel) =>
    `from "${pathToFileURL(path.resolve(path.dirname(file), rel)).href}"`);
  if (!/\nboot\(\);\s*$/.test(code)) throw new Error("the page no longer ends with boot()");
  code = code.replace(/\nboot\(\);\s*$/, "\nglobalThis.__page = { readInputs, render, pensionNow };\nawait boot();\n");
  const tmp = path.join(os.tmpdir(), `page_checks_${process.pid}_${counter++}.mjs`);
  fs.writeFileSync(tmp, code);
  try {
    await import(pathToFileURL(tmp).href);
  } finally {
    fs.unlinkSync(tmp);
  }
  return { page: globalThis.__page, els, market };
}

const type = (P, id, value) => { P.els[id].value = value; P.els[id].fire("input"); P.els[id].fire("blur"); };
const tick = (P, id, on) => { P.els[id].checked = on; P.els[id].fire("input"); P.els[id].fire("change"); };
const editBox = (P, which, f) => { const el = P.els[`path-${which}`]; el.value = f(el.value); el.fire("input"); };
const addToBenefits = (amount) => (text) => text.split("\n").map((line) => {
  const [age, wage, benefit] = line.trim().split(/\s{2,}/).map((s) => Number(s.replace(/[^0-9.]/g, "")));
  return `${age} ${wage} ${benefit + amount}`;
}).join("\n");
function answer(P) {
  const { household } = P.page.readInputs();
  P.page.render();
  return { figure: P.els["verdict-figure"].textContent, adults: household.adults };
}

let failed = 0;
function check(label, ok, detail = "") {
  if (!ok) failed += 1;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}${detail ? `   ${detail}` : ""}`);
}

// A pension from a later age stays fixed when the box is edited, even by a
// space that changes no number: the edit once made it ride the wage's chain.
{
  const P = await load("index.html");
  type(P, "benefit", "20000"); type(P, "benefit-start", "60");
  tick(P, "custom-path", true);
  const before = answer(P);
  editBox(P, 1, (v) => v + " ");
  const after = answer(P);
  check("an edit to the box keeps a later pension fixed",
        before.figure === after.figure && after.adults[0].benefitStart === 60 && P.els["benefit"].disabled,
        `${before.figure} then ${after.figure}`);
}

// A pension typed only in the box, from its first year, is one already paid,
// as it would be in the field.
{
  const P = await load("index.html");
  type(P, "benefit", "10000");
  const field = answer(P).figure;
  type(P, "benefit", "0");
  tick(P, "custom-path", true);
  editBox(P, 1, addToBenefits(10000));
  const box = answer(P);
  check("a pension typed in the box from its first year reads as in the field",
        box.figure === field && box.adults[0].currentBenefit === 10000, `${field} and ${box.figure}`);
}

// A Social Security tick with no amount would replace the imputed pension
// with nothing.
{
  const P = await load("index.html");
  const before = answer(P).figure;
  tick(P, "benefit-state", true);
  const after = answer(P);
  check("a tick with no amount changes nothing", before === after.figure && !after.adults[0].benefitIsState);
}

// The spousal benefit is instead of a pension of the partner's own: beside
// one, the tick is disabled and ignored, so nothing is counted twice.
{
  const P = await load("index.html");
  type(P, "age", "64");
  tick(P, "partnered", true); type(P, "partner-age", "63"); type(P, "partner-wage", "0");
  type(P, "partner-benefit", "15000"); tick(P, "partner-benefit-state", true);
  const own = answer(P).figure;
  tick(P, "partner-spousal", true);
  const both = answer(P);
  check("the spousal tick is ignored beside the partner's own pension",
        own === both.figure && !both.adults[1].claimsSpousal && P.els["partner-spousal"].disabled);
}

// No savings, or debts above them: no figure, no cap note and no bar, in
// every way a debt is typed.
for (const typed of ["0", "-50,000", "$-50,000", "(50,000)"]) {
  const P = await load("index.html");
  type(P, "wealth", typed);
  answer(P);
  check(`savings of ${typed} give no answer`,
        P.els["verdict-figure"].textContent === "" && P.els["cap-flag"].innerHTML === "" && P.els["split"].hidden);
}

// A minus sign means something on savings only.
{
  const P = await load("index.html");
  type(P, "benefit", "-20000");
  check("a minus sign on a pension is not kept", P.els["benefit"].value === "$20,000", P.els["benefit"].value);
}

// A pension from a later age is not in this year's income, which sets the
// size of the risk question's coin.
{
  const P = await load("index.html");
  type(P, "benefit", "20000");
  const now = P.page.pensionNow(1);
  type(P, "benefit-start", "60");
  check("a pension from a later age is not income today", now === 20000 && P.page.pensionNow(1) === 0);
}

// The world index row: the gross yield compounded with the growth term.
{
  const P = await load("index.html");
  answer(P);
  const g = P.market.global;
  const want = new Intl.NumberFormat("en-US", { style: "percent", minimumFractionDigits: 2, maximumFractionDigits: 2 })
    .format((1 + g.dividend_yield_gross) * (1 + g.real_growth) - 1);
  check("the world index row compounds the gross yield", P.els["inputs-rows"].innerHTML.includes(`>${want}<`), want);
}

// The Italian page runs the same code.
{
  const P = await load("it/index.html");
  type(P, "benefit", "10000"); type(P, "benefit-start", "60");
  tick(P, "custom-path", true);
  editBox(P, 1, (v) => v + " ");
  const r = answer(P);
  check("the Italian page keeps a later pension fixed too", r.adults[0].benefitStart === 60);
  type(P, "wealth", "-5.000");
  answer(P);
  check("the Italian page gives no answer for negative savings", P.els["verdict-figure"].textContent === "");
}

console.log(failed ? `${failed} failed` : "all passed");
process.exit(failed ? 1 : 0);
