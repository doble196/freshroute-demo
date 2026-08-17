// insight_card_test.cjs — the recurring-critical-flag card's contract.
// Run: node analysis/insight_card_test.cjs   (same convention as agrade_flag_test.cjs)
"use strict";
const assert = require("node:assert");
require("../data-app/lib/insight-card.js"); // repo is type:module → lib lands on globalThis
const { buildRecurringFlagInsight } = globalThis.InsightCard;

// A miniature PERSIST in the generated table's exact shape (04L's real numbers).
const persist = {
  pairs: 6960,
  minCited: 50,
  codes: {
    "04L": { rate: 0.4103, lo: 0.3898, hi: 0.4312, n: 2169 },
    "10F": { rate: 0.5344, lo: 0.5182, hi: 0.5506, n: 3645 },
  },
};

const row = (code, critical, desc) => ({
  violation_code: code,
  critical_flag: critical ? "Critical" : "Not Critical",
  violation_description: desc,
});

// 1. A critical code on two distinct dates renders the card with the REAL numbers.
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("04L", true, "Evidence of mice or live mice present"), row("02G", true, "x")]],
      ["2026-03-10", [row("04L", true, "Evidence of mice or live mice present")]],
    ],
    persist,
  );
  assert.ok(out.card, "expected a card");
  assert.strictEqual(out.card.code, "04L");
  assert.strictEqual(out.card.timesCited, 2);
  assert.ok(out.card.onLatest);
  assert.match(out.card.sentence1, /41% of the time/);
  assert.match(out.card.sentence1, /n=2,169/);
  assert.match(out.card.sentence1, /95% CI 39–43%/);
  assert.match(out.card.sentence2, /inspection days/);
  assert.match(out.card.sentence2, /not what your kitchen looks like every day/);
}

// 2. Two repeated criticals: the MEASURED-higher rate wins (10F over 04L).
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("04L", true, "mice"), row("10F", true, "non-food surface improperly constructed")]],
      ["2026-03-10", [row("04L", true, "mice"), row("10F", true, "non-food surface improperly constructed")]],
    ],
    persist,
  );
  assert.strictEqual(out.card.code, "10F");
}

// 3. One inspection on record: refuse, with the reason.
{
  const out = buildRecurringFlagInsight([["2026-07-01", [row("04L", true, "mice")]]], persist);
  assert.strictEqual(out.none, "one-inspection-record");
}

// 4. No code repeats across dates: refuse.
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("04L", true, "mice")]],
      ["2026-03-10", [row("02G", true, "hot food")]],
    ],
    persist,
  );
  assert.strictEqual(out.none, "no-repeat-critical");
}

// 5. A repeat WITHIN one visit is one finding, not a pattern: refuse.
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("04L", true, "mice"), row("04L", true, "mice")]],
      ["2026-03-10", [row("02G", true, "hot food")]],
    ],
    persist,
  );
  assert.strictEqual(out.none, "no-repeat-critical");
}

// 6. A repeated critical the table never measured: refuse rather than guess.
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("99Z", true, "unmeasured thing")]],
      ["2026-03-10", [row("99Z", true, "unmeasured thing")]],
    ],
    persist,
  );
  assert.strictEqual(out.none, "no-measured-rate");
}

// 7. Non-critical repeats never make a "critical flag" card.
{
  const out = buildRecurringFlagInsight(
    [
      ["2026-07-01", [row("10B", false, "plumbing")]],
      ["2026-03-10", [row("10B", false, "plumbing")]],
    ],
    persist,
  );
  assert.strictEqual(out.none, "no-repeat-critical");
}

console.log("insight_card_test: 7 checks passed");
