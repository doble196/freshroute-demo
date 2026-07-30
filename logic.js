// Pure data logic — no DOM. Imported by BOTH script.js (browser) and
// review-test.js (node), so the test exercises the exact code that ships.
// (audit-test.js in reporting-app/ keeps a hand-synced copy; that's a
//  liability this file exists to avoid.)

export const C = {
  product: "Product Name", brand: "Brand", location: "Location", date: "Date",
  stock: "Quantity in Stock (liters/kg)",
  threshold: "Minimum Stock Threshold (liters/kg)",
  reorder: "Reorder Quantity (liters/kg)",
  storage: "Storage Condition", expiry: "Expiration Date",
};

export const EXPIRY_WINDOW_DAYS = 14;

// ── Where the numbers come from ──────────────────────────────────────
// Three different things, and a user can't tell them apart by looking:
//
//   SYNTHETIC  Generated. The shapes are realistic, the values are invented.
//              Safe to build against, NEVER safe to conclude anything from.
//   STATIC     A real file, downloaded once. The values are true — as of the
//              day it was exported. Every day after that it drifts further
//              from reality, and nothing in the file says so.
//   LIVE       A stream or API. True right now; needs a "last updated" and a
//              plan for what happens when the feed dies.
//
// Declaring it is the point. A dashboard that doesn't say which of these it
// is invites the reader to assume LIVE, because that's what a screen full of
// current-looking numbers implies.
export const SOURCE_KINDS = {
  synthetic: { label: "SYNTHETIC DATA",
               note: "Generated for testing. Realistic shape, invented values — don't act on these numbers." },
  static:    { label: "STATIC FILE",
               note: "A real export, downloaded once. True as of the date below, not since." },
  live:      { label: "LIVE FEED",
               note: "Streaming from the source." },
};

// This app reads a real Kaggle export that stopped in 2022 — STATIC, not LIVE.
export const DATA_SOURCE = "static";

// ── GUARD: spelling ──────────────────────────────────────────────────
// Match on a normalised copy; never overwrite what the file said.
// "Haryana", "haryana" and " Haryana " are one place. Compared raw they
// become three — which splits a location into phantom entries in the
// dropdown, splits a storage group in two, and inflates the item count.
// Verified on this file: 3 injected variants turned 600 items into 602.
export function normKey(v) {
  return String(v ?? "").trim().replace(/\s+/g, " ").toLowerCase();
}

// When variants of one value exist, display the one that appears most often —
// a real spelling from the file, never an invented "correct" one. Ties break
// alphabetically so the choice is reproducible.
export function canonical(values) {
  const counts = new Map();
  for (const v of values) {
    const k = normKey(v);
    if (!counts.has(k)) counts.set(k, new Map());
    const m = counts.get(k);
    m.set(v, (m.get(v) || 0) + 1);
  }
  const out = new Map();
  for (const [k, spellings] of counts) {
    const best = [...spellings.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))[0][0];
    out.set(k, { display: best, variants: [...spellings.keys()] });
  }
  return out;
}

export function splitLine(line) {
  const out = []; let cur = "", q = false;
  for (let i = 0; i < line.length; i++) {
    const c = line[i];
    if (q) { if (c === '"' && line[i+1] === '"') { cur += '"'; i++; } else if (c === '"') q = false; else cur += c; }
    else if (c === '"') q = true;
    else if (c === ",") { out.push(cur); cur = ""; }
    else cur += c;
  }
  out.push(cur); return out;
}

export function parseCSV(text) {
  if (text.charCodeAt(0) === 0xfeff) text = text.slice(1);
  const lines = text.split(/\r?\n/).filter(l => l.trim() !== "");
  const headers = splitLine(lines[0]).map(h => h.trim());
  const rows = lines.slice(1).map(line => {
    const cells = splitLine(line);
    const o = Object.fromEntries(headers.map((h, i) => [h, (cells[i] ?? "").trim()]));
    o.__cells = cells.length;
    return o;
  });
  return { headers, rows };
}

