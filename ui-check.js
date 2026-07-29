// Click every control. Assert the user sees something change.
//
// This exists because three real bugs this week were invisible to 57 passing
// logic tests and obvious within seconds of clicking:
//
//   1. STATE reassigned with a bare literal — dropped the `grouped` flag, so
//      the toggle read "checked" and the view was flat.
//   2. The expiry conflict flag existed only in the supplier view. The default
//      screen — the one she lands on — showed none.
//   3. "Copy order" failed on every click and told the user to open devtools.
//
// Every one of those is a RENDER bug. review-test.js exercises logic and never
// looks at the screen; verify.py cross-checks numbers and never looks at the
// screen. This is the cheapest possible bridge between "the logic is right"
// and "the product works".
//
// It is deliberately NOT a snapshot test. It asserts only that a control
// produces a visible effect — the weakest useful claim, and the one that
// catches a control wired to nothing.
//
// Run: open the app, paste this file into the console, call uiCheck().

async function uiCheck() {
  const $ = id => document.getElementById(id);
  const wait = (ms = 120) => new Promise(r => setTimeout(r, ms));
  const results = [];
  const check = (name, before, after, note = "") => {
    const changed = JSON.stringify(before) !== JSON.stringify(after);
    results.push({ name, ok: changed, note });
    console.log(`${changed ? "PASS" : "FAIL"}  ${name}${note ? `  — ${note}` : ""}`);
    if (!changed) console.log("      nothing visibly changed:", before);
  };

  // A cheap fingerprint of what's on screen. If a control does something, this moves.
  const screen = () => ({
    summary: $("summary").textContent,
    scope: $("scope").textContent,
    reorderRows: document.querySelectorAll("#reorder tbody tr").length,
    reorderShape: document.querySelectorAll(".supplier").length + "|" + document.querySelectorAll(".group").length,
    briefFirstLine: document.querySelector("#brief li")?.textContent ?? "",
    conflictMarkers: document.querySelectorAll("#reorder .warn-tag").length,
    exportLabel: $("export").textContent,
  });

  console.log("=== interaction check ===");

  // Reset to a known baseline FIRST. Without this the check inherits whatever
  // the previous run left behind — and it caught itself doing exactly that:
  // run 1 ends in supplier view, so run 2's "view toggle switches to supplier"
  // passed trivially because it was already there. A check with no known
  // starting state can pass for the wrong reason, which is the disease this
  // whole file exists to cure.
  // Dispatch on EVERY control, not just one. Setting .value without firing
  // that control's own handler leaves app state untouched — the first version
  // set viewToggle.value and dispatched only on location, so STATE.view never
  // moved and the "reset" reset nothing.
  for (const [el, set] of [[$("location"), e => e.value = e.options[0].value],
                           [$("viewToggle"), e => e.value = "urgency"],
                           [$("groupToggle"), e => e.checked = true]]) {
    set(el);
    el.dispatchEvent(new Event("change"));
    await wait(60);
  }
  const baseline = screen();
  if (baseline.reorderShape.split("|")[0] !== "0") {
    console.log("FAIL  could not reach a known baseline — supplier cards still rendered");
    return { passed: 0, total: 1, failed: ["baseline reset"] };
  }
  console.log(`baseline: ${baseline.reorderRows} rows, ${baseline.summary.slice(0, 40)}…`);

  // 1. location filter
  const loc = $("location");
  let before = screen();
  loc.value = loc.options[1].value; loc.dispatchEvent(new Event("change")); await wait();
  check("location filter changes the view", before, screen(), `→ ${loc.value}`);

  // 2. the filtered banner must appear AND say what's hidden
  results.push({ name: "filtered banner names the hidden count",
    ok: /\d+ flagged item/.test($("scope").textContent), note: $("scope").textContent.trim().slice(0, 48) });
  console.log(`${/\d+ flagged item/.test($("scope").textContent) ? "PASS" : "FAIL"}  filtered banner names the hidden count`);

  // 3. clear button restores
  before = screen();
  $("clear")?.click(); await wait();
  check("clear-filter button restores all locations", before, screen());

  // 4. view toggle
  const view = $("viewToggle");
  before = screen();
  view.value = "supplier"; view.dispatchEvent(new Event("change")); await wait();
  check("view toggle switches to supplier cards", before, screen(),
        `${document.querySelectorAll(".supplier").length} cards`);

  // 5. copy order — the one that was silently broken
  const copyBtn = document.querySelector(".copyOrder");
  const labelBefore = copyBtn?.textContent;
  copyBtn?.click(); await wait(400);
  const gotFeedback = copyBtn && (copyBtn.textContent !== labelBefore || document.querySelector(".copybox"));
  results.push({ name: "copy-order produces visible feedback", ok: !!gotFeedback,
                 note: copyBtn?.textContent });
  console.log(`${gotFeedback ? "PASS" : "FAIL"}  copy-order produces visible feedback  — ${copyBtn?.textContent}`);
  results.push({ name: "copy-order never sends the user to the console",
                 ok: !/console/i.test(copyBtn?.textContent ?? "") });
  console.log(`${!/console/i.test(copyBtn?.textContent ?? "") ? "PASS" : "FAIL"}  copy-order never sends the user to the console`);
  document.querySelector(".copybox-close")?.click();

  // 6. back to urgency, then the group toggle
  view.value = "urgency"; view.dispatchEvent(new Event("change")); await wait();
  const grp = $("groupToggle");
  before = screen();
  grp.checked = !grp.checked; grp.dispatchEvent(new Event("change")); await wait();
  check("group-by-storage toggle changes the layout", before, screen());
  grp.checked = true; grp.dispatchEvent(new Event("change")); await wait();

  // 7. copy brief
  const brief = $("copyBrief");
  const briefLabel = brief.textContent;
  brief.click(); await wait(400);
  const briefFeedback = brief.textContent !== briefLabel || document.querySelector(".copybox");
  results.push({ name: "copy-brief produces visible feedback", ok: !!briefFeedback, note: brief.textContent });
  console.log(`${briefFeedback ? "PASS" : "FAIL"}  copy-brief produces visible feedback  — ${brief.textContent}`);
  document.querySelector(".copybox-close")?.click();

  // 8. the conflict flag must exist in EVERY view — bug #2 above
  const seen = {};
  for (const [label, set] of [["urgency-grouped", () => { view.value = "urgency"; grp.checked = true; }],
                              ["urgency-flat",    () => { view.value = "urgency"; grp.checked = false; }],
                              ["supplier",        () => { view.value = "supplier"; }]]) {
    set(); view.dispatchEvent(new Event("change")); grp.dispatchEvent(new Event("change")); await wait();
    seen[label] = document.querySelectorAll("#reorder .warn-tag").length;
  }
  const allViewsFlag = Object.values(seen).every(n => n > 0);
  results.push({ name: "expiry conflicts are visible in every view", ok: allViewsFlag, note: JSON.stringify(seen) });
  console.log(`${allViewsFlag ? "PASS" : "FAIL"}  expiry conflicts are visible in every view  — ${JSON.stringify(seen)}`);

  const failed = results.filter(r => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  if (failed.length) console.log("FAILED:", failed.map(f => f.name));
  return { passed: results.length - failed.length, total: results.length, failed: failed.map(f => f.name) };
}
