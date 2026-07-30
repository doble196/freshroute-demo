// Every fault in dirt_manifest.csv was DECLARED before it was injected
// (make_synthetic.py). This asserts each one lands where the manifest says —
// the test reads the manifest, so a regenerated fixture re-tests itself.
//
// Paths resolve from THIS file's location, so it runs from anywhere:
//   node data/inventory-app/test-data/vendors-test.js     (repo root)
//   node test-data/vendors-test.js                        (app dir)

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCSV, csvCell, normKey, C } from "../logic.js";
import { parseVendors, planOrder, planOrders, caseRound, VC } from "../vendor-logic.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const read = f => parseCSV(readFileSync(join(HERE, f), "utf8"));
const manifest = read("dirt_manifest.csv").rows;
const messy = parseVendors(read("messy_vendors.csv").rows);
const cleanVendors = parseVendors(read("../data/vendors.csv").rows);
const stockRows = read("messy_vendor_stock.csv").rows;

let pass = 0, fail = 0;
const t = (label, cond, detail = "") => {
  cond ? pass++ : fail++;
  console.log(`${cond ? "PASS" : "FAIL"}  ${label}${detail ? `\n      → ${detail}` : ""}`);
};

console.log(`manifest: ${manifest.length} declared faults · vendor table -> ` +
  `${messy.vendors.size} usable, ${messy.review.length} review, ` +
  `${messy.conflicts.length} conflicts, ${messy.merged.length} folds\n`);

// ── 1. every declared vendor-table fault lands where the manifest says ──
console.log("=== manifest: vendor-table faults ===");
for (const m of manifest.filter(r => r.file === "messy_vendors.csv")) {
  const id = m.id.trim();
  const inReview = messy.review.find(r => r[VC.vendor] === id);
  if (m.expect === "review")
    t(`row ${m.row} [${m.guard}] ${id} -> review`, !!inReview, inReview?._reason ?? "NOT in review");
  else if (m.expect === "clean")
    t(`row ${m.row} [${m.guard}] ${id} -> usable`, messy.vendors.has(normKey(id)) && !inReview);
  // fold/conflict/dedupe pairs are asserted structurally below
}

// ── 2. the pairs: fold, conflict, dedupe ─────────────────────────────
console.log("\n=== pairs: fold / conflict / dedupe ===");
t("' mother dairy ' folds — no extra vendor",
  [...messy.vendors.keys()].filter(k => k === "mother dairy").length === 1 &&
  messy.merged.some(mg => mg.column === VC.vendor),
  messy.merged.map(mg => JSON.stringify(mg.folded)).join(" "));
t("Raj discount conflict resolved to the LOWER value (2.0, not 2.5)",
  messy.vendors.get("raj")?.discount === 2.0, `kept: ${messy.vendors.get("raj")?.discount}`);
t("Raj conflict is REPORTED, not silently picked",
  messy.conflicts.some(c => normKey(c.vendor) === "raj"),
  messy.conflicts.map(c => c._reason).join(" | "));
t("byte-identical Sudha pair collapses silently — one vendor, NO conflict",
  messy.vendors.has("sudha") && !messy.conflicts.some(c => normKey(c.vendor) === "sudha"));
t("exactly the 6 vendors with fully-valid rows survive",
  messy.vendors.size === 6, `got: ${[...messy.vendors.keys()].join(", ")}`);

// ── 3. quoting: the address survives a full CSV round trip ───────────
console.log("\n=== quoting ===");
const addr = 'Plot 7, "Gate B", Milk Colony, Pune';
const rt = parseCSV(`h\r\n${csvCell(addr)}\r\n`).rows[0].h;
t("comma-and-quote address survives parse from fixture",
  messy.review.concat([...messy.vendors.values()].map(v => ({ [VC.address]: v.address })))
    .some(r => (r[VC.address] ?? r.address) === addr) ||
  [...messy.vendors.values()].some(v => v.address === addr),
  [...messy.vendors.values()].map(v => v.address).find(a => a.includes("Gate B")) ?? "not found");
t("csvCell round trip is lossless (RFC 4180)", rt === addr, rt);

// ── 4. the join: manifest-driven, computed expectations ──────────────
console.log("\n=== join: stock rows -> purchase orders ===");
const MON_10AM = new Date("2022-12-05T10:00:00");   // Monday, before every cutoff
const { orders, review: joinReview } = planOrders(stockRows, cleanVendors.vendors, MON_10AM);

t("no join explosion: 4 stock rows -> exactly 4 outcomes",
  orders.length + joinReview.length === stockRows.length,
  `${orders.length} orders + ${joinReview.length} review`);