export function audit({ headers, rows }, expectedMinRows) {
  const p = [], n = headers.length;
  if (n === 1) p.push("only 1 column parsed — wrong delimiter?");
  rows.forEach((r, i) => { if (r.__cells !== n) p.push(`row ${i}: ${r.__cells} cells, header declares ${n}`); });
  if (expectedMinRows != null && rows.length < expectedMinRows)
    p.push(`got ${rows.length} rows, expected ≥${expectedMinRows} — truncated?`);
  for (const key of Object.values(C))
    if (!headers.includes(key)) p.push(`missing expected column: "${key}"`);
  return p;
}

// 4,325 history rows -> one CURRENT position per product x location x brand.
//
// DUPLICATES: 13 position-days in this file have TWO rows with the same
// product+brand+location+date and different stock (biggest gap: 619 units).
// A plain `>` comparison keeps whichever the file listed first, so the answer
// depends on row order — a silent coin flip between two real readings.
//
// Resolved conservatively: on a tie, keep the LOWER stock. The cost is
// asymmetric — an under-read causes a spurious reorder (you get extra
// inventory), an over-read causes a stockout (the thing this tool exists to
// prevent). Failing toward "flag it" is the cheap direction to be wrong in.
// Every conflict is recorded so it can be shown, not swallowed.
// Two passes on purpose. A single pass that compares against "whatever I've
// seen so far" reports conflicts on dates that a later row supersedes — it
// over-counted 4 when only 2 positions are actually uncertain today.
export function toSnapshot(rows) {
  // GUARD (spelling): fold casing/whitespace variants onto one canonical
  // spelling BEFORE keying, or " haryana " becomes a second location.
  const KEYED = [C.product, C.location, C.brand, C.storage];
  const canon = Object.fromEntries(KEYED.map(c => [c, canonical(rows.map(r => r[c]))]));
  const merged = [];
  for (const c of KEYED)
    for (const [, v] of canon[c])
      if (v.variants.length > 1) merged.push({ column: c, kept: v.display, folded: v.variants });

  rows = rows.map(r => {
    const o = { ...r };
    for (const c of KEYED) o[c] = canon[c].get(normKey(r[c]))?.display ?? r[c];
    return o;
  });

  const keyOf = r => `${normKey(r[C.product])}|||${normKey(r[C.location])}|||${normKey(r[C.brand])}`;

  // Pass 1 — the current date for each position.
  const maxDate = new Map();
  for (const r of rows) {
    const k = keyOf(r), d = r[C.date];
    if (!maxDate.has(k) || d > maxDate.get(k)) maxDate.set(k, d);
  }

  // Pass 2 — resolve only among rows ON that date.
  const chosen = new Map(), seen = new Map();
  for (const r of rows) {
    const k = keyOf(r);
    if (r[C.date] !== maxDate.get(k)) continue;
    (seen.get(k) ?? seen.set(k, []).get(k)).push(r);
  }

  const conflicts = [];
  for (const [k, candidates] of seen) {
    if (candidates.length === 1) { chosen.set(k, candidates[0]); continue; }

    const readings = candidates.map(r => num(r[C.stock])).filter(v => v !== null);
    const distinct = [...new Set(readings)];
    if (distinct.length <= 1) { chosen.set(k, candidates[0]); continue; }

    // Conservative: keep the LOWEST stock. The cost is asymmetric — an
    // under-read causes a spurious reorder (extra inventory), an over-read
    // causes a stockout, which is the thing this tool exists to prevent.
    const pick = candidates.reduce((a, b) =>
      (num(b[C.stock]) ?? Infinity) < (num(a[C.stock]) ?? Infinity) ? b : a);
    chosen.set(k, pick);
    conflicts.push({ ...pick,
      _reason: `${distinct.length} readings for ${pick[C.date]} (${distinct.sort((x, y) => x - y).join(", ")}) ` +
               `— using the lowest` });
  }

  const out = [...chosen.values()];
  out.conflicts = conflicts;
  out.merged = merged;   // spelling variants folded — surfaced, not swallowed   // carried alongside so callers can surface it
  return out;
}

// Strict: only a clean, finite, non-negative number counts. parseFloat("12abc")
// returns 12, which would silently accept corrupt input — so reject anything
// that isn't fully numeric.
export function num(v) {
  if (v === null || v === undefined) return null;
  const s = String(v).trim();
  if (s === "" || !/^-?\d+(\.\d+)?$/.test(s)) return null;
  const n = parseFloat(s);
  return Number.isFinite(n) ? n : null;
}

