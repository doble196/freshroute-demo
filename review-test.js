// Break the data on purpose; confirm the review bucket screams.
// An empty review bucket on clean data proves nothing — Cheatcode #22.
// Runs from anywhere — paths resolve from this file's location:
//   node data/inventory-app/review-test.js    (repo root)
//   node review-test.js                       (app dir)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCSV, toSnapshot, reorderList, expiringSoon, C } from "./logic.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const raw = parseCSV(readFileSync(join(HERE, "data/dairy_dataset.csv"), "utf8"));
const CLEAN = toSnapshot(raw.rows);

// Corrupt ONE field on the first row and hand back a fresh copy.
function corrupt(snapshot, column, value) {
  const copy = snapshot.map(r => ({ ...r }));
  copy[0][column] = value;
  return copy;
}

const reviewCount = snap => {
  const { unknown } = reorderList(snap);
  const { unparseable } = expiringSoon(snap, new Date("2023-05-03"));
  return { n: unknown.length + unparseable.length,
           why: [...unknown, ...unparseable][0]?._reason };
};

const cases = [
  // label,                       column,      injected value,  should be caught?
  ["baseline — untouched",        null,        null,            false],
  ["stock is 'N/A'",              C.stock,     "N/A",           true ],
  ["stock is empty",              C.stock,     "",              true ],
  ["stock has a stray unit",      C.stock,     "42 L",          true ],
  ["stock is 'unknown'",          C.stock,     "unknown",       true ],
  ["threshold is 'TBD'",          C.threshold, "TBD",           true ],
  ["threshold is empty",          C.threshold, "",              true ],
  ["negative stock",              C.stock,     "-5",            true ],
  ["expiry is 'not a date'",      C.expiry,    "not a date",    true ],
  ["expiry is empty",             C.expiry,    "",              true ],
  ["expiry is '00/00/0000'",      C.expiry,    "00/00/0000",    true ],
  ["stock is a normal number",    C.stock,     "37",            false], // must NOT fire
];

const base = reviewCount(CLEAN);
console.log(`clean snapshot: ${CLEAN.length} positions, ${base.n} in review\n`);

let pass = 0, fail = 0;
for (const [label, column, value, shouldCatch] of cases) {
  const snap = column ? corrupt(CLEAN, column, value) : CLEAN.map(r => ({ ...r }));

  // GUARD: if the injection didn't change anything, this test is lying.
  // (Learned the hard way in reporting-app/audit-test.js — a replace() that
  //  never matched looked exactly like a check that failed to fire.)
  if (column && snap[0][column] !== value) {
    console.log(`FAIL  ${label}\n      INJECTION DID NOT APPLY — test bug, not a finding`);
    fail++; continue;
  }

  const got = reviewCount(snap);
  const caught = got.n > base.n;
  const ok = caught === shouldCatch;
  ok ? pass++ : fail++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  console.log(`      expected caught=${shouldCatch}, got=${caught}` +
              (got.why && caught ? `\n      → ${got.why}` : ""));
}

console.log(`\nreview bucket: ${pass} passed, ${fail} failed`);

// ── location filter ──────────────────────────────────────────────────
import { byLocation, locationCounts, ALL_LOCATIONS } from "./logic.js";

