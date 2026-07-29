# Morning triage — FreshRoute inventory

An Inventory Coordinator's morning board. Reads a real 4,325-row dairy
distribution export and shows the handful of items that need action today,
instead of every row.

**This is the live-demo copy.** The dataset ([CC0, public
domain](https://www.kaggle.com/datasets/suraj520/dairy-goods-sales-dataset))
is committed right in the repo so the page just works.

## Run it

**Live:** https://doble196.github.io/freshroute-demo/

Or locally:

```bash
python3 -m http.server 8100     # then open http://localhost:8100
```

One command, no install, no build step.

## What you should see

```
113 below reorder threshold · 13 expiring within 14 days · 0 need review · tracking 600 items across 15 locations
```

If you see `FAILED TO LOAD`, `setup.sh` hasn't run or didn't finish.

## What it does with the data

**4,325 rows → 600 items → 113 flagged → 20 shown → all 113 exportable.**

- **Snapshot.** The file is a *transaction log*, not a stock snapshot — 4,325
  historical rows for 10 products. Taking the latest row per **product × location
  × brand** gives 600 real current items. Summing locations would hide a
  stockout in one place behind surplus in another.
- **Reorder now.** Stock below its minimum threshold, ranked by how *deep* below
  (`gap / threshold`), so 1-of-90 outranks 60-of-68 — the item that's actually
  out beats the one that's merely low.
- **Expiring soon.** Within 14 days. **Labeled DEMO on screen**, because 100% of
  this export's rows already expired — it evaluates against the file's last
  recorded day (2022-12-28) and says so. The reorder panel uses live data.
- **Needs review.** Anything with an unreadable stock, threshold or date is shown
  here, never silently dropped.
- **Filter and group.** By location (dropdown ranked by problem count, so the
  control tells you where to start) and by storage condition (in declared urgency
  order — alphabetically, `Ambient`, the *least* urgent, would lead).
- **Export.** All flagged items in scope as CSV, RFC 4180 quoted, filename scoped
  to the current filter.

## Checking it yourself

```bash
node review-test.js             # 57 tests — mutation tests, partition invariants, a skip guard
node test-data/guards-test.js   # 20 tests — planned broken rows: blanks, types, spelling, repeats
python3 verify.py               # cross-checks the whole pipeline against an independent
                                # pandas implementation; exits nonzero on any disagreement
```

There's a fourth layer for the part these can't see: `ui-check.js`, pasted into
the browser console, clicks every control and asserts something visible changes.
Three real bugs this week lived only in the render layer — invisible to every
passing logic test.

`verify.py` deliberately uses *different* techniques from the JS where there's a
choice (`sort_values` + `drop_duplicates` vs a Map, stdlib `csv.writer` vs
hand-rolled quoting). Two unrelated routes agreeing is evidence; one route
agreeing with a copy of itself isn't.

## Known limits

- The data is **not** what the brief describes: 10 products in Indian states with
  INR revenue, not ~80 products in the US Midwest. Built to the file, labeled
  honestly.
- The expiry feature can't run live on this export — see DEMO above.
- No cost column, so the app can detect *what* needs attention, never explain
  *why* something is unprofitable.

Files: [`logic.js`](logic.js) is all the data logic (imported by both the app and
the tests), [`script.js`](script.js) is DOM and render only.