for (const m of manifest.filter(r => r.file === "messy_vendor_stock.csv")) {
  const [brandish, product] = m.id.split("/");
  const order = orders.find(o => o.product === product);
  if (m.expect === "review") {
    t(`stock row ${m.row} [${m.guard}] ${m.id} -> review, not a silent order`,
      joinReview.some(r => r[C.product] === product),
      joinReview.find(r => r[C.product] === product)?._reason);
  } else {
    const okUnits = order && String(order.units) === m.expected_units &&
                    String(order.cases) === m.expected_cases;
    t(`stock row ${m.row} [${m.guard}] ${m.id} -> ${m.expected_units} units / ${m.expected_cases} cases`,
      !!okUnits, order ? `got ${order.units} units / ${order.cases} cases` : "no order produced");
  }
}

// ── 5. money: discount applied to the rounded-up units ───────────────
console.log("\n=== money ===");
const amul = cleanVendors.vendors.get("amul");
const milk = orders.find(o => o.product === "Milk");
const expectCost = Math.round(milk.units * 42.61 * (1 - amul.discount / 100) * 100) / 100;
t(`cost = units x price x (1 - ${amul.discount}%)`, milk.cost === expectCost,
  `${milk.units} x 42.61 x ${1 - amul.discount / 100} = ${milk.cost}`);
t("order carries the vendor's address (the driver needs it, not the DB)",
  milk.address === amul.address, milk.address);

// ── 6. time: cutoff, weekday lead, closed days ───────────────────────
console.log("\n=== time: cutoff / weekday / closed ===");
const mkStock = over => ({ [C.brand]: over.brand, [C.product]: "Milk", [C.location]: "X",
  [C.reorder]: "10", "Price per Unit": "50" });

// Amul: cutoff 15:30, lead Mon 2 -> Wed. Same order at 16:00 slips to Tue (lead 2) -> Thu.
const before = planOrder(mkStock({ brand: "Amul" }), cleanVendors.vendors, new Date("2022-12-05T10:00:00")).order;
const after  = planOrder(mkStock({ brand: "Amul" }), cleanVendors.vendors, new Date("2022-12-05T16:00:00")).order;
t("before the cutoff: Monday order arrives Wednesday", before.arrival === "2022-12-07",
  `${before.effectiveDay} +${before.leadDays}d -> ${before.arrival}`);
t("AFTER the cutoff the same order becomes Tuesday's -> arrives Thursday", after.arrival === "2022-12-08",
  `${after.effectiveDay} +${after.leadDays}d -> ${after.arrival}`);

// Weekday matters: Amul Friday lead is 3, not 2.
const friday = planOrder(mkStock({ brand: "Amul" }), cleanVendors.vendors, new Date("2022-12-09T10:00:00")).order;
t("Friday order uses Friday's lead (3d, not Monday's 2d)", friday.leadDays === 3 && friday.arrival === "2022-12-12",
  `${friday.effectiveDay} +${friday.leadDays}d -> ${friday.arrival}`);

// Britannia: Lead Sun blank = closed. Sunday order -> review; Monday -> fine.
const sun = planOrder(mkStock({ brand: "Britannia Industries" }), cleanVendors.vendors, new Date("2022-12-11T09:00:00"));
const mon = planOrder(mkStock({ brand: "Britannia Industries" }), cleanVendors.vendors, new Date("2022-12-12T09:00:00"));
t("Sunday order to a Sunday-closed vendor -> review, not a fake arrival date",
  !!sun.review, sun.review?._reason);
t("same vendor on Monday -> a real order", !!mon.order, mon.order && `arrives ${mon.order.arrival}`);

// The compound trap: Saturday 13:00 is past Britannia's 12:30 cutoff, so the
// order slips to SUNDAY — which is closed. Two rules interacting correctly.
const trap = planOrder(mkStock({ brand: "Britannia Industries" }), cleanVendors.vendors, new Date("2022-12-10T13:00:00"));
t("Saturday-after-cutoff slips onto the closed Sunday -> review names both rules",
  !!trap.review && /cutoff/.test(trap.review._reason), trap.review?._reason);

// ── 7. caseRound in isolation ────────────────────────────────────────
console.log("\n=== case rounding ===");
t("exact multiple stays exact", caseRound(96, 48).cases === 2 && caseRound(96, 48).units === 96);
t("one unit over rounds UP", caseRound(49, 48).cases === 2 && caseRound(49, 48).units === 96);
t("tiny order still buys a whole case", caseRound(1, 24).units === 24);

console.log(`\n${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
