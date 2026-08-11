#!/usr/bin/env python3
"""
The contractor theory, tested against the building's own record.

THE CLAIM UNDER TEST (pre-registered, before any DOB row is pulled):
our re-inspection join showed facility violations (building problems) persist
at ~1.6x the rate of practice violations (behavior). The published so-what
said the difference is MONEY - "one you fix with a staff meeting, the other
with a contractor and money you don't have" - and was flagged as inference,
not measurement. If it is right, facility persistence should be HIGHER for
restaurants sitting in buildings that already had open DOB violations before
the inspection window, because a troubled building marks a landlord or a
structure the restaurant cannot fix alone.

  PREDICTION:  facility persistence, troubled buildings - clean buildings
               >= +5 points.
  PLACEBO:     practice persistence should NOT move with the building
               (staff behavior does not need the landlord): |diff| < 5 points.
  FALSIFIERS:  facility diff < 5 points -> this test does NOT support the
               contractor story; say so and keep the published hedge.
               practice moves as much as facility -> whatever moved is
               operator/neighborhood quality, not building dependence, and
               the theory is CONFOUNDED, not confirmed.

TREATMENT definition: the building (bin) has >= 1 DOB violation that is
still ACTIVE and was ISSUED before the pair window opens (issue_date
<= PRE_CUTOFF), i.e. the building was already chronically troubled before
any outcome we measure. Issued-later violations are excluded from the
treatment so the arrow cannot run backward (a failed restaurant attracting
complaints that become DOB violations).

Pairing logic mirrors reinspect_join.py (same window, same classifier,
same per-citation persistence definition) so the split is comparable to
the published 6,990-pair headline.

Runs entirely on pull.Guarded - watermark drift checks, sentinel fences,
grouped auto-pagination, 429 retry - for BOTH datasets.

Usage:  python3 dob_contractor_test.py [--window 120] [--json out.json]
"""

import argparse
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull import Guarded                                       # noqa: E402
from reinspect_join import (INITIAL, REINSP, FAIL_SCORE, classify)  # noqa: E402

PRE_CUTOFF = "20230801"   # pairs live in the rolling ~3yr window from late 2023;
                          # treatment = building trouble that predates all of it
BIN_BATCH = 100           # bins per DOB in(...) query


def wilson_diff_note(p1, n1, p2, n2):
    """Normal-approx 95% CI on (p1-p2), printed so the reader sees width."""
    if not n1 or not n2:
        return "n/a"
    se = math.sqrt(p1 * (1 - p1) / n1 + p2 * (1 - p2) / n2)
    d = p1 - p2
    return f"{d*100:+.1f}pp (95% CI {100*(d-1.96*se):+.1f} .. {100*(d+1.96*se):+.1f})"


def build_pairs(g, window_days):
    """Same construction as reinspect_join.py, plus bin carried per camis."""
    rows = g.agg(**{
        "$select": ("camis, inspection_date, inspection_type, violation_code, "
                    "max(score) AS score_v, max(bin) AS bin_v"),
        "$where": f"inspection_type in ('{INITIAL}', '{REINSP}') AND violation_code IS NOT NULL",
        "$group": "camis, inspection_date, inspection_type, violation_code",
    })
    print(f"violation-grain rows: {len(rows):,}", file=sys.stderr)

    desc_rows = g.agg(paginate=False, **{
        "$select": "violation_code, max(violation_description) AS descr",
        "$where": "violation_code IS NOT NULL",
        "$group": "violation_code", "$limit": 400,
    })
    klass = {r["violation_code"]: classify(r.get("descr", "")) for r in desc_rows}

    insp = defaultdict(lambda: {"codes": set(), "score": None})
    cam_bin = {}
    for r in rows:
        key = (r["camis"], r["inspection_date"][:10], r["inspection_type"])
        insp[key]["codes"].add(r["violation_code"])
        s = r.get("score_v")
        if s is not None:
            insp[key]["score"] = float(s)
        b = r.get("bin_v")
        if b:
            cam_bin[r["camis"]] = b

    by_camis = defaultdict(list)
    for (camis, d, t), v in insp.items():
        by_camis[camis].append((datetime.fromisoformat(d), t, v))
    for v in by_camis.values():
        v.sort(key=lambda x: x[0])

    pairs = []
    window = timedelta(days=window_days)
    for camis, timeline in by_camis.items():
        for i, (d0, t0, v0) in enumerate(timeline):
            if t0 != INITIAL or (v0["score"] or 0) < FAIL_SCORE:
                continue
            for d1, t1, v1 in timeline[i + 1:]:
                if d1 - d0 > window or t1 == INITIAL:
                    break
                if t1 == REINSP:
                    pairs.append({"camis": camis,
                                  "init_codes": v0["codes"], "re_codes": v1["codes"]})
                    break
    return pairs, cam_bin, klass