export function reorderList(snapshot) {
  const flagged = [], unknown = [];
  for (const r of snapshot) {
    const stock = num(r[C.stock]), threshold = num(r[C.threshold]);
    if (stock === null || threshold === null) {
      unknown.push({ ...r, _reason:
        stock === null && threshold === null ? `stock "${r[C.stock]}" and threshold "${r[C.threshold]}" both unreadable`
        : stock === null ? `stock "${r[C.stock]}" is not a number`
        : `threshold "${r[C.threshold]}" is not a number` });
      continue;
    }
    if (stock < 0 || threshold < 0) {
      unknown.push({ ...r, _reason: `negative value (stock ${stock}, threshold ${threshold})` });
      continue;
    }
    if (stock < threshold)
      flagged.push({ ...r, _gap: threshold - stock, _severity: (threshold - stock) / threshold });
  }
  // Deterministic order. Severity alone leaves ties — 4 items sit at exactly
  // 1.0 (stock is zero), and an unstable tie-break makes the top-20 list
  // reshuffle between runs. Break ties by absolute shortfall (needing 95 units
  // is worse than needing 41), then by key so the result is fully reproducible.
  const sortKey = r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`;
  flagged.sort((a, b) =>
    b._severity - a._severity ||
    b._gap - a._gap ||
    sortKey(a).localeCompare(sortKey(b)));
  return { flagged, unknown };
}

// ── location filter ──────────────────────────────────────────────────
export const ALL_LOCATIONS = "__all__";

export function byLocation(rows, location) {
  if (!location || location === ALL_LOCATIONS) return rows;
  const want = normKey(location);          // GUARD (spelling)
  return rows.filter(r => normKey(r[C.location]) === want);
}

// Locations ranked by how many problems each has, so the dropdown itself
// tells her where to look — not just alphabetical noise.
export function locationCounts(flagged, snapshot) {
  const counts = new Map();
  for (const r of snapshot) counts.set(r[C.location], { location: r[C.location], flagged: 0, tracked: 0 });
  for (const r of snapshot) counts.get(r[C.location]).tracked++;
  for (const r of flagged) counts.get(r[C.location]).flagged++;
  return [...counts.values()].sort((a, b) => b.flagged - a.flagged || a.location.localeCompare(b.location));
}

// ── group by storage condition ───────────────────────────────────────
// This column is an ORDERED CATEGORY, and the order is not alphabetical —
// sorted A-Z, "Ambient" (least urgent) would come first. So the order is
// declared here, on purpose, the same way a priority column has to be.
//
// HONEST CAVEAT: the source mixes two concepts in one column. Frozen /
// Refrigerated / Ambient are storage temperatures; Tetra Pack / Polythene
// Packet are PACKAGING (they only ever appear on Milk). The ranking below
// treats polythene-packet milk as cold-chain and tetra-pack as shelf-stable,
// which is a declared domain assumption — NOT something the data proves.
// If FreshRoute says otherwise, change this array, not the code.
export const STORAGE_ORDER = [
  "Frozen",            // fails fastest if the chain breaks
  "Refrigerated",
  "Polythene Packet",  // fresh milk in a bag — assumed to need cold
  "Tetra Pack",        // assumed aseptic / shelf-stable
  "Ambient",           // shelf-stable
];

export const STORAGE_IS_PACKAGING = new Set(["Tetra Pack", "Polythene Packet"]);

export function storageRank(value) {
  const i = STORAGE_ORDER.findIndex(s => normKey(s) === normKey(value));
  return i === -1 ? STORAGE_ORDER.length : i;   // unknown values sort last, never first
}

// Group rows under their storage value, in declared urgency order.
// Unknown values still get a group — they're surfaced, not dropped.
export function groupByStorage(rows) {
  const groups = new Map();
  for (const r of rows) {
    const key = r[C.storage] || "(not recorded)";
    if (!groups.has(key)) groups.set(key, { storage: key, rows: [], unknown: storageRank(key) === STORAGE_ORDER.length });
    groups.get(key).rows.push(r);
  }
  return [...groups.values()].sort((a, b) =>
    storageRank(a.storage) - storageRank(b.storage) || a.storage.localeCompare(b.storage));
}

// ── Morning brief: what a coordinator needs without reading 600 rows ──
// Spots the trends a human would have to scan for. Every sentence is
// computed from the data — nothing here is generated prose, so it can't
// hallucinate a number. The LLM hand-off (briefPrompt) is for the part a
// model is genuinely better at: judgement, not arithmetic.
export function morningBrief(snapshot, flagged, expiring, review, conflicts = []) {
  const lines = [];
  const pct = (n, d) => d ? Math.round((n / d) * 100) : 0;

  // 1. The headline: how bad is today, in one number a person can hold.
  const out = flagged.filter(r => num(r[C.stock]) === 0);
  const critical = flagged.filter(r => r._severity > 0.75);
  lines.push(`${flagged.length} of ${snapshot.length} items are below their reorder level (${pct(flagged.length, snapshot.length)}%).` +
    (out.length ? ` ${out.length} ${out.length === 1 ? "is" : "are"} completely out of stock.` : ""));
  if (critical.length) lines.push(`${critical.length} ${critical.length === 1 ? "is" : "are"} at or below a quarter of their minimum — those are the ones that bite first.`);

  // 2. Concentration: is this everywhere, or one place?
  const byLoc = {};
  for (const r of flagged) byLoc[r[C.location]] = (byLoc[r[C.location]] || 0) + 1;
  const locs = Object.entries(byLoc).sort((a, b) => b[1] - a[1]);
  const tracked = {};
  for (const r of snapshot) tracked[r[C.location]] = (tracked[r[C.location]] || 0) + 1;
  // Only meaningful when there's more than one location in scope — filtered
  // to a single site this compared that site against itself ("33% against a
  // 33% average") and reported "spread across 1 locations".
  if (locs.length > 1) {
    const [worstLoc, worstN] = locs[0];
    const rate = pct(worstN, tracked[worstLoc]);
    const avg = pct(flagged.length, snapshot.length);
    lines.push(`${worstLoc} is worst — ${worstN} of its ${tracked[worstLoc]} items short (${rate}%)` +
      (rate > avg ? `, against a ${avg}% average across ${locs.length} locations.` : `.`) +
      (locs.length > 2 ? ` Shortages appear in ${locs.length} locations, so this isn't one bad site.` : ``));
  }

  // 3. Category: which product is systematically short, not just unlucky?
  const byProd = {}, prodTotal = {};
  for (const r of snapshot) prodTotal[r[C.product]] = (prodTotal[r[C.product]] || 0) + 1;
  for (const r of flagged) byProd[r[C.product]] = (byProd[r[C.product]] || 0) + 1;
  const prods = Object.entries(byProd)
    .map(([p, n]) => ({ product: p, n, total: prodTotal[p], rate: n / prodTotal[p] }))
    .sort((a, b) => b.rate - a.rate);
  if (prods.length) {
    const w = prods[0];
    lines.push(`${w.product} is the weakest line — ${w.n} of ${w.total} items short (${pct(w.n, w.total)}%). ` +
      `That's a supply pattern, not one bad location.`);
  }

  // 4. Cold chain: does the shortage sit where it's expensive?
  const cold = flagged.filter(r => ["Frozen", "Refrigerated"].includes(r[C.storage])).length;
  if (cold) lines.push(`${cold} of the ${flagged.length} shortages (${pct(cold, flagged.length)}%) are frozen or refrigerated — restocking those needs cold transport, so they need longer lead time.`);

  // 5. Expiry and anything the tool couldn't read.
  if (expiring.length) lines.push(`Separately, ${expiring.length} item${expiring.length === 1 ? " expires" : "s expire"} within 14 days.`);
  if (review.length) lines.push(`${review.length} row${review.length === 1 ? "" : "s"} couldn't be read and are excluded — check them before trusting the totals.`);
  // Conflicts arrive unfiltered — scope them to what's actually on screen, or
  // a location filter shows a count for positions somewhere else entirely.
  const inScope = new Set(snapshot.map(r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`));
  const shown = conflicts.filter(c => inScope.has(`${c[C.product]}|${c[C.brand]}|${c[C.location]}`));
  if (shown.length) lines.push(`${shown.length} item${shown.length === 1 ? " has" : "s have"} conflicting stock readings for the same day; the lower figure was used.`);

  return lines;
}

// A structured hand-off for the questions a model answers better than a
// formula: what to do first, what to say to a supplier, what pattern to
// investigate. Facts computed here; judgement left to the model.
export function briefPrompt(brief, flagged, asOfLabel) {
  const top = flagged.slice(0, 15).map(r =>
    `- ${r[C.product]} (${r[C.brand]}) at ${r[C.location]}: ${r[C.stock]} on hand, ` +
    `minimum ${Math.round(num(r[C.threshold]))}, reorder ${Math.round(num(r[C.reorder]))}, ${r[C.storage]}`);

  return [
    `I'm an inventory coordinator at a dairy distributor. Here is this morning's stock position${asOfLabel ? ` (as of ${asOfLabel})` : ""}.`,
    ``,
    `SUMMARY`,
    ...brief.map(l => `- ${l}`),
    ``,
    `THE ${top.length} MOST URGENT SHORTAGES`,
    ...top,
    ``,
    `Please:`,
    `1. Tell me the three things to action first and why, in that order.`,
    `2. Draft a short supplier message for the single most urgent one.`,
    `3. Name any pattern here worth investigating that the numbers alone don't explain.`,
    ``,
    `Be concise. If the data doesn't support a conclusion, say so rather than guessing.`,
  ].join("\n");
}