console.log("\n=== location filter ===");
const { flagged } = reorderList(CLEAN);
const counts = locationCounts(flagged, CLEAN);
let lf_pass = 0, lf_fail = 0;
const check = (label, cond, detail = "") => {
  cond ? lf_pass++ : lf_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

check("ALL_LOCATIONS returns everything untouched",
      byLocation(flagged, ALL_LOCATIONS).length === flagged.length,
      `${flagged.length} flagged`);

check("undefined location returns everything (no accidental empty view)",
      byLocation(flagged, undefined).length === flagged.length);

// The sum of every location's slice must equal the whole — nothing lost, nothing double-counted.
const partitioned = counts.reduce((n, c) => n + byLocation(flagged, c.location).length, 0);
check("per-location slices sum to the total (no rows lost or duplicated)",
      partitioned === flagged.length, `${partitioned} === ${flagged.length}`);

check("dropdown counts match the actual filtered rows",
      counts.every(c => byLocation(flagged, c.location).length === c.flagged),
      counts.slice(0, 3).map(c => `${c.location}:${c.flagged}`).join(" "));

check("counts are sorted worst-first",
      counts.every((c, i) => i === 0 || counts[i - 1].flagged >= c.flagged),
      `top: ${counts[0].location} (${counts[0].flagged})`);

check("an unknown location yields an empty list, not everything",
      byLocation(flagged, "Atlantis").length === 0);

console.log(`\nfilter: ${lf_pass} passed, ${lf_fail} failed`);



// ── CSV export round-trip ────────────────────────────────────────────
import { toCSV, csvCell, ORDER_COLUMNS } from "./logic.js";

console.log("\n=== csv export ===");
let cx_pass = 0, cx_fail = 0;
const cx = (label, cond, detail = "") => {
  cond ? cx_pass++ : cx_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

cx("plain value is not quoted", csvCell("Butter") === "Butter");
cx("comma forces quotes", csvCell("Bloom & Sons, LLC") === '"Bloom & Sons, LLC"',
   csvCell("Bloom & Sons, LLC"));
cx("inner quote is doubled", csvCell('He said "hi"') === '"He said ""hi"""',
   csvCell('He said "hi"'));
cx("newline forces quotes", csvCell("a\nb") === '"a\nb"');
cx("null becomes empty, not the string 'null'", csvCell(null) === "");

// The real proof: export it, parse it back, confirm the values survive.
const dirty = [{ [C.product]: "Bloom & Sons, LLC", [C.brand]: 'The "Good" Dairy',
                 [C.location]: "Haryana", [C.stock]: "1", [C.threshold]: "90",
                 [C.reorder]: "156", [C.storage]: "Frozen", _gap: 89 }];
const out = toCSV(dirty, ORDER_COLUMNS);
const back = parseCSV(out.replace(/\r\n/g, "\n"));
cx("round-trip: header count survives", back.headers.length === ORDER_COLUMNS.length,
   `${back.headers.length} columns`);
cx("round-trip: comma-containing name survives intact",
   back.rows[0]["Product"] === "Bloom & Sons, LLC", back.rows[0]["Product"]);
cx("round-trip: quoted name survives intact",
   back.rows[0]["Brand"] === 'The "Good" Dairy', back.rows[0]["Brand"]);
cx("round-trip: no column shift (Storage still Storage)",
   back.rows[0]["Storage"] === "Frozen", back.rows[0]["Storage"]);

// And against the real flagged list, not just a fixture.
const realOut = toCSV(flagged, ORDER_COLUMNS);
const realBack = parseCSV(realOut.replace(/\r\n/g, "\n"));
cx("real export: every row round-trips with the right column count",
   realBack.rows.every(r => r.__cells === ORDER_COLUMNS.length),
   `${realBack.rows.length} rows exported`);
cx("real export: row count matches flagged count",
   realBack.rows.length === flagged.length, `${realBack.rows.length} === ${flagged.length}`);

console.log(`\ncsv: ${cx_pass} passed, ${cx_fail} failed`);



// ── group by storage ─────────────────────────────────────────────────
import { groupByStorage, storageRank, STORAGE_ORDER } from "./logic.js";

console.log("\n=== group by storage ===");
let gs_pass = 0, gs_fail = 0;
const gs = (label, cond, detail = "") => {
  cond ? gs_pass++ : gs_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

const groups = groupByStorage(flagged);

gs("every flagged row lands in exactly one group",
   groups.reduce((n, g) => n + g.rows.length, 0) === flagged.length,
   `${groups.reduce((n, g) => n + g.rows.length, 0)} === ${flagged.length}`);

gs("groups come out in DECLARED order, not alphabetical",
   groups.every((g, i) => i === 0 || storageRank(groups[i-1].storage) <= storageRank(g.storage)),
   groups.map(g => `${g.storage}(${g.rows.length})`).join(" → "));

gs("alphabetical would have been wrong (Ambient is not first)",
   groups[0].storage !== "Ambient", `first group: ${groups[0].storage}`);

gs("an unrecognized storage value gets its own group, flagged, sorted LAST",
   (() => {
     const odd = [...flagged.map(r => ({ ...r })), { ...flagged[0], [C.storage]: "Cryogenic" }];
     const g2 = groupByStorage(odd);
     const last = g2[g2.length - 1];
     return last.storage === "Cryogenic" && last.unknown === true;
   })());

gs("a blank storage value becomes '(not recorded)', not dropped",
   (() => {
     const blank = [{ ...flagged[0], [C.storage]: "" }];
     const g2 = groupByStorage(blank);
     return g2.length === 1 && g2[0].storage === "(not recorded)" && g2[0].rows.length === 1;
   })());

gs("declared order covers every storage value actually in the data",
   groups.filter(g => g.unknown).length === 0,
   `unknown groups: ${groups.filter(g => g.unknown).map(g => g.storage).join(", ") || "none"}`);

console.log(`\ngroup: ${gs_pass} passed, ${gs_fail} failed`);


// ── morning brief ────────────────────────────────────────────────────
import { morningBrief, briefPrompt, byLocation as byLoc2 } from "./logic.js";

console.log("\n=== morning brief ===");
let mb_pass = 0, mb_fail = 0;
const mb = (label, cond, detail = "") => {
  cond ? mb_pass++ : mb_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

const conflicts = CLEAN.conflicts ?? [];
const allBrief = morningBrief(CLEAN, flagged, [], [], conflicts);

mb("brief is non-empty and every line is a string",
   allBrief.length > 0 && allBrief.every(l => typeof l === "string"), `${allBrief.length} lines`);

mb("headline states the real counts",
   allBrief[0].includes(String(flagged.length)) && allBrief[0].includes(String(CLEAN.length)),
   allBrief[0]);

mb("no unresolved template placeholders",
   !allBrief.some(l => /undefined|NaN|\[object/.test(l)),
   allBrief.find(l => /undefined|NaN|\[object/.test(l)) || "clean");

// The bug found by cold-testing the filter: conflicts arrived unfiltered, so
// filtering to Haryana claimed 2 conflicts that live in Tamil Nadu and Kerala.
const hSnap = byLoc2(CLEAN, "Haryana");
const hFlag = byLoc2(flagged, "Haryana");
const hBrief = morningBrief(hSnap, hFlag, [], [], conflicts);
const conflictLocs = new Set(conflicts.map(c => c[C.location]));
mb("conflicts are scoped to the filter, not reported globally",
   conflictLocs.has("Haryana") === hBrief.some(l => l.includes("conflicting")),
   `conflicts live in [${[...conflictLocs].join(", ")}]; Haryana brief mentions conflicts: ${hBrief.some(l => l.includes("conflicting"))}`);

// Filtered to one location, "X is worst ... against a Y% average" compares a
// place against itself, and "spread across 1 locations" is nonsense.
mb("single-location scope drops the cross-location comparison",
   !hBrief.some(l => l.includes("is worst")),
   hBrief.find(l => l.includes("is worst")) || "absent, correct");

mb("no '1 locations' / '1 positions expire' grammar breaks",
   !allBrief.concat(hBrief).some(l => /\b1 locations\b|\b1 positions\b|\b1 position expire\b/.test(l)),
   allBrief.concat(hBrief).find(l => /\b1 locations\b|\b1 positions\b|\b1 position expire\b/.test(l)) || "clean");

mb("filtered brief reports the filtered numbers, not the global ones",
   hBrief[0].includes(String(hFlag.length)) && hBrief[0].includes(String(hSnap.length)),
   hBrief[0]);

const prompt = briefPrompt(allBrief, flagged, "2022-12-28");
mb("prompt embeds the brief and the urgent rows",
   prompt.includes(allBrief[0]) && prompt.includes(flagged[0][C.product]) && prompt.includes("2022-12-28"),
   `${prompt.split("\n").length} lines`);

console.log(`\nbrief: ${mb_pass} passed, ${mb_fail} failed`);


// ── order by supplier ────────────────────────────────────────────────
import { bySupplier, supplierOrderText } from "./logic.js";

console.log("\n=== order by supplier ===");
let sp_pass = 0, sp_fail = 0;
const sp = (label, cond, detail = "") => {
  cond ? sp_pass++ : sp_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

const fileToday = new Date(Math.max(...CLEAN.map(r => new Date(r[C.date])).filter(d => !isNaN(d))));
const { soon: soonRows } = expiringSoon(CLEAN, fileToday, 14);
const cards = bySupplier(flagged, soonRows);

sp("every flagged item lands in exactly one supplier card",
   cards.reduce((n, g) => n + g.rows.length, 0) === flagged.length,
   `${cards.reduce((n, g) => n + g.rows.length, 0)} === ${flagged.length}`);

sp("no item appears in two cards",
   new Set(cards.flatMap(g => g.rows.map(r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`))).size === flagged.length);

sp("113 items collapse to a handful of calls",
   cards.length < 15 && cards.length > 1, `${cards.length} suppliers`);

sp("suppliers WITH a conflict sort before suppliers without",
   (() => { const firstClean = cards.findIndex(g => g.conflicts === 0);
            return firstClean === -1 || cards.slice(firstClean).every(g => g.conflicts === 0); })(),
   cards.map(g => `${g.supplier}:${g.conflicts}`).join(" "));

const conflictItems = cards.reduce((n, g) => n + g.rows.filter(r => r._expiresInDays !== undefined).length, 0);
sp("an item both low AND expiring is marked, not silently reordered",
   conflictItems === cards.reduce((n, g) => n + g.conflicts, 0) && conflictItems > 0,
   `${conflictItems} conflict rows`);

sp("expiring items are NOT removed from the order list — flagged, not resolved",
   cards.flatMap(g => g.rows).length === flagged.length);

const txt = supplierOrderText(cards[0], "2022-12-28");
sp("order text names every item in the card",
   cards[0].rows.every(r => txt.includes(r[C.product]) && txt.includes(r[C.location])));
sp("order text warns about conflicts inline, not as a footnote",
   cards[0].conflicts === 0 || (txt.includes("confirm before ordering") && txt.includes("<< expires in")),
   txt.split("\n").find(l => l.includes("confirm before ordering")) ?? "no conflicts in card 0");

console.log(`\nsupplier: ${sp_pass} passed, ${sp_fail} failed`);


// ── the cap must never hide a conflict ───────────────────────────────
import { capWithExemptions } from "./logic.js";

console.log("\n=== cap exemptions ===");
let ce_pass = 0, ce_fail = 0;
const ce = (label, cond, detail = "") => {
  cond ? ce_pass++ : ce_fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

const annotated = flagged.map(r => {
  const hit = soonRows.find(s => s[C.product] === r[C.product] && s[C.brand] === r[C.brand] && s[C.location] === r[C.location]);
  return hit ? { ...r, _expiresInDays: hit._daysLeft } : r;
});
const totalConflicts = annotated.filter(r => r._expiresInDays !== undefined).length;

ce("fixture has conflicts to hide (otherwise this proves nothing)",
   totalConflicts > 0, `${totalConflicts} conflicted items`);

// THE invariant, at every cap from brutal to generous
let allOk = true, worst = "";
for (const cap of [1, 3, 5, 10, 20, 50, 113]) {
  const { shown, exempt, exemptOverflow } = capWithExemptions(annotated, cap);
  const visible = new Set([...shown, ...exempt].filter(r => r._expiresInDays !== undefined)
    .map(r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`));
  if (visible.size + exemptOverflow !== totalConflicts) { allOk = false; worst = `cap=${cap}: ${visible.size}+${exemptOverflow} of ${totalConflicts}`; }
}
ce("every conflict is visible or counted, at EVERY cap size", allOk, worst || "caps 1,3,5,10,20,50,113 all clean");

const tiny = capWithExemptions(annotated, 1);
ce("a brutal cap (1 row) still surfaces the conflicts",
   tiny.exempt.length + tiny.exemptOverflow >= totalConflicts - (tiny.shown.filter(r=>r._expiresInDays!==undefined).length),
   `cap=1 → ${tiny.shown.length} shown + ${tiny.exempt.length} exempt`);

ce("the exemption has its OWN bound — a bad week can't defeat the cap",
   capWithExemptions(annotated, 0, 2).exempt.length === 2 &&
   capWithExemptions(annotated, 0, 2).exemptOverflow === totalConflicts - 2,
   `exemptCap=2 → 2 shown, ${totalConflicts - 2} overflow (stated, not dropped)`);

ce("a list with no conflicts produces no exempt block",
   capWithExemptions(flagged.map(({_expiresInDays, ...r}) => r), 5).exempt.length === 0);

ce("the ranking is untouched — shown rows are still the top N by severity",
   capWithExemptions(annotated, 20).shown.every((r, i) => i === 0 || annotated[i - 1]._severity >= r._severity));

console.log(`\ncap exemptions: ${ce_pass} passed, ${ce_fail} failed`);

// Guard: assert every case actually ran. A suite that silently skips half
// its tests and prints "passed" is the exact failure this file exists to
// catch — it happened once already writing this.
const EXPECTED_CASES = cases.length + 6 + 11 + 6 + 8 + 8 + 6;
const ran = pass + fail + lf_pass + lf_fail + cx_pass + cx_fail + gs_pass + gs_fail + mb_pass + mb_fail + sp_pass + sp_fail + ce_pass + ce_fail;
if (ran !== EXPECTED_CASES) {
  console.log(`\nFAIL  only ${ran} of ${EXPECTED_CASES} cases executed — suite is skipping tests`);
  process.exit(1);
}
console.log(`\nTOTAL: ${pass + lf_pass + cx_pass + gs_pass + mb_pass + sp_pass + ce_pass}/${EXPECTED_CASES} passed`);
process.exit(fail + lf_fail + cx_fail + gs_fail + mb_fail + sp_fail + ce_fail ? 1 : 0);
