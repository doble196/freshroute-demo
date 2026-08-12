# Inspection Record Confidence 1.0 — pre-registration and backtest specification

**Registered 2026-08-11, before any rating engine exists.**

**Declaration: as of this commit, no rating engine, no backtest code, and no
result artifact exist.** This document and `irc_prereg.json` are committed
alone, before implementation begins. The git commit is the timestamp. The
first result artifact must embed this registration's commit hash. This
registration commit is never amended: corrections are subsequent, dated
amendment commits that state whether they occurred before or after first
execution of the engine. If the backtest contradicts this document, the
backtest wins and the failure is published.

Machine-readable constants live in `irc_prereg.json` beside this file. The
engine must read them from there — a constant redeclared in code is a
constant that drifts.

---

## 1. The claim

Inspection Record Confidence says **how much the available inspection history
lets you lean on the displayed city grade. It rates the evidence, not the
kitchen.**

It does not measure food quality, current kitchen conditions, service,
popularity, or the probability that any individual diner becomes ill. Those
words appear in the product, not just here.

## 2. Semantic contract (frozen)

- API key: `inspection_record_confidence`. No product name in the schema —
  the surrounding app can be renamed without a schema migration.
- Public states:
  - **Candidate outcome-ordered levels:** `strong`, `limited`. Candidate,
    not validated: the retrospective 28.9%/46.7% finding supports A-origin
    as a candidate *separator*; it does not yet validate complete levels
    across every eligible restaurant. Historical as-of reconstruction and an
    untouched validation window still have to earn these labels.
  - **Reserved:** `moderate` exists in the enum and is **not emitted in v1**.
    No splitter search is conducted in v1 (§9). Empty Moderate is correct
    behavior, not a failed implementation — UI, API, compare flow, analytics,
    and tests must all tolerate zero Moderate classifications.
  - **Abstention:** `not_enough_current_evidence` — not the bottom of the
    ordered scale. Excluded from monotonicity requirements; its observed
    outcomes are still published descriptively.
  - **Out of scope:** `displayed_grade_not_a` (§3).
- Change reasons, one required on every changed result:
  `NEW_CITY_DATA` · `METHODOLOGY_VERSION_CHANGED` · `SOURCE_RECORD_CORRECTED`.
  A methodology change must never masquerade as restaurant activity.
- Owner independence, as product copy: *"This rating can't be bought or
  changed by a business. It changes when the city record changes or when we
  publish a new methodology version."*
- Identity: `camis` is the source identifier for this dataset. The canonical
  physical-location ID is a separate concept. Reserve actions require a
  verified mapping; no mapping, no reserve button.

## 3. Scope: displayed-A records only, in 1.0

The ordered levels apply **only where the displayed city grade is A**.

Why: every measured effect this registration builds on is an A-grade effect —
the 34.5% base rate, the 28.9%/46.7% origin split, the censoring structure.
Nothing is measured about how a displayed B or C behaves next, and the
product moment is the A-moment: a displayed B or C already carries its own
warning; the A is the letter that over-promises.

A displayed B/C returns `displayed_grade_not_a` with the city grade shown
prominently. Extending ordered levels to non-A records requires its own
measured outcomes and its own version.

## 4. Unit of observation

One observation per **(camis, graded full-cycle A event)**. The as-of date is
that event's `inspection_date`. One observation per event, not per day —
daily sampling would manufacture thousands of autocorrelated copies of the
same evidence.

Eligible as-of events: Cycle inspections carrying grade A and a score.
Grade-pending events (Z/N/P), re-opening visits, administrative visits, and
sentinel-dated rows (`1900-01-01`) are not eligible as-of events.

## 5. Outcome (frozen)

**The next Cycle Initial Inspection with a score, strictly after the as-of
date. Failure = score >= 14** — the same `FAIL_SCORE` constant used by
`reinspect_join.py` and the re-inspection-A flag. The gate suite enforces
parity between this registration and the code.

No subsequent initial by the data cutoff = **censored**: counted, published
in the report card, never silently dropped. The censored population includes
closed restaurants whose records the city deleted — the observations that
fared worst are structurally the least likely to appear, and the report card
says so.

## 6. Leakage rules