// Split a ranked list into what a cap shows, what it must show anyway, and
// what it may legitimately hide. Pure, so the invariant is testable:
//
//   every conflicted row appears in `shown` OR `exempt` — never in `hidden`.
//
// The ranking is untouched. An exemption is not a promotion: these rows are
// not claimed to be more urgent, only unmissable. Blending "how short" with
// "how soon it expires" into one score is a composite the data can't support.
export function capWithExemptions(rows, cap, exemptCap = 10) {
  const shown = rows.slice(0, cap);
  const rest = rows.slice(cap);
  const conflicts = rest.filter(r => r._expiresInDays !== undefined);
  return {
    shown,
    exempt: conflicts.slice(0, exemptCap),
    exemptOverflow: Math.max(0, conflicts.length - exemptCap),
    hiddenCount: rest.length,
  };
}

// ── Order by supplier ────────────────────────────────────────────────
// The reorder list is ranked for READING. This regroups it for DOING:
// she doesn't action 113 items, she makes 10 phone calls. The unit of a
// phone call is a brand.
//
// It also carries the one contradiction the app previously left unjoined.
// An item can be below threshold (the reorder panel says order more) AND
// expiring within the window (the expiry panel says it's about to go bad).
// Both facts were on screen; nothing connected them — and the moment she's
// most likely to act on it is reading down a list to a supplier.
//
// The conflict is FLAGGED, never resolved. Low stock plus imminent expiry
// has at least three readings: it sold well and needs restocking, it's low
// *because* it was written down for expiry, or the batch is old and
// reordering compounds the problem. The data cannot distinguish them.
export function bySupplier(flagged, expiring) {
  const key = r => `${normKey(r[C.product])}|${normKey(r[C.brand])}|${normKey(r[C.location])}`;
  const expiryDays = new Map(expiring.map(r => [key(r), r._daysLeft]));

  const groups = new Map();
  for (const r of flagged) {
    const b = r[C.brand];
    if (!groups.has(b)) groups.set(b, { supplier: b, rows: [], units: 0, sites: new Set(), conflicts: 0 });
    const g = groups.get(b);
    const days = expiryDays.get(key(r));
    g.rows.push(days === undefined ? r : { ...r, _expiresInDays: days });
    g.units += num(r[C.reorder]) ?? 0;
    g.sites.add(r[C.location]);
    if (days !== undefined) g.conflicts++;
  }

  return [...groups.values()]
    .map(g => ({ ...g, sites: g.sites.size, units: Math.round(g.units) }))
    // Conflicts first — a supplier where something shouldn't be reordered is
    // the call to make carefully, not the biggest one. Then by workload.
    .sort((a, b) => (b.conflicts > 0) - (a.conflicts > 0) || b.rows.length - a.rows.length
                    || a.supplier.localeCompare(b.supplier));
}

