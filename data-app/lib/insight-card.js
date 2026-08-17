/* insight-card.js — the recurring-critical-flag insight, as a pure function.
 *
 * The card says two sentences to a restaurant operator:
 *   1. the claim  — "this exact critical violation keeps appearing on YOUR
 *      record, and measured across the city's paired inspections it is the
 *      one that most often survives to the re-inspection";
 *   2. the limit — the rate measures inspection DAYS, not the kitchen's
 *      every day, phrased so the caveat aims the insight instead of
 *      undermining it (preparation, not cleanliness, is the claim).
 *
 * Refusals are first-class: when the record has no repeated critical code,
 * or the repeated code has no measured rate, the function says WHY it is
 * not rendering instead of stretching a weaker number into a card. A card
 * this opinionated must be able to decline.
 *
 * Pure on purpose (no fetch, no DOM): the page, a future server route, and
 * the test in analysis/insight_card_test.cjs all call this same function.
 */
(function (factory) {
  // Dual-home: CJS gets module.exports; everything else (browser classic
  // script, node ESM via require(esm)) gets globalThis.InsightCard.
  const api = factory();
  if (typeof module === "object" && module && module.exports) module.exports = api;
  else globalThis.InsightCard = api;
})(function () {
  "use strict";

  /**
   * Build the recurring-critical-flag insight for one restaurant record.
   *
   * @param {Array<[string, Array<object>]>} byDateEntries — [isoDate, rows[]]
   *        pairs, one per inspection date (any order; sorted here). Rows are
   *        the city's citation rows: violation_code / violation_description /
   *        critical_flag.
   * @param {object} persist — the generated PERSIST table from the page:
   *        { pairs, minCited, codes: { CODE: {rate, lo, hi, n} } }.
   * @returns {{card: object}|{none: string}} — a renderable card, or the
   *        reason there is none: "one-inspection-record" | "no-repeat-critical"
   *        | "no-measured-rate".
   */
  function buildRecurringFlagInsight(byDateEntries, persist) {
    const dates = [...byDateEntries].sort((a, b) => (a[0] < b[0] ? 1 : -1));
    if (dates.length < 2) return { none: "one-inspection-record" };

    // Which critical codes appear on which DISTINCT inspection dates. A code
    // cited twice within one visit is one finding, not a pattern.
    const seenOn = new Map(); // code -> { dates:Set, desc }
    for (const [date, rows] of dates) {
      for (const r of rows) {
        if (!r.violation_code || r.critical_flag !== "Critical") continue;
        let e = seenOn.get(r.violation_code);
        if (!e) seenOn.set(r.violation_code, (e = { dates: new Set(), desc: r.violation_description || "" }));
        e.dates.add(date);
        if (!e.desc && r.violation_description) e.desc = r.violation_description;
      }
    }

    const latestDate = dates[0][0];
    const repeats = [...seenOn.entries()].filter(([, e]) => e.dates.size >= 2);
    if (!repeats.length) return { none: "no-repeat-critical" };

    // Rank repeated codes by their MEASURED persistence; codes without a
    // measured rate are never guessed at (same law as the triage list).
    const measured = repeats
      .map(([code, e]) => ({ code, e, p: persist.codes[code] }))
      .filter((c) => c.p)
      .sort((a, b) => b.p.rate - a.p.rate);
    if (!measured.length) return { none: "no-measured-rate" };

    const top = measured[0];
    const pct = Math.round(top.p.rate * 100);
    const lo = Math.round(top.p.lo * 100);
    const hi = Math.round(top.p.hi * 100);
    const onLatest = top.e.dates.has(latestDate);
    const timesCited = top.e.dates.size;
    const totalVisits = dates.length;

    const sentence1 =
      `${top.e.desc ? top.e.desc.replace(/\s+/g, " ").trim() : "This violation"} ` +
      `(${top.code} — a critical flag) was cited on ${timesCited} of your last ` +
      `${totalVisits} inspections${onLatest ? ", including the most recent one" : ""}, ` +
      `and across ${persist.pairs.toLocaleString("en-US")} paired NYC inspections this exact ` +
      `code was still there at the re-inspection ${pct}% of the time ` +
      `(n=${top.p.n.toLocaleString("en-US")}, 95% CI ${lo}–${hi}%) — the item on your ` +
      `record most worth fixing before the next visit.`;

    const sentence2 =
      `That ${pct}% measures what inspectors keep finding on inspection days — not what ` +
      `your kitchen looks like every day — and that is exactly what makes it useful: ` +
      `this is the item inspectors reliably re-check and rarely see resolved, so it is ` +
      `where preparation ahead of the next visit pays off most.`;

    return {
      card: {
        code: top.code,
        description: top.e.desc,
        timesCited,
        totalVisits,
        onLatest,
        rate: top.p.rate,
        lo: top.p.lo,
        hi: top.p.hi,
        n: top.p.n,
        pairs: persist.pairs,
        sentence1,
        sentence2,
      },
    };
  }

  return { buildRecurringFlagInsight };
});