- Features at as-of date T use only rows with `inspection_date <= T`.
- The engine ships with a leakage gate: injecting a synthetic future row must
  change **nothing** about any feature computed at T, and the gate must FIRE
  on a deliberately broken engine (Cheatcode #22).
- **Declared limitation:** the dataset does not record when a row became
  publicly *visible*. We assume visibility at `inspection_date`. Real
  publication lag means the as-of reconstruction is slightly more informed
  than a real user could have been on that date. This applies equally across
  levels; it is stated in the report card, not hidden.

## 7. Samples and the touch-once rule

- **Development:** as-of events with `inspection_date < 2024-07-01`.
- **Validation:** as-of events with `inspection_date >= 2024-07-01`,
  outcomes observed through the run's data cutoff.
- Temporal split, not random: the question is forward usefulness, and a
  random split would leak regime effects across the boundary.
- The same restaurant may appear in both windows. Features only look
  backward from their own as-of date, so this is not leakage; noted anyway.
- **The validation window is opened once** (`validation_runs_allowed: 1`).
  One run, on this registered mapping, published regardless of result.
  Anything changed after that run is a new methodology version and requires
  a NEW validation window of later data.
- Because v1 conducts no splitter search and freezes every threshold here,
  the development sample is used for diagnostics, censoring
  characterization, and the sensitivity reporting in §8 — not for tuning.
  A backtest tuned against its own test population measures
  threshold-fitting skill, not future usefulness.

## 8. The single classification feature, and the two constraints

**Feature (the only one in v1) — origin of the displayed A. CANDIDATE.**
Measured retrospectively (agrade_test.json, watermark on file):

- A earned on an initial inspection: 28.9% failure (n=16,674, CI 28.2–29.6)
- A earned on a confirmed re-inspection after a failed initial: 46.7%
  (n=4,110, CI 45.1–48.2)
- Unconfirmed re-inspection A: 44.9% (n=3,985) — held separate.

**Ambiguity fails closed:** an origin that cannot be confirmed is assigned
the level of the worst confirmable interpretation, never the best. (The
unconfirmed stratum's measured 44.9% ≈ 46.7% is consistent with this rule,
but the rule stands on fail-closed grounds, not on that number.)
Classification uses the same 180-day lookback as `agrade_test.py`.

**Constraint 1 — evidence age. A product currentness policy, not an outcome
feature, and not outcome-validated.**

- `evidence_age_days <= 730`: eligible for classification.
- `evidence_age_days > 730`: `not_enough_current_evidence`.
- Age contributes no points, no weights, no deductions, and no
  Strong-to-Moderate downgrade. It determines whether the app speaks, not
  what risk it claims.
- The abstention cohort is excluded from monotonicity requirements; its
  observed outcomes are published descriptively.
- Sensitivity reporting at fixed alternatives — 365, 545, and 730 days —
  ships in the report card: share abstained and descriptive outcomes at
  each. Descriptive only; the 730 policy does not move on outcome data.
- **Disclosure:** the author had seen age-bucket outcome data before
  registering this policy — the directional staleness hypothesis was tested
  through those buckets and **FAILED at −10.3pp (fresher A's failed MORE,
  confounded by why the city returned early)**. This policy therefore cannot
  claim blindness to age data and is registered as product policy, with its
  sign-preserved rejection attached. Any future attempt to use age as a
  risk feature must first explain that sign.

**Constraint 2 — no splitter search in v1.** No statistic other than the
origin feature is computed against outcomes anywhere in the v1 backtest.
Earlier drafts listed consistency definitions (score-range, C-band-crossing,
A-band-share, history-depth) and a parent-initial severity split. Those are
**parked as future-work notes, not registered**: evaluating any of them in
v1 would hand the development process enough freedom to manufacture a middle
band. If Moderate is ever to exist, it arrives as v1.1 — its own
registration, one named feature with a fixed cutoff-selection rule, required
separation from **both** neighbors, and a fresh untouched validation window.

## 9. Registered mapping, v1.0.0-candidate

Order of evaluation: scope, then abstention, then levels.

1. Displayed grade is not A → `displayed_grade_not_a` (out of scope).
2. No eligible graded A event, newest older than 730 days, or no
   classifiable record at all → `not_enough_current_evidence`.
3. **`strong`** — the displayed A was earned on an initial inspection.
4. **`limited`** — the displayed A was earned on a re-inspection: confirmed
   after a failed initial, or unconfirmable (fails closed).
5. **`moderate` — reserved, never emitted in v1.** No rule produces it.

## 10. Hypothesis, bars, and failure actions (frozen)

**H1 (the entire v1 hypothesis):** in the untouched validation window, with
features reconstructed as-of, `strong` and `limited` separate:

- **Monotonic:** strong's next-inspection failure rate < limited's.
- **Separation:** by **>= 5.0pp**.
- **Support:** n >= 500 eligible observations in each level.
- **Published:** Wilson 95% intervals, denominators, date ranges, and
  censoring counts for every state — including abstention and
  `displayed_grade_not_a`, descriptive only.

**Failure actions:** with only two ordered levels there is nothing to merge
into. If H1 fails on validation, **the rating is abandoned** and the failure
is published with the same prominence a success would have received. If H1
holds on development but the validation window's support is insufficient
(n < 500 in either level), the run is reported as inconclusive and the next
attempt is a new version against a later window — not a re-run of this one.

## 11. Report card (published, linked from the UI)

Per state: eligible observations, next-inspection failure rate, 95%
interval, censored count — abstention and out-of-scope reported separately,
descriptive only. Plus: methodology version, source-data cutoff, outcome
definition, lookback rules, exclusions, missing-data behavior, calibration
period, untouched validation period, the age-policy sensitivity table
(§8), and **rejected candidate components** — currently the DOB contractor
explanation (NOT SUPPORTED, −0.1pp) and directional staleness (FAILED,
−10.3pp, sign preserved).

## 12. Change control

- This registration commit is never amended. Corrections are subsequent,
  dated amendment commits stating whether they occurred before or after
  first execution of the engine.
- Any change after the validation run is a new methodology version and
  requires a new validation window.
- Every published result embeds this registration's commit hash.
- The gate suite pins the frozen constants in `irc_prereg.json` against the
  code that must consume them, with negative tests proving the pins fire.
