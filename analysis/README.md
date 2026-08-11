# The evidence behind the apps

Every claim the two live pages make is produced by a script in this folder. The
app and its evidence ship together, so a claim cannot outlive the analysis that
earned it.

```bash
python3 gates_app_test.py        # 15 gates over the shipped pages - no setup
```

That is the fastest way to check this work. It reads the actual shipped
`../data-app/*.html` and fails if any of them drifted from the analysis.

## What each file is for

| File | What it earns |
|---|---|
| `reinspect_join.py` | Pairs a failed initial inspection with the re-inspection that followed and counts which violation codes were still there. Produces every rate in the operator app. |
| `reinspect_join.json` | Its output: 40 codes with at least 50 citations, each with a Wilson 95% interval. |
| `dob_contractor_test.py` | A pre-registered test of our own favourite explanation. |
| `dob_contractor_test.json` | Its verdict: **NOT SUPPORTED**. |
| `build_operator.py` | The only writer of the persistence table embedded in `operator.html`. |
| `gates_app_test.py` | GUARDS 10&ndash;12. Each paired with a negative test that proves it fires. |
| `pull.py` | The shared, guarded fetch layer every analysis script goes through. |
| `CHECK-APP.md` | Traces each sentence printed on screen back to the script that earned it. |

## Rerun it yourself

```bash
python3 reinspect_join.py --json reinspect_join.json   # ~28s against the live API
python3 build_operator.py                              # re-embed into the page
python3 gates_app_test.py                              # prove nothing drifted
```

No API key. A key embedded in a public page is a key you have given away, and
this dataset does not need one.

## The result that killed our own story

The operator app says facility and pest violations come back far more often
than food-handling ones &mdash; about **4 in 10** against **1 in 4**. For a
while the page also said *why*: "needs money and a contractor."

That was an explanation, not a measurement. So we tested it against each
building's own Department of Buildings record, writing the bar down **before**
pulling a single DOB row:

- **Predicted:** facility persistence at least 5pp higher in buildings that
  already had ACTIVE DOB violations before the window opened.
- **Placebo:** practice persistence should *not* move &mdash; staff behaviour
  does not depend on the landlord.

Measured across 3,249 troubled-building restaurants and 2,481 clean ones:

```
                      troubled     clean    difference
facility persistence     29.6%     29.7%    -0.1pp
practice persistence     18.9%     18.8%    +0.2pp
```

**Not supported.** The building's own violation record explains none of it.

Two things worth keeping straight:

1. **The fact survived.** Facility violations persist ~1.57&times; practice
   violations in troubled buildings and ~1.58&times; in clean ones. The pattern
   replicates in both strata &mdash; it is *more* robust after this test.
2. **The explanation did not.** The page now says the pattern is real and that
   we do not know why. A null result that kills your own favourite sentence is
   still a result, and it went off the live page the same afternoon.

## What we still cannot tell you

- **How the points were added up.** The city publishes the total and the
  violations, never the points each violation carried. So the operator app
  ranks by whether an item tends to still be there, never by what clearing it
  saves you.
- **Why the sticky ones stick.** See above. Tested, and still open.
- **Anything about the places that closed.** This dataset holds only active
  restaurants. Every restaurant that failed hard and shut down was removed
  before we ever counted, so the worst records are the ones we cannot see.
