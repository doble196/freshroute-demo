# AGENTS.md

Instructions for coding agents working in this repository.

## What this repo is

Two browser apps and the analysis behind them. The DataHub (`data-app/`) reads
NYC's restaurant-inspection API live; FreshRoute (repo root) triages a committed
dairy export. No build step, no framework, no package install needed to run
either.

```bash
python3 -m http.server 8100     # then open http://localhost:8100
cd analysis && python3 gates_app_test.py    # 15 gates, no setup, no API key
```

## The rule that matters most here

**A claim and the evidence for it ship together.** If you put a number on a
page, a script in `analysis/` must produce it, and a gate must fail when the two
disagree. Do not hand-copy a figure from a script's output into HTML. That copy
drifts the first time either side changes, and nothing looks wrong when it does.

`analysis/build_operator.py` is the *only* writer of the persistence table
embedded in `data-app/operator.html`. Edit the block by hand and GUARD 12 fails.

## Before you commit

```bash
cd analysis && python3 gates_app_test.py        # must be 15 passed, 0 failed
python3 build_operator.py --check               # embedded table must be current
python3 sync_public.py <war-room-path> --check  # if you have the private repo
```

## Constraints that will bite you

- **`data-app/check.html` and `data-app/operator.html` must be pure ASCII.** No
  raw curly quotes, em dashes, or ellipses. Use `\uXXXX` escapes inside JS
  strings and HTML entities inside markup. GUARD 11 fails the build on a single
  byte above U+007F. When writing an escape, build it from the codepoint rather
  than typing the glyph - typing it is how this broke three times.
- **Both pages must name the same failure kinds.** GUARD 12 compares them. If
  you add a failure mode to one, add it to the other.
- **Never add an API key.** The dataset needs none, and a key in a public page
  is a key you have given away.

## Handling a live fetch

Any user-triggered fetch here handles five distinct failures, each with its own
message: network drop, HTTP error status, malformed body, wrong-shape 200, and
hang (12s `AbortController` timeout). Do not collapse these into one catch
block. The reason is specific: Socrata returns its own errors as a JSON
**object**, and an object has no `.length`, so before the `Array.isArray` check
an outage rendered on screen as "No NYC restaurant matched" - an error printed
as reassurance.

Two invariants hold across all five, and both are load-bearing:

1. **An error never deletes a true answer.** `#out` holds the last result the
   city actually returned; `#status` holds what is happening now. Keeping them
   separate is what makes the wipe unrepresentable rather than merely unhandled.
2. **The footer stamp always describes what is on screen.** If an error left an
   older result visible, the stamp says so. A real timestamp must never vouch
   for the wrong result.

## Writing copy

Plain and short. Name the trick first. State what a screen *cannot* tell you on
the screen itself, not in a footnote - the empty state names both causes,
including that closed restaurants are deleted from the dataset entirely.

## What not to do

- Do not add tracking, analytics, or third-party scripts. These pages load
  nothing from outside NYC OpenData.
- Do not soften a measured claim into a hedge, or harden a hedge into a claim.
  If a number is uncertain, print its interval and its sample size.
- Do not describe an explanation as a finding. If a mechanism is untested, the
  page says the pattern is real and the reason is unknown - because that is what
  happened here once already, and the test came back NOT SUPPORTED.
