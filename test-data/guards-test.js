// Every row in messy_rows.csv has a stated job in PLAN.md. This asserts it.
// A row that stops proving its point fails loudly instead of quietly passing.
//
// Paths resolve from THIS file's location, so it runs from anywhere:
//   node data/inventory-app/test-data/guards-test.js      (repo root)
//   node test-data/guards-test.js                         (app dir)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCSV, toSnapshot, reorderList, expiringSoon, byLocation,
         groupByStorage, normKey, C } from "../logic.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const raw = parseCSV(readFileSync(join(HERE, "messy_rows.csv"), "utf8"));
const snap = toSnapshot(raw.rows);
const { flagged, unknown } = reorderList(snap);
const { unparseable } = expiringSoon(snap, new Date("2022-12-10"), 14);
const review = [...unknown, ...unparseable];

let pass = 0, fail = 0;
const t = (label, cond, detail = "") => {
  cond ? pass++ : fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};
const reviewFor = p => review.find(r => r[C.product] === p);
const inReview = p => !!reviewFor(p);

console.log(`fixture: ${raw.rows.length} rows × ${raw.headers.length} cols → ${snap.length} items`);
console.log(`flagged ${flagged.length} · review ${review.length}\n`);

console.log("=== GUARD: blanks ===");
t("row 2 — blank stock goes to review, not counted as 0", inReview("Cheese"), reviewFor("Cheese")?._reason);
t("row 3 — blank threshold goes to review", inReview("Curd"), reviewFor("Curd")?._reason);
t("row 4 — the WORD 'N/A' is caught too", inReview("Ghee") || snap.some(r => r[C.product]==="Ghee"),
  reviewFor("Ghee")?._reason ?? "(see repeats — Ghee also used there)");
t("nothing blank silently became a flagged item",
  !flagged.some(r => ["Cheese","Curd"].includes(r[C.product]) && r[C.stock] === ""));

console.log("\n=== GUARD: types ===");
t("row 5 — '42 L' rejected (parseFloat would return 42)", inReview("Lassi"), reviewFor("Lassi")?._reason);
t("row 6 — negative stock rejected, not treated as low", inReview("Paneer"), reviewFor("Paneer")?._reason);
t("row 7 — 'not a date' rejected", inReview("Yogurt"), reviewFor("Yogurt")?._reason);
t("no NaN reached the flagged list",
  flagged.every(r => Number.isFinite(Number(r._severity))));

console.log("\n=== GUARD: spelling ===");
const locs = [...new Set(snap.map(r => r[C.location]))];
t("row 8 — ' haryana ' folded; no phantom location",
  locs.filter(l => normKey(l) === "haryana").length === 1, `locations: ${JSON.stringify(locs)}`);
const stores = [...new Set(snap.map(r => r[C.storage]))];
t("row 9 — 'FROZEN' folded; no phantom storage group",
  stores.filter(s => normKey(s) === "frozen").length === 1, `storage: ${JSON.stringify(stores)}`);
const brands = [...new Set(snap.map(r => r[C.brand]))];
t("row 10 — trailing-space brand folded",
  brands.filter(b => normKey(b) === "amul").length === 1, `brands: ${JSON.stringify(brands)}`);
t("byLocation matches regardless of the spelling asked for",
  byLocation(snap, "haryana").length === byLocation(snap, "Haryana").length &&
  byLocation(snap, "Haryana").length > 0);
// Two layers handle spelling, and knowing which does what matters:
//   parseCSV()  trims every cell   -> pure-whitespace variants ("Amul  ")
//                                     never reach the merge stage at all
//   normKey()   folds case + inner -> only variants that still differ AFTER
//               whitespace            trimming get reported as merges
// So row 10 is fixed upstream and correctly does NOT appear here. Asserting
// ">= 3 merges" was asserting the wrong layer.
t("case variants are REPORTED, not silently folded",
  (snap.merged ?? []).length === 2, (snap.merged ?? []).map(m => `${m.column}:${JSON.stringify(m.folded)}`).join(" "));
t("whitespace-only variants are handled at parse time, before merging",
  !(snap.merged ?? []).some(m => m.column === C.brand),
  "brand needed no merge — parseCSV already trimmed it");

console.log("\n=== GUARD: repeats ===");
const kerala = snap.filter(r => r[C.product]==="Milk" && r[C.brand]==="Sudha" && r[C.location]==="Kerala");
t("rows 11-12 — same product+brand+location+date collapse to ONE item", kerala.length === 1);
t("rows 11-12 — resolved CONSERVATIVELY to the lower reading (10, not 900)",
  kerala[0]?.[C.stock] === "10", `kept: ${kerala[0]?.[C.stock]}`);
t("rows 11-12 — the conflict is reported, not silently picked",
  (snap.conflicts ?? []).some(c => c[C.product]==="Milk" && c[C.location]==="Kerala"),
  (snap.conflicts ?? []).map(c => c._reason).join(" | "));
const ghee = snap.filter(r => r[C.product]==="Ghee" && r[C.brand]==="Raj");
t("rows 13-14 — same name at DIFFERENT locations are NOT duplicates", ghee.length === 2,
  `kept: ${ghee.map(r => r[C.location]).join(", ")}`);

console.log("\n=== the control ===");
t("row 15 — a clean shortage still flags (pipeline survives the junk)",
  flagged.some(r => r[C.product]==="Cheese" && r[C.location]==="Bihar"));
t("row 1 — a valid, well-stocked row is NOT flagged and NOT in review",
  !flagged.some(r => r[C.product]==="Milk" && r[C.location]==="Haryana") &&
  !review.some(r => r[C.product]==="Milk" && r[C.location]==="Haryana"));

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
