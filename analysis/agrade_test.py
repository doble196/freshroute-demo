#!/usr/bin/env python3
"""
Does the A in the window predict what the next inspection finds?

THE CLAIM UNDER TEST (pre-registered, written before a single row was pulled).
Both live tools rest on one sentence: the grade card is a weak description of
what a kitchen is like now. That is an assertion. This measures it.

  PREDICTION  More than 20% of A-graded inspections are followed by a next
              full inspection scoring 14 or worse (B-or-C by the city's own
              bands). If a displayed A is that unreliable, decomposing it is
              worth doing.

  PLACEBO     Staleness must matter. Among A-grades, a longer gap to the next
              inspection should mean a higher failure rate. If a 400-day-old A
              predicts exactly as well as a 60-day-old one, then the "this is
              N days old" copy on both pages is decoration and comes off.

  FALSIFIER   If A-grades hold at 90%+ (fewer than 10% failing next time),
              the premise is wrong. The grade card would be doing its job and
              I would be selling a problem that does not exist. That gets
              published, and the pages get rewritten.

WHY THIS PAIRING. A grade is earned by one inspection and displayed until the
next one replaces it. So the honest question is not "is this restaurant clean"
but "when the city came back, what did they find?" For each inspection carrying
grade A, the outcome is the NEXT Cycle Initial Inspection with a score - the
next FULL inspection, not a re-opening or a compliance visit, because those are
not top-to-bottom checks (the tools already say so on screen).

WHAT IS COUNTED, NOT HIDDEN:
  - A-grades with no later initial (censored: too recent, or the restaurant
    closed and the city deleted it -> survivorship, the same hole as always)
  - the split between As earned on an initial vs earned on a re-inspection,
    since both display the same card but are not the same event

Runs on pull.Guarded: sentinel exclusion, watermark drift, grouped
auto-pagination, alias-shadow guard, 429 retry - all inherited.

Usage:  python3 agrade_test.py [--json agrade_test.json]
"""

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull import Guarded                                          # noqa: E402
from reinspect_join import INITIAL, REINSP, FAIL_SCORE, wilson    # noqa: E402

# Pre-registered bars. Named here so they cannot be adjusted after the fact.
PREDICT_MIN_FAIL = 0.20      # >20% of As followed by a 14+ score
FALSIFY_MAX_FAIL = 0.10      # <10% and the premise is dead
PLACEBO_MIN_SPREAD = 5.0     # stale-vs-fresh must differ by >=5pp

GAP_BUCKETS = [(0, 180, "under 6 months"), (180, 300, "6-10 months"),
               (300, 400, "10-13 months"), (400, 10**6, "over 13 months")]