def troubled_bins(gd, bins):
    """bin -> count of ACTIVE DOB violations issued before PRE_CUTOFF."""
    bins = sorted(bins)
    out = {}
    for i in range(0, len(bins), BIN_BATCH):
        chunk = bins[i:i + BIN_BATCH]
        inlist = ",".join(f"'{b}'" for b in chunk)
        rows = gd.agg(paginate=False, **{
            "$select": "bin, count(*) AS n_active",
            "$where": (f"bin in({inlist}) AND violation_category like '%ACTIVE%' "
                       f"AND issue_date <= '{PRE_CUTOFF}'"),
            "$group": "bin", "$limit": str(BIN_BATCH + 1),
        })
        for r in rows:
            out[r["bin"]] = int(float(r["n_active"]))
        done = min(i + BIN_BATCH, len(bins))
        print(f"  DOB probe {done}/{len(bins)} bins", file=sys.stderr)
    return out


def persistence(pairs, klass, member):
    """Per-citation persistence by class, over pairs where member(camis)."""
    cited = defaultdict(int)
    kept = defaultdict(int)
    n_pairs = 0
    for p in pairs:
        if not member(p["camis"]):
            continue
        n_pairs += 1
        for c in p["init_codes"]:
            k = klass.get(c, "other")
            cited[k] += 1
            if c in p["re_codes"]:
                kept[k] += 1
    rate = {k: (kept[k] / cited[k] if cited[k] else None) for k in ("facility", "practice")}
    return n_pairs, cited, kept, rate


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=int, default=120)
    ap.add_argument("--json", metavar="PATH")
    a = ap.parse_args()

    print("PRE-REGISTERED before pulling DOB:", file=sys.stderr)
    print("  predict: facility persistence (troubled - clean) >= +5pp", file=sys.stderr)
    print("  placebo: practice |diff| < 5pp", file=sys.stderr)

    g = Guarded("restaurants", strict=True)
    pairs, cam_bin, klass = build_pairs(g, a.window)
    print(f"pairs: {len(pairs):,}", file=sys.stderr)

    paired_camis = {p["camis"] for p in pairs}
    with_bin = {c: cam_bin[c] for c in paired_camis if c in cam_bin}
    no_bin = len(paired_camis) - len(with_bin)
    print(f"paired restaurants: {len(paired_camis):,} ({no_bin:,} lack bin -> excluded)",
          file=sys.stderr)

    gd = Guarded("dob", strict=True)
    active = troubled_bins(gd, set(with_bin.values()))

    def is_troubled(camis):
        return active.get(with_bin.get(camis), 0) >= 1

    trbl = {c for c in with_bin if is_troubled(c)}
    clean = {c for c in with_bin if not is_troubled(c)}

    nT, citedT, keptT, rT = persistence(pairs, klass, lambda c: c in trbl)
    nC, citedC, keptC, rC = persistence(pairs, klass, lambda c: c in clean)

    print()
    print(f"TROUBLED buildings (>=1 ACTIVE DOB violation issued pre-{PRE_CUTOFF[:4]}): "
          f"{len(trbl):,} restaurants, {nT:,} pairs")
    print(f"CLEAN buildings: {len(clean):,} restaurants, {nC:,} pairs")
    print()
    hdr = f"{'':<26}{'troubled':>12}{'clean':>12}{'difference':>34}"
    print(hdr)
    results = {}
    for k in ("facility", "practice"):
        pT, pC = rT[k], rC[k]
        diff = wilson_diff_note(pT, citedT[k], pC, citedC[k])
        print(f"{k + ' persistence':<26}"
              f"{'' if pT is None else f'{pT*100:.1f}%':>12}"
              f"{'' if pC is None else f'{pC*100:.1f}%':>12}"
              f"{diff:>34}")
        print(f"{'  (persisted/cited)':<26}"
              f"{f'{keptT[k]}/{citedT[k]}':>12}{f'{keptC[k]}/{citedC[k]}':>12}")
        results[k] = {"troubled": pT, "clean": pC,
                      "troubled_n": citedT[k], "clean_n": citedC[k]}

    fac_d = (rT["facility"] or 0) - (rC["facility"] or 0)
    pra_d = (rT["practice"] or 0) - (rC["practice"] or 0)
    print()
    print("VERDICT against the pre-registered bar:")
    fac_hit = fac_d >= 0.05
    pla_ok = abs(pra_d) < 0.05
    if fac_hit and pla_ok:
        v = ("SUPPORTED: facility persistence moves with the building and practice "
             "does not. The contractor sentence can lose its hedge.")
    elif fac_hit and not pla_ok:
        v = ("CONFOUNDED: practice moved too - troubled buildings host generally "
             "worse operators (or neighborhoods). This does NOT isolate money.")
    else:
        v = ("NOT SUPPORTED: facility persistence does not move >= 5pp with prior "
             "building trouble. The published hedge stays.")
    print("  " + v)

    if a.json:
        Path(a.json).write_text(json.dumps({
            "pre_cutoff": PRE_CUTOFF, "window_days": a.window,
            "pairs": len(pairs), "no_bin": no_bin,
            "troubled_restaurants": len(trbl), "clean_restaurants": len(clean),
            "rates": results, "facility_diff": fac_d, "practice_diff": pra_d,
            "verdict": v,
        }, indent=2))
        print(f"wrote {a.json}", file=sys.stderr)


if __name__ == "__main__":
    main()