// Plain text for an email or a phone call. Conflicts are called out inline,
// not footnoted — she reads this aloud.
export function supplierOrderText(group, asOf) {
  const lines = [
    `Reorder request — ${group.supplier}${asOf ? ` (as of ${asOf})` : ""}`,
    `${group.rows.length} item${group.rows.length === 1 ? "" : "s"} across ${group.sites} location${group.sites === 1 ? "" : "s"}`,
    "",
  ];
  if (group.conflicts)
    lines.push(`** ${group.conflicts} item${group.conflicts === 1 ? " is" : "s are"} also expiring within ${EXPIRY_WINDOW_DAYS} days — confirm before ordering **`, "");
  for (const r of group.rows) {
    lines.push(`${r[C.product]} — ${r[C.location]}: ${r[C.stock]} on hand (min ${Math.round(num(r[C.threshold]))}), order ${Math.round(num(r[C.reorder]))}` +
      (r._expiresInDays !== undefined ? `   << expires in ${r._expiresInDays} days — confirm` : ""));
  }
  lines.push("", `Total: ${group.units} units`);
  return lines.join("\n");
}

// ── CSV export ───────────────────────────────────────────────────────
// We spent this whole build proving that a naive join(",") corrupts any
// field containing a comma. Don't ship the bug we came here to avoid:
// quote anything with a comma, quote, or newline, and double inner quotes
// (RFC 4180). "Bloom & Sons, LLC" must survive the round trip.
export function csvCell(value) {
  const s = String(value ?? "");
  return /[",\n\r]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

export function toCSV(rows, columns) {
  const head = columns.map(c => csvCell(c.label)).join(",");
  const body = rows.map(r => columns.map(c => csvCell(c.get(r))).join(","));
  return [head, ...body].join("\r\n") + "\r\n";   // CRLF: Excel's expectation
}

// The supplier's reorder quantity is a FIELD IN THE FILE, not a calculation —
// so nothing makes it close the gap it sits next to, and on this export it
// often doesn't: order exactly what the column says and 12 of 113 items are
// still below their minimum, one by 56 units. The column was labelled "Order"
// under a heading that reads "Reorder now", which is the app telling a
// coordinator to under-order in its own voice.
//
// Returns units still short AFTER ordering the stated quantity:
//   null -> can't tell (unreadable quantity or no gap recorded)
//   0    -> the stated quantity covers it
//   n    -> ordering this leaves you n units below minimum
export function orderShortfall(row) {
  const qty = num(row[C.reorder]);
  const gap = row._gap;
  if (qty === null || gap === null || gap === undefined) return null;
  return Math.max(0, Math.round(gap - qty));
}

export const ORDER_COLUMNS = [
  { label: "Product",        get: r => r[C.product] },
  { label: "Brand",          get: r => r[C.brand] },
  { label: "Location",       get: r => r[C.location] },
  { label: "On hand",        get: r => r[C.stock] },
  { label: "Min threshold",  get: r => r[C.threshold] },
  { label: "Order quantity", get: r => r[C.reorder] },
  { label: "Storage",        get: r => r[C.storage] },
  { label: "Short by",       get: r => Math.round(r._gap ?? 0) },
];

export function expiringSoon(snapshot, today, windowDays = EXPIRY_WINDOW_DAYS) {
  const cutoff = new Date(today); cutoff.setDate(cutoff.getDate() + windowDays);
  const soon = [], unparseable = [];
  for (const r of snapshot) {
    const raw = r[C.expiry];
    const d = new Date(raw);
    if (!raw || isNaN(d.getTime())) {
      unparseable.push({ ...r, _reason: `unreadable expiry date "${raw}"` });
      continue;
    }
    if (d >= today && d <= cutoff)
      soon.push({ ...r, _daysLeft: Math.ceil((d - today) / 86400000) });
  }
  soon.sort((a, b) => a._daysLeft - b._daysLeft);
  return { soon, unparseable };
}