def bucket(days):
    for lo, hi, label in GAP_BUCKETS:
        if lo <= days < hi:
            return label
    return GAP_BUCKETS[-1][2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json")
    a = ap.parse_args()

    g = Guarded("restaurants", strict=True)

    # Inspection grain. The raw table is one row per violation, so group to
    # (camis, date, type) and take max() of the repeated inspection-level
    # fields. Grouping also dedupes the same-inspection-twice rows.
    rows = g.agg(**{
        "$select": ("camis, inspection_date, inspection_type, "
                    "max(score) AS score_i, max(grade) AS grade_i"),
        "$where": "inspection_date IS NOT NULL",
        "$group": "camis, inspection_date, inspection_type",
    })
    print(f"inspection-grain rows: {len(rows):,}", file=sys.stderr)

    by_camis = defaultdict(list)
    for r in rows:
        d = (r.get("inspection_date") or "")[:10]
        if not d or d == "1900-01-01":         # the city's null-date sentinel
            continue
        s = r.get("score_i")
        by_camis[r["camis"]].append({
            "date": datetime.fromisoformat(d),
            "type": r.get("inspection_type") or "",
            "score": None if s is None else float(s),
            "grade": (r.get("grade_i") or "").strip().upper(),
        })
    for v in by_camis.values():
        v.sort(key=lambda x: x["date"])

    # ── the pairing: each displayed A -> the next FULL inspection ──────
    paired, censored = [], 0
    for timeline in by_camis.values():
        for i, ev in enumerate(timeline):
            if ev["grade"] != "A":
                continue
            nxt = None
            for later in timeline[i + 1:]:
                if later["type"] == INITIAL and later["score"] is not None:
                    nxt = later
                    break
            if nxt is None:
                censored += 1
                continue
            paired.append({
                "gap": (nxt["date"] - ev["date"]).days,
                "next_score": nxt["score"],
                "next_grade": nxt["grade"],
                "earned_on": "initial" if ev["type"] == INITIAL else
                             ("re-inspection" if ev["type"] == REINSP else "other"),
            })

    n = len(paired)
    if not n:
        sys.exit("no A-grades could be paired - nothing to report")

    failed = [p for p in paired if p["next_score"] >= FAIL_SCORE]
    rate = len(failed) / n
    lo, hi = wilson(len(failed), n)

    print("\n=== THE A-GRADE TEST ===")
    print(f"A-graded inspections paired with a later full inspection: {n:,}")
    print(f"A-grades with no later full inspection (censored):        {censored:,}")
    print(f"\n  next full inspection scored {FAIL_SCORE}+ (B or worse): "
          f"{100*rate:.1f}%  ({len(failed):,}/{n:,})")
    print(f"  95% interval: {100*lo:.1f}% - {100*hi:.1f}%")

    scores = sorted(p["next_score"] for p in paired)
    med = scores[len(scores) // 2]
    print(f"  median next score: {med:.0f}   (the A band tops out at 13)")

    # where the failures land
    c_band = sum(1 for p in paired if p["next_score"] >= 28)
    print(f"  of all {n:,}: {100*c_band/n:.1f}% scored 28+ (C band) next time")

    # ── PLACEBO: does staleness predict anything? ─────────────────────
    print(f"\n  by gap from the A to the next full inspection:")
    per_bucket = {}
    for _, _, label in GAP_BUCKETS:
        grp = [p for p in paired if bucket(p["gap"]) == label]
        if len(grp) < 30:
            print(f"    {label:<16} n={len(grp):<6} (too few to report)")
            continue
        f = sum(1 for p in grp if p["next_score"] >= FAIL_SCORE)
        blo, bhi = wilson(f, len(grp))
        per_bucket[label] = {"n": len(grp), "fail_rate": f / len(grp),
                             "lo": blo, "hi": bhi}
        print(f"    {label:<16} n={len(grp):<6} {100*f/len(grp):>5.1f}% failed "
              f"  ({100*blo:.1f}-{100*bhi:.1f}%)")

    # ── how the A was earned: same card, different event ──────────────
    print(f"\n  how that A was earned:")
    per_origin = {}
    for origin in ("initial", "re-inspection", "other"):
        grp = [p for p in paired if p["earned_on"] == origin]
        if len(grp) < 30:
            continue
        f = sum(1 for p in grp if p["next_score"] >= FAIL_SCORE)
        per_origin[origin] = {"n": len(grp), "fail_rate": f / len(grp)}
        print(f"    {origin:<16} n={len(grp):<6} {100*f/len(grp):>5.1f}% failed next time")

    # ── the verdict, against bars set before the pull ──────────────────
    # The placebo needs a DIRECTION, not just a spread. Written as "spread
    # >= 5pp" it passed on a 12.6pp gap that runs the wrong way - fresher As
    # failing MORE than stale ones. A bar that a result can clear by moving
    # opposite to the prediction is not a bar. Stated properly: staler must be
    # worse, comparing the oldest bucket to the freshest.
    ordered = [per_bucket[label] for _, _, label in GAP_BUCKETS if label in per_bucket]
    spread = 0.0
    if len(ordered) > 1:
        spread = 100 * (ordered[-1]["fail_rate"] - ordered[0]["fail_rate"])

    print("\n=== VERDICT (bars set before the data was pulled) ===")
    pred = rate > PREDICT_MIN_FAIL
    fals = rate < FALSIFY_MAX_FAIL
    plac = spread >= PLACEBO_MIN_SPREAD
    print(f"  PREDICTION >{100*PREDICT_MIN_FAIL:.0f}% fail: "
          f"{'MET' if pred else 'NOT MET'} ({100*rate:.1f}%)")
    print(f"  FALSIFIER  <{100*FALSIFY_MAX_FAIL:.0f}% fail: "
          f"{'TRIGGERED - the premise is dead' if fals else 'not triggered'}")
    print(f"  PLACEBO    stalest bucket >={PLACEBO_MIN_SPREAD:.0f}pp WORSE than freshest: "
          f"{'HOLDS' if plac else 'FAILS'} ({spread:+.1f}pp, oldest minus newest)")
    if not plac and spread < 0:
        print(f"             -> and it runs BACKWARDS: the freshest As fail most.")
        print(f"                Short gaps are not random - the city came back early")
        print(f"                for a reason. Gap is confounded by cause of visit.")

    for src, wm in g.watermarks.items():
        print(f"\nwatermark {src}: {wm}" + (" - held" if not g.drift else f" DRIFT {g.drift}"))

    if a.json:
        Path(a.json).write_text(json.dumps({
            "paired": n, "censored": censored,
            "fail_score": FAIL_SCORE,
            "fail_rate": rate, "fail_lo": lo, "fail_hi": hi,
            "failed_n": len(failed),
            "median_next_score": med,
            "c_band_share": c_band / n,
            "by_gap": per_bucket,
            "by_origin": per_origin,
            "staleness_spread_pp": spread,
            "prereg": {"predict_min_fail": PREDICT_MIN_FAIL,
                       "falsify_max_fail": FALSIFY_MAX_FAIL,
                       "placebo_min_spread_pp": PLACEBO_MIN_SPREAD},
            "verdict": {"prediction_met": pred, "falsifier_triggered": fals,
                        "placebo_holds": plac},
        }, indent=2))
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
