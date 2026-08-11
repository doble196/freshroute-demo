# check.html — the live restaurant checker

A single self-contained page. Type any NYC restaurant, it fetches the city's
inspection record from the SODA API **in the browser at the moment you search**
and shows what the score is made of.

```bash
python3 -m http.server 8000     # from this folder
# then open http://localhost:8000/check.html
```

No build step, no dependencies, no API key. A key embedded in a public page is
a key you have given away, and this dataset does not need one.

## Why it lives in this folder

Every claim the page makes is produced by a script sitting next to it. That is
the point — the app and its evidence ship together, so a claim cannot outlive
the analysis that earned it.

| The page says | Earned by |
|---|---|
| A 0–13, B 14–27, C 28+ | DOHMH's own published cut points, not ours |
| "about 4 in 10 of these were still there at the re-inspection" | `reinspect_join.py` — 6,975 initial→re-inspection pairs |
| the building vs handling split | `reinspect_join.py`, classified from each violation's own description text |
| "we tested whether buildings with open DOB violations explain it — they don't" | `dob_contractor_test.py` → `dob_contractor_test.json` |

## The sentence this app used to say, and no longer does

It read: *"Needs money and a contractor."* That was an explanation for the
4-in-10 persistence, not a measurement of it — flagged as inference when it was
written.

`dob_contractor_test.py` tested it against each building's own Department of
Buildings record, pre-registering the bar before pulling a single DOB row:

- **Predicted:** facility persistence ≥5pp higher in buildings that already had
  ACTIVE DOB violations issued before the window opened.
- **Placebo:** practice persistence should *not* move — staff behaviour does not
  depend on the landlord.

Measured, across 3,908 troubled-building pairs and 2,972 clean-building pairs:

```
                      troubled     clean    difference
facility persistence     29.6%     29.7%    -0.1pp  (95% CI -1.7 .. +1.4)
practice persistence     18.9%     18.8%    +0.2pp  (95% CI -1.2 .. +1.5)
```

**Not supported.** The building's own violation record explains none of it.

Two things worth keeping straight:

1. **The fact survived.** Facility violations persist ~1.57× practice violations
   in troubled buildings and ~1.58× in clean ones. The pattern replicates in both
   strata — it is more robust after this test, not less.
2. **The explanation did not.** So the page now says the pattern is real and that
   we do not yet know why. A null result that kills your own favourite sentence is
   still a result.

Re-run it:

```bash
python3 dob_contractor_test.py --json dob_contractor_test.json
```

## The five ways this page can fail, and what each one says

A user-triggered fetch is not a fetch-on-load. On load the request and the page
are the same event: if the fetch dies, nothing renders and the failure is
self-evident. Afterwards they are two things, and **the page outlives the
request** — so a dead request leaves a live page that is fully capable of
looking correct while being wrong. Every state below exists because of that.

| Failure | What the reader sees | Why it is not one branch |
|---|---|---|
| no network | "Could not reach the city's API at all." | `fetch()` rejects with a `TypeError`. A 503 does **not** land here. |
| HTTP error | "The city's API answered with an error: 503." | Their server refusing. Worth retrying. |
| malformed body | "The city's API answered, but what came back was not data." | 200 in the status line, HTML in the body — a gateway answering in front of the real server. |
| wrong-shape 200 | "The city's API rejected the query: *<their message>*" | Socrata returns errors as a JSON **object**. An object has no `.length`, so before the `Array.isArray` check this rendered as **"No NYC restaurant matched"** — an outage printed as reassurance. |
| hang | "The city's API did not answer within 12 seconds." | `AbortController` + a 12s timer. Without it the button stayed dead at "Looking..." forever. |

Two rules hold across all five:

1. **An error never deletes a true answer.** `#out` holds the last thing the
   city actually gave us; `#status` holds what is happening now. The previous
   result stays, dimmed and labelled as belonging to the earlier search,
   because it is still exactly as true as it was a second ago.
2. **The stamp describes what is on screen.** If an error left an older result
   up, the footer says the stamp belongs to *that* result — a real timestamp
   must never vouch for the wrong thing.

`gates_test.py` GUARD 11 fails the build if any failure kind loses its own
explanation, if the shape check or the timeout is removed, or if a single
non-ASCII byte reaches the file.

## Zero rows is not one answer either

An empty result has two causes and the screen cannot tell them apart, so it
names both. The second one is the important one: **this dataset holds only
restaurants that are still open.** When one closes, the city removes its whole
inspection history — so a restaurant that failed hard and shut down comes back
looking identical to a restaurant that never existed. The page says so.

## What the page refuses to do

- **Invent numbers.** Every value on screen came from the API response in that
  session. There is no cached copy and no fixture.
- **Let a low score pass as a clean bill of health.** A re-opening visit gets an
  amber warning *above* the number, because "Establishment re-opened by DOHMH"
  with a score of 0 is not a kitchen that was checked top to bottom.
- **Imply the total is decomposable.** The city publishes the score and the
  violations but not the points per violation, so the page shows what was found
  and never the arithmetic. It says so on screen.
- **Hide staleness.** Anything over a year old is called out as old rather than
  presented as current.

## Deployed

Public copy at `data-app/check.html` in the freshroute-demo repo →
https://doble196.github.io/freshroute-demo/data-app/check.html

The two copies are byte-identical — this one carries the DataHub back-link too,
so a `diff` should always return nothing. This one is the reference; that one is
the deploy. If they ever diverge, the deploy is wrong.
