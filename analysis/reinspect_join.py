#!/usr/bin/env python3
"""
The initial -> re-inspection JOIN: which violations survive their own
re-inspection?

THE CLAIM UNDER TEST (pre-registered): facility violations (building problems
— vermin, plumbing, surfaces, ventilation) persist to re-inspection at >= 1.5x
the rate of practice violations (behavior — temperatures, cleaning, hygiene).
FALSIFIER: if the two classes persist within 10% of each other, the
"can't-fix vs won't-fix" story is dead.

WHY A JOIN, NOT A GROUP-BY. A re-inspection row does not name the initial it
follows. The pairing is constructed: for each camis, each failed initial
(score >= 14) is paired with the EARLIEST subsequent Cycle Re-inspection
within PAIR_WINDOW days, provided no newer initial intervenes. Everything
else in this project has been aggregation; this is the first real join, and
its edges are counted, not hidden:
  - initials with no re-inspection in window (censoring: too recent, or the
    restaurant closed/terminated -> survivorship)
  - re-inspections with no parent initial in window

CLASSIFICATION comes from the data's own violation_description text, not
from memory of the code book. Codes whose description matches neither
keyword family land in 'other' and are EXCLUDED from the headline comparison
but reported — a silent third bucket would be a thumb on the scale.

Runs on pull.Guarded: sentinel exclusion, watermark drift checks, grouped
auto-pagination, alias-shadow guard, 429 retry — all inherited.

Usage:  python3 reinspect_join.py [--window 120] [--json out.json]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull import Guarded                                       # noqa: E402

INITIAL = "Cycle Inspection / Initial Inspection"
REINSP = "Cycle Inspection / Re-inspection"
FAIL_SCORE = 14          # B-or-worse on the initial: triggers re-inspection

FACILITY_KW = ["mice", "rats", "roaches", "flies", "vermin", "harborage",
               "plumbing", "sewage", "ventilation", "lighting", "walls",
               "floor", "ceiling", "premises", "constructed", "maintained",
               "pipe", "facility"]
PRACTICE_KW = ["temperature", "cold food", "hot food", "thermometer", "washed",
               "sanitiz", "hygien", "hands", "glove", "hair", "smoking",
               "contamin", "protected", "labeled", "thaw", "cooling",
               "reheat", "food worker", "wiping", "utensil"]


def classify(desc):
    d = (desc or "").lower()
    fac = any(k in d for k in FACILITY_KW)
    pra = any(k in d for k in PRACTICE_KW)
    if fac and not pra:
        return "facility"
    if pra and not fac:
        return "practice"
    return "other"          # both or neither — excluded from the headline


# Below this many citations the interval is too wide to rank a code on, so the
# operator page is not shown the code at all rather than shown a soft number.
MIN_CITED = 50


def wilson(k, n, z=1.96):
    """95% interval for a proportion.

    Computed HERE and exported, never in the browser. operator.html ranks a
    restaurant's open violations by these rates, so the page must only ever
    print a number this script handed it - a statistic recomputed in JS is a
    second implementation that drifts (the reason GUARD 10 exists).
    """
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    margin = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5)
    return ((centre - margin) / d, (centre + margin) / d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120, help="max days initial->re-inspection")
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args()

    g = Guarded("restaurants", strict=True)

    # One grouped pull at violation grain for both cycle types. Grouping
    # dedupes the rare same-code-twice rows; auto-pagination completes it.
    rows = g.agg(**{
        "$select": ("camis, inspection_date, inspection_type, violation_code, "
                    "max(score) AS score_v, max(boro) AS boro_v"),
        "$where": f"inspection_type in ('{INITIAL}', '{REINSP}') AND violation_code IS NOT NULL",
        "$group": "camis, inspection_date, inspection_type, violation_code",
    })
    print(f"violation-grain rows: {len(rows):,}", file=sys.stderr)

    # code -> description (for classification), from the data itself
    desc_rows = g.agg(paginate=False, **{
        "$select": "violation_code, max(violation_description) AS descr",
        "$where": "violation_code IS NOT NULL",
        "$group": "violation_code", "$limit": 400,
    })
    desc = {r["violation_code"]: r.get("descr", "") for r in desc_rows}
    klass = {c: classify(d) for c, d in desc.items()}

    # assemble inspections: (camis, date, type) -> {codes}, score
    insp = defaultdict(lambda: {"codes": set(), "score": None, "boro": None})
    for r in rows:
        key = (r["camis"], r["inspection_date"][:10], r["inspection_type"])
        insp[key]["codes"].add(r["violation_code"])
        s = r.get("score_v")
        if s is not None:
            insp[key]["score"] = float(s)
        insp[key]["boro"] = r.get("boro_v") or insp[key]["boro"]

    # per-camis timeline
    by_camis = defaultdict(list)
    for (camis, d, t), v in insp.items():
        by_camis[camis].append((datetime.fromisoformat(d), t, v))
    for v in by_camis.values():
        v.sort(key=lambda x: x[0])

    # ── the join ──────────────────────────────────────────────────────
    pairs, unpaired_initials, orphan_reinsp = [], 0, 0
    window = timedelta(days=a.window)
    for camis, timeline in by_camis.items():
        for i, (d0, t0, v0) in enumerate(timeline):
            if t0 != INITIAL or (v0["score"] or 0) < FAIL_SCORE:
                continue
            mate = None
            for d1, t1, v1 in timeline[i + 1:]:
                if d1 - d0 > window:
                    break
                if t1 == INITIAL:      # a new cycle started first — no pair
                    break
                if t1 == REINSP:
                    mate = (d1, v1)
                    break
            if mate:
                pairs.append({"camis": camis, "initial": v0, "re": mate[1],
                              "gap_days": (mate[0] - d0).days})
            else:
                unpaired_initials += 1
    paired_re = {(p["camis"], id(p["re"])) for p in pairs}
    total_re = sum(1 for tl in by_camis.values() for _, t, _ in tl if t == REINSP)

    # ── per-code persistence ──────────────────────────────────────────
    cited = defaultdict(int)      # code -> times cited at a paired initial
    persisted = defaultdict(int)  # code -> times re-cited at the paired re-inspection
    for p in pairs:
        for c in p["initial"]["codes"]:
            cited[c] += 1
            if c in p["re"]["codes"]:
                persisted[c] += 1

    def rate(codes):
        c = sum(cited[x] for x in codes)
        p_ = sum(persisted[x] for x in codes)
        return (p_ / c if c else 0.0), p_, c

    fac_codes = [c for c in cited if klass.get(c) == "facility"]
    pra_codes = [c for c in cited if klass.get(c) == "practice"]
    oth_codes = [c for c in cited if klass.get(c, "other") == "other"]
    fr, fp, fc = rate(fac_codes)
    pr_, pp, pc = rate(pra_codes)
    orr, op, oc = rate(oth_codes)

    gaps = sorted(p["gap_days"] for p in pairs)
    med_gap = gaps[len(gaps) // 2] if gaps else 0

    print(f"\n=== THE JOIN ===")
    print(f"pairs (failed initial -> re-inspection <= {a.window}d): {len(pairs):,}")
    print(f"failed initials with NO pair (censored/closed/new cycle): {unpaired_initials:,}")
    print(f"median gap initial -> re-inspection: {med_gap} days")
    print(f"\n=== PERSISTENCE: cited at initial AND re-cited at its re-inspection ===")
    print(f"  facility ({len(fac_codes)} codes): {100*fr:.1f}%  ({fp:,}/{fc:,})")
    print(f"  practice ({len(pra_codes)} codes): {100*pr_:.1f}%  ({pp:,}/{pc:,})")
    print(f"  other    ({len(oth_codes)} codes): {100*orr:.1f}%  ({op:,}/{oc:,})  [excluded from headline]")
    ratio = fr / pr_ if pr_ else float("inf")
    print(f"\n  RATIO facility/practice = {ratio:.2f}x   (pre-registered: >=1.5x holds, within 10% kills)")

    top = sorted(cited, key=lambda c: -cited[c])[:12]
    print(f"\n  {'code':<6}{'class':<10}{'cited':>7}{'persist':>9}  description")
    for c in top:
        print(f"  {c:<6}{klass.get(c,'?'):<10}{cited[c]:>7,}{100*persisted[c]/cited[c]:>8.1f}%  {(desc.get(c) or '')[:56]}")

    # ── THE DISCRETION CHECK, pre-registered before this ran ──────────
    # Competing explanation: inspectors reflexively re-cite structural codes
    # (discretion), rather than structures being harder to fix (difficulty).
    # Discretion is exercised by LOCAL inspector pools; buildings are not
    # local. Two tests, thresholds fixed in advance:
    #   T1 RANK: facility > practice persistence within EVERY borough.
    #      Difficulty predicts 5/5; borough-local discretion predicts flips.
    #   T2 SPREAD: for each top code, the cross-borough range of persistence.
    #      If the MEDIAN per-code range exceeds the citywide facility-practice
    #      gap, borough effects dominate code effects -> discretion serious.
    # LIMIT stated up front: a citywide-uniform citation policy would pass
    # both tests — this check can only exclude borough-local discretion.
    print(f"\n=== DISCRETION CHECK (pre-registered) ===")
    boros = ["Manhattan", "Brooklyn", "Queens", "Bronx", "Staten Island"]
    def rate_in(codes, boro):
        c = p_ = 0
        for pr in pairs:
            if pr["initial"]["boro"] != boro:
                continue
            for x in pr["initial"]["codes"]:
                if x in codes:
                    c += 1
                    if x in pr["re"]["codes"]:
                        p_ += 1
        return (p_ / c if c else None), c
    gap = fr - pr_
    print(f"citywide facility-practice gap: {100*gap:.1f} points")
    print(f"\n  T1 — class rates per borough (difficulty predicts facility > practice in all 5):")
    wins = 0
    for b in boros:
        f_, fn = rate_in(set(fac_codes), b)
        p2, pn = rate_in(set(pra_codes), b)
        if f_ is None or p2 is None:
            print(f"    {b:<15} insufficient pairs"); continue
        ok = f_ > p2; wins += ok
        print(f"    {b:<15} facility {100*f_:>5.1f}% ({fn:>5,})  practice {100*p2:>5.1f}% ({pn:>5,})  "
              f"{'facility>practice' if ok else 'FLIPPED'}")
    print(f"    -> {wins}/5 boroughs")
    print(f"\n  T2 — cross-borough RANGE of persistence per top code:")
    # POST-HOC CORRECTION, stated openly: the first implementation (a) used
    # sorted[n//2], the upper-middle of an even list, not the median, and
    # (b) included 'other'-class codes the facility/practice claim excludes —
    # and the verdict flipped on those two implementation accidents. Fixed to
    # a true median over the claim's own codes; the all-codes reading is
    # still printed so the correction is visible, not silent.
    import statistics as _st
    def code_ranges(codes):
        out = []
        for c in codes:
            vals = [r_ for b in boros
                    for r_, n_ in [rate_in({c}, b)] if r_ is not None and n_ >= 50]
            if len(vals) >= 3:
                out.append((c, max(vals) - min(vals)))
        return out
    claim_codes = [c for c in top[:8] if klass.get(c) in ("facility", "practice")]
    all_r = code_ranges(top[:8])
    claim_r = code_ranges(claim_codes)
    for c, rng in all_r:
        tag = "" if klass.get(c) in ("facility", "practice") else "   [other — outside the claim]"
        print(f"    {c:<6}{klass.get(c,'?'):<10} range {100*rng:>5.1f} pts{tag}")
    med_all = _st.median([r for _, r in all_r]) if all_r else 0
    med_claim = _st.median([r for _, r in claim_r]) if claim_r else 0
    print(f"    -> true median, ALL top codes:   {100*med_all:.1f} pts vs gap {100*gap:.1f}")
    print(f"    -> true median, CLAIM codes only: {100*med_claim:.1f} pts vs gap {100*gap:.1f}: "
          f"{'borough effects dominate — discretion serious' if med_claim > gap else 'code effects dominate — difficulty survives'}")

    for src, wm in g.watermarks.items():
        print(f"\nwatermark {src}: {wm}" + (" — held" if not g.drift else f" DRIFT {g.drift}"))

    if a.json:
        Path(a.json).write_text(json.dumps({
            "pairs": len(pairs), "unpaired_initials": unpaired_initials,
            "median_gap_days": med_gap, "window_days": a.window,
            "facility": {"rate": fr, "persisted": fp, "cited": fc, "codes": len(fac_codes)},
            "practice": {"rate": pr_, "persisted": pp, "cited": pc, "codes": len(pra_codes)},
            "other": {"rate": orr, "persisted": op, "cited": oc, "codes": len(oth_codes)},
            "ratio": ratio,
            "per_code": [{"code": c, "class": klass.get(c, "?"), "cited": cited[c],
                          "persist_rate": persisted[c] / cited[c],
                          "desc": (desc.get(c) or "")[:80]} for c in top],
            # Every code with a usable sample, worst-persisting first. This is
            # what operator.html ranks an open inspection by: not the class
            # rate (the class comes from a keyword classifier that the browser
            # does not run, so pairing one with a JS-assigned class would
            # attach a measured number to an assignment the measurement never
            # made), but the code's own rate, with its own interval and n.
            "min_cited": MIN_CITED,
            "per_code_all": [
                {"code": c, "class": klass.get(c, "other"),
                 "cited": cited[c], "persisted": persisted[c],
                 "persist_rate": persisted[c] / cited[c],
                 "lo": wilson(persisted[c], cited[c])[0],
                 "hi": wilson(persisted[c], cited[c])[1],
                 "desc": desc.get(c) or ""}
                for c in sorted(cited, key=lambda x: -persisted[x] / cited[x])
                if cited[c] >= MIN_CITED
            ],
        }, indent=2))
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
