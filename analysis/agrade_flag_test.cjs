#!/usr/bin/env node
/*
 * Behavioural tests for the "This A followed a re-inspection" flag.
 *
 * The flag prints a rate measured on ONE population: A grades confirmed to
 * have been earned on a re-inspection that answered a failed initial. If the
 * page shows it for anybody else, it is quoting a number about somebody else.
 * So the interesting cases are all the ways it must STAY OFF.
 *
 * These run against the function as it actually ships: the source is extracted
 * from check.html rather than copied here, because a copy of the logic would
 * pass forever while the page changed underneath it.
 *
 *     node agrade_flag_test.cjs
 */
"use strict";
const fs = require("fs");
const path = require("path");

// check.html sits beside this file in the war room, and in ../data-app/ in
// the public repo. Same lookup the Python side does, same reason.
const HERE = __dirname;
const page = ["check.html", "../data-app/check.html"]
  .map(p => path.resolve(HERE, p))
  .find(p => fs.existsSync(p));
if (!page) {
  console.error("cannot find check.html beside this file or in ../data-app/");
  process.exit(1);
}

const html = fs.readFileSync(page, "utf8");

// Pull the function out by brace-matching from its declaration, so a change to
// its body cannot silently detach the test from the thing it tests.
const START = "function reinspectionAContext(";
const at = html.indexOf(START);
if (at === -1) {
  console.error("reinspectionAContext not found in check.html");
  process.exit(1);
}
let depth = 0, end = -1;
for (let i = html.indexOf("{", at); i < html.length; i++) {
  if (html[i] === "{") depth++;
  else if (html[i] === "}") { depth--; if (depth === 0) { end = i + 1; break; } }
}
const src = html.slice(at, end);
const reinspectionAContext = eval("(" + src + ")");   // eslint-disable-line no-eval

const CFG = { lookbackDays: 180, failScore: 14 };

// Build the (dates, byDate) pair render() works with: dates newest-first, and
// a Map from date to that inspection's violation rows.
function fixture(events) {
  const byDate = new Map();
  for (const e of events) {
    byDate.set(e.date, [{
      inspection_type: e.type,
      score: e.score === undefined ? null : e.score,
      grade: e.grade || null,
    }]);
  }
  const dates = events.map(e => e.date).sort().reverse();
  return [dates, byDate];
}

const RE = "Cycle Inspection / Re-inspection";
const IN = "Cycle Inspection / Initial Inspection";

let pass = 0, fail = 0;
function check(label, cond, detail) {
  cond ? pass++ : fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}` + (detail ? `\n      -> ${detail}` : ""));
}

// ── 1. the qualifying case: flag SHOWN ───────────────────────────────────
{
  const [d, m] = fixture([
    { date: "2026-03-01", type: IN, score: 24, grade: null },
    { date: "2026-04-10", type: RE, score: 9,  grade: "A" },
  ]);
  const r = reinspectionAContext(d, m, CFG);
  check("1. A on a re-inspection answering a failed initial -> SHOWN",
        r !== null && r.score === 24 && r.date === "2026-03-01",
        r ? `parent initial ${r.date} scored ${r.score}` : "returned null");
}

// ── 2. an A earned first time: flag ABSENT ───────────────────────────────
{
  const [d, m] = fixture([
    { date: "2025-05-02", type: IN, score: 11, grade: "A" },
    { date: "2026-04-10", type: IN, score: 8,  grade: "A" },
  ]);
  check("2. A earned on an initial inspection -> ABSENT",
        reinspectionAContext(d, m, CFG) === null);
}

// ── 3. not an A at all: flag ABSENT ──────────────────────────────────────
{
  const [d, m] = fixture([
    { date: "2026-03-01", type: IN, score: 30, grade: null },
    { date: "2026-04-10", type: RE, score: 19, grade: "B" },
  ]);
  check("3. re-inspection carrying a B -> ABSENT",
        reinspectionAContext(d, m, CFG) === null);
}

// ── 4. anything unconfirmable: flag ABSENT (withhold, never guess) ───────
const withheld = [
  ["no prior inspection at all",
   [{ date: "2026-04-10", type: RE, score: 9, grade: "A" }]],
  ["parent initial has no score (cannot confirm it failed)",
   [{ date: "2026-03-01", type: IN, score: null, grade: null },
    { date: "2026-04-10", type: RE, score: 9, grade: "A" }]],
  ["parent initial passed, so this answered nothing",
   [{ date: "2026-03-01", type: IN, score: 7, grade: "A" },
    { date: "2026-04-10", type: RE, score: 9, grade: "A" }]],
  ["parent initial is outside the lookback window",
   [{ date: "2025-08-01", type: IN, score: 24, grade: null },
    { date: "2026-04-10", type: RE, score: 9, grade: "A" }]],
  ["an unclassifiable visit sits in between",
   [{ date: "2026-03-01", type: IN, score: 24, grade: null },
    { date: "2026-03-20", type: "", score: null, grade: null },
    { date: "2026-04-10", type: RE, score: 9, grade: "A" }]],
  ["the displayed visit has no recorded type",
   [{ date: "2026-03-01", type: IN, score: 24, grade: null },
    { date: "2026-04-10", type: "", score: 9, grade: "A" }]],
];
for (const [label, events] of withheld) {
  const [d, m] = fixture(events);
  const r = reinspectionAContext(d, m, CFG);
  check(`4. ${label} -> ABSENT`, r === null,
        r ? `WRONGLY returned ${JSON.stringify(r)}` : "");
}

// ── the tests must be capable of failing ─────────────────────────────────
{
  const [d, m] = fixture([
    { date: "2026-03-01", type: IN, score: 24, grade: null },
    { date: "2026-04-10", type: RE, score: 9,  grade: "A" },
  ]);
  // Same fixture as case 1, but with the failure bar raised above the parent's
  // score: the initial no longer counts as failed, so the flag must go off.
  check("negative control: raising failScore above the parent turns it OFF",
        reinspectionAContext(d, m, { lookbackDays: 180, failScore: 25 }) === null);
}

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
