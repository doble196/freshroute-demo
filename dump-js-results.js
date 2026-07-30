// Emit the JS pipeline's results as JSON so an independent implementation
// can be diffed against them. Run: node dump-js-results.js > /tmp/js.json

import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";
import { parseCSV, toSnapshot, reorderList, expiringSoon,
         locationCounts, groupByStorage, byLocation, toCSV, ORDER_COLUMNS,
         C, EXPIRY_WINDOW_DAYS } from "./logic.js";

const MAX_ROWS_SHOWN = 20;   // must match script.js

const HERE = dirname(fileURLToPath(import.meta.url));
const parsed = parseCSV(readFileSync(join(HERE, "data/dairy_dataset.csv"), "utf8"));
const snapshot = toSnapshot(parsed.rows);
const { flagged, unknown } = reorderList(snapshot);

const recordDates = snapshot.map(r => new Date(r[C.date])).filter(d => !isNaN(d));
const fileToday = new Date(Math.max(...recordDates));
const { soon, unparseable } = expiringSoon(snapshot, fileToday, EXPIRY_WINDOW_DAYS);

const key = r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`;

console.log(JSON.stringify({
  rows: parsed.rows.length,
  columns: parsed.headers.length,
  positions: snapshot.length,
  flagged: flagged.length,
  expiring: soon.length,
  review: unknown.length + unparseable.length,
  file_today: fileToday.toISOString().slice(0, 10),
  // The sets matter more than the counts — two implementations can both
  // produce 113 and disagree about WHICH 113.
  flagged_keys: flagged.map(key).sort(),
  expiring_keys: soon.map(key).sort(),
  position_keys: snapshot.map(key).sort(),
  by_location: Object.fromEntries(
    locationCounts(flagged, snapshot).map(l => [l.location, l.flagged])),
  by_storage: Object.fromEntries(
    groupByStorage(flagged).map(g => [g.storage, g.rows.length])),
  // Top 5 by severity, in order — checks the RANKING, not just membership.
  top5: flagged.slice(0, 5).map(r => ({ key: key(r), severity: +r._severity.toFixed(6) })),

  // ── UI-derived outputs: what the page actually renders ──
  // The 20 rows the flat view shows, in display order.
  top20: flagged.slice(0, MAX_ROWS_SHOWN).map(key),

  // Group headers in DISPLAY order, with the full count each header states.
  group_order: groupByStorage(flagged).map(g => ({ storage: g.storage, count: g.rows.length })),

  // What each group actually renders after its per-group cap.
  group_shown: Object.fromEntries((() => {
    const groups = groupByStorage(flagged);
    const perGroup = Math.max(5, Math.ceil(MAX_ROWS_SHOWN / groups.length));
    return groups.map(g => [g.storage, g.rows.slice(0, perGroup).map(key)]);
  })()),

  // Every location's filtered view — the filter is only honest if each slice
  // is exactly right, not just if the counts add up.
  per_location: Object.fromEntries(
    locationCounts(flagged, snapshot).map(l => [l.location, byLocation(flagged, l.location).map(key)])),

  // The exported bytes themselves, unfiltered and filtered.
  csv_all: toCSV(flagged, ORDER_COLUMNS),
  csv_haryana: toCSV(byLocation(flagged, "Haryana"), ORDER_COLUMNS),
}, null, 2));
