#!/usr/bin/env node
/*
 * UI/engine parity for Inspection Record Confidence.
 *
 * classifyIRC ships inside check.html; irc_engine.classify ships in Python.
 * Two implementations of one registered rule set drift silently - the GUARD
 * 10 lesson - so this harness extracts classifyIRC from the page AS IT SHIPS
 * and replays the shared fixture through it, against the same expectations
 * irc_engine_test.py pins on the Python side. If either side drifts, its own
 * suite fails.
 *
 *     node irc_ui_parity_test.cjs
 */
"use strict";
const fs = require("fs");
const path = require("path");

const HERE = __dirname;
const page = ["check.html", "../data-app/check.html"]
  .map(p => path.resolve(HERE, p)).find(p => fs.existsSync(p));
if (!page) { console.error("cannot find check.html"); process.exit(1); }
const html = fs.readFileSync(page, "utf8");

function extract(name) {
  const at = html.indexOf(name);
  if (at === -1) { console.error(`${name} not found in check.html`); process.exit(1); }
  let depth = 0, end = -1;
  for (let i = html.indexOf("{", at); i < html.length; i++) {
    if (html[i] === "{") depth++;
    else if (html[i] === "}") { depth--; if (depth === 0) { end = i + 1; break; } }
  }
  return html.slice(at, end);
}

// The classifier needs its two lookup tables; extract all three as shipped.
const src = extract("const IRC_LEVEL = ") + ";\n" +
            extract("function classifyIRC(");
const ctx = {};
const classifyIRC = new Function(
  "cfg", src + "\nreturn (dates, byDate, asofMs) => classifyIRC(dates, byDate, asofMs, cfg);"
)({ abstainAfterDays: 730, lookbackDays: 180, failScore: 14 });

const fx = JSON.parse(fs.readFileSync(path.resolve(HERE, "irc_fixture.json"), "utf8"));

function recordFor(camis, asof) {
  // The page classifies the record it can SEE. Visibility at a historical
  // as-of is rows dated on or before it - the same wall the engine builds.
  const byDate = new Map();
  for (const r of fx.rows) {
    if (String(r.camis) !== camis) continue;
    const d = (r.inspection_date || "").slice(0, 10);
    if (!d || d === "1900-01-01" || d > asof) continue;
    if (!byDate.has(d)) byDate.set(d, []);
    byDate.get(d).push({ inspection_type: r.inspection_type, score: r.score, grade: r.grade });
  }
  const dates = [...byDate.keys()].sort().reverse();
  return [dates, byDate];
}

// The SAME expectations irc_engine_test.py pins on the Python engine.
const EXPECT = [
  ["F01", "2023-05-01", "strong", "ORIGIN_INITIAL"],
  ["F02", "2023-03-15", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"],
  ["F03", "2023-03-15", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"],
  ["F04", "2023-03-15", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"],
  ["F05", "2023-06-30", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"],
  ["F06", "2023-07-01", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"],
  ["F07", "2023-04-01", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"],
  ["F08", "2023-03-15", "limited", "ORIGIN_REINSP_AFTER_PASSED_INITIAL"],
  ["F09", "2023-05-01", "limited", "ORIGIN_OTHER_CYCLE_FAILS_CLOSED"],
  ["F10", "2023-07-01", "displayed_grade_not_a", "DISPLAYED_GRADE_NOT_A"],
  ["F11", "2023-05-02", "not_enough_current_evidence", "A_EVENT_NOT_ELIGIBLE"],
  ["F12", "2023-01-01", "strong", "ORIGIN_INITIAL"],
  ["F12", "2023-01-02", "not_enough_current_evidence", "EVIDENCE_TOO_OLD"],
  ["F14A", "2023-05-01", "strong", "ORIGIN_INITIAL"],
  ["F14B", "2023-03-15", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"],
  ["F15", "2023-05-01", "strong", "ORIGIN_INITIAL"],
  ["F16", "2023-04-01", "strong", "ORIGIN_INITIAL"],
  ["F17", "2023-06-01", "not_enough_current_evidence", "NO_GRADED_RECORD"],
];

let pass = 0, fail = 0;
function check(label, cond, detail) {
  cond ? pass++ : fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}` + (detail ? `\n      -> ${detail}` : ""));
}

const seen = new Set();
let bad = [];
for (const [camis, asof, state, reason] of EXPECT) {
  const [dates, byDate] = recordFor(camis, asof);
  const got = classifyIRC(dates, byDate, Date.parse(asof + "T00:00:00Z"));
  seen.add(got.state);
  if (got.state !== state || got.reason !== reason)
    bad.push(`${camis}@${asof}: got ${got.state}/${got.reason}, want ${state}/${reason}`);
}
check("all shared fixture cases: UI classifier === Python engine", bad.length === 0,
      bad.length ? bad.join("; ") : `${EXPECT.length} cases, byte-for-byte agreement of state and reason`);

check("moderate is impossible in the UI: never emitted, absent from the level map",
      !seen.has("moderate") && !/["']moderate["']/.test(extract("const IRC_LEVEL = ")),
      `states emitted: ${[...seen].sort().join(", ")}`);

check("age produces abstention only, never Strong-to-Limited movement",
      (() => {
        const [d729, b729] = recordFor("F12", "2022-12-31");
        const [d731, b731] = recordFor("F12", "2023-01-02");
        const at729 = classifyIRC(d729, b729, Date.parse("2022-12-31T00:00:00Z"));
        const at731 = classifyIRC(d731, b731, Date.parse("2023-01-02T00:00:00Z"));
        return at729.state === "strong" && at731.state === "not_enough_current_evidence";
      })(), "age 729 -> strong; age 731 -> abstain; limited is unreachable via age");

// negative control (Cheatcode #22): a shifted lookback must flip the boundary case
const tight = new Function(
  "cfg", src + "\nreturn (dates, byDate, asofMs) => classifyIRC(dates, byDate, asofMs, cfg);"
)({ abstainAfterDays: 730, lookbackDays: 179, failScore: 14 });
const [d5, b5] = recordFor("F05", "2023-06-30");
check("negative: a 179-day lookback flips the 180-day case (drift WOULD be caught)",
      tight(d5, b5, Date.parse("2023-06-30T00:00:00Z")).reason
        === "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
      "boundary sensitivity is real on the UI side too");

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
