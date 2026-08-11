# Two working data apps

Both read real data. Both state their own limits on screen rather than in a
footnote. Neither has a build step.

| | What it is | Live |
|---|---|---|
| **NYC DataHub** | Three tools over the city's restaurant-inspection API, fetched in your browser at the moment you search | **[/data-app/](https://doble196.github.io/freshroute-demo/data-app/)** |
| **FreshRoute morning triage** | An inventory coordinator's board over a real 4,325-row dairy export | [/](https://doble196.github.io/freshroute-demo/) |

---

## NYC DataHub — [live](https://doble196.github.io/freshroute-demo/data-app/)

No snapshot, no fixture, no API key. Every number on screen came from the
city's API in that session. A key embedded in a public page is a key you have
given away, and this dataset does not need one.

### [You failed the inspection. What do you fix first?](https://doble196.github.io/freshroute-demo/data-app/operator.html)

For the operator holding a failed inspection. Your open violations ranked by
how often **that exact violation code** was still there at the re-inspection —
measured across 6,960 paired NYC inspections, each rate shipped with its sample
size and 95% interval.

The spread is the product: **53.4% down to 0.8%.** That is the difference
between "fix everything" and "fix these three." It also surfaces something an
operator would otherwise get backwards — the stickiest code on a typical sheet
carries **no critical flag**. The city's flag answers *how dangerous*, not
*will this still be here in 54 days*, and only one of those is the question you
have a re-inspection to answer.

What it refuses to do: **price the fixes.** The city publishes your total and
your violations but never the points each one carried. So it ranks by whether
an item tends to still be there, never by what clearing it saves you.

### [What does that grade in the window actually mean?](https://doble196.github.io/freshroute-demo/data-app/check.html)

For anyone standing outside. Type a restaurant, see what the score is made of —
because a good number and a fixed building are not the same thing. A score of 0
from a re-opening visit gets an amber warning *above* the number.

### [Watch a true chart become a false one](https://doble196.github.io/freshroute-demo/data-app/spin-scrolly.html)

One chart, pinned, spun one display lever at a time. No number changes at any
point — that is the lesson.

### The five ways a live fetch fails

A one-time fetch on page load and a user-triggered fetch are not the same
problem. On load, the request and the page are the same event: if the fetch
dies, nothing renders and the failure is obvious. **Afterwards the page
outlives the request**, so a dead request leaves a live page that is fully
capable of looking correct while being wrong.

Both live tools handle each shape separately, because only one of them looks
like the 503 everybody tests:

| Failure | What the screen says |
|---|---|
| no network | "Could not reach the city's API at all." |
| HTTP error | "The city's API answered with an error: 503 Service Unavailable." |
| malformed body | "The city's API answered, but what came back was not data." |
| wrong-shape 200 | "The city's API rejected the query: *<their message>*" |
| hang | "The city's API did not answer within 12 seconds." (button recovers) |

The fourth one is why this matters. Socrata returns its own errors as a JSON
**object**, and an object has no `.length` — so before the shape check, an
outage rendered on screen as **"No NYC restaurant matched"**. An error printed
as reassurance.

Two rules hold across all five: **an error never deletes a true answer** (the
previous result stays, dimmed and labelled as belonging to the earlier search),
and **the footer stamp always describes what is actually on screen**, so a real
timestamp never vouches for the wrong result.

An empty result gets the same treatment — it names *both* causes, including the
one that flatters us less: this dataset holds only restaurants that are still
open, so a restaurant that failed hard and shut down looks identical to one
that never existed.

### Check the work — [`/analysis/`](analysis/)

Every number on those pages is produced by a script that ships next to it.

```bash
cd analysis && python3 gates_app_test.py     # 15 gates, no setup, no API key
```

It reads the actual shipped pages and fails if any of them drifted from the
analysis — including a gate that fails the build if `operator.html` is still
quoting rates the analysis no longer produces.

The folder also holds `dob_contractor_test.py`: a **pre-registered test of our
own favourite explanation**, which came back `NOT SUPPORTED` and took a
sentence off the live page the same afternoon. The pattern it was explaining
survived and got *stronger*; the explanation did not. See
[`analysis/README.md`](analysis/README.md).

---

## FreshRoute morning triage

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

If you see `FAILED TO LOAD`, the page couldn't read `data/dairy_dataset.csv` —
which ships in this repo, so on the live URL that means a network failure, and
locally it means the server isn't rooted at the repo directory.

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
node test-data/vendors-test.js  # 39 tests — vendor reorder maths, asserted against a fault manifest
python3 verify.py               # cross-checks the whole pipeline against an independent
                                # pandas implementation; exits nonzero on any disagreement
```

Every one of these resolves its own paths, so they run from the repo root or
anywhere else.

`vendor-logic.js` turns *"order 100 units"* into a real purchase order — cases,
discounts, order cutoff, and a lead time that depends on the weekday. It is
**tested but not yet on screen**; the fixtures it runs against are generated by
`test-data/make_synthetic.py` from a fixed seed, with every injected fault
declared in `test-data/dirt_manifest.csv`.

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

---

## Data app (`/data-app/`)

A reusable shell for publishing findings that state their own limits. Every
dataset renders the same four blocks: **what one row counts** (grain, measured
not assumed), **the charts** (each with why that form and what method), **what
this data cannot answer**, and **source + provenance**.

**Adding a dataset is one JSON file — no code changes.**

1. Drop your chart PNGs in `data-app/assets/`
2. Write `data-app/datasets/<your-dataset>.json` (copy an existing one; the
   schema is: `id, title, subtitle, source{}, grain{}, charts[], cannot_answer[]`)
3. Add the filename to `datasets` in `data-app/datasets/manifest.json`

Every chart entry carries `form` and `form_why` because the choice of chart
type is an argument, and `method` + `caution` because framing choices —
window, denominator, smoothing, axis range — decide what a reader concludes.
