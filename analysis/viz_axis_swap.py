#!/usr/bin/env python3
"""
The axis-swap test: does putting score on x and inspections on y make the
chart's visual grammar match the mechanism?

The problem it addresses: readers parse x -> y as cause -> effect. The
original chart plots inspections on x and score on y, so its layout argues
"inspections make restaurants worse" while the measured mechanism runs the
other way (DOHMH re-inspects any initial >=14 by rule; restaurants that ever
scored >=14 average 1.69 inspections vs 1.04). A title can contradict a
layout, but the layout is what a reader absorbs in the first two seconds.

So: bucket by SCORE BAND on x, plot median inspections on y. Same data, same
grain, same window — only the axis assignment changes.

Honest note on what this does NOT fix: swapping axes does not establish
causality either. It aligns the visual grammar with a mechanism already known
from the enforcement rule. If the rule were unknown, this chart would be just
as capable of implying the reverse.

Usage: python3 viz_axis_swap.py  -> axis_swap.png
"""

import sys
import statistics as st
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pull import Guarded                                       # noqa: E402

import matplotlib                                              # noqa: E402
matplotlib.use("Agg")
import matplotlib.pyplot as plt                                # noqa: E402

HERE = Path(__file__).resolve().parent
SURFACE, INK, INK2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e2"
BLUE, GRAY = "#2a78d6", "#b9b8b3"

# Score bands from DOHMH's own grading scale — not invented cut points.
BANDS = [("0-13\n(A range)", 0, 14), ("14-27\n(B range)", 14, 28),
         ("28-40\n(C range)", 28, 41), ("41+\n(worst)", 41, 10**6)]


def main():
    g = Guarded("restaurants", strict=True)
    today = date.today()
    hi = date(today.year, today.month, 1)
    lo = date(hi.year - 1, hi.month, 1)
    W = (f"inspection_date >= '{lo}T00:00:00' AND inspection_date < '{hi}T00:00:00' "
         f"AND score IS NOT NULL")

    rows = g.agg(**{"$select": "camis, inspection_date, min(score) AS s",
                    "$where": W, "$group": "camis, inspection_date"})
    R = defaultdict(list)
    for r in rows:
        R[r["camis"]].append(float(r["s"]))

    # One point per restaurant: its WORST score (the trigger the rule acts on)
    # and how many inspections it received.
    rest = [{"worst": max(v), "freq": len(v)} for v in R.values()]
    print(f"{len(rest):,} restaurants, {len(rows):,} inspections", file=sys.stderr)

    pts = []
    for lab, lo_s, hi_s in BANDS:
        sub = [r["freq"] for r in rest if lo_s <= r["worst"] < hi_s]
        if len(sub) >= 25:
            pts.append((lab, st.median(sub), sum(sub) / len(sub), len(sub)))

    fig, ax = plt.subplots(figsize=(8.6, 5.0), dpi=150)
    fig.patch.set_facecolor(SURFACE); ax.set_facecolor(SURFACE)
    xs = list(range(len(pts)))
    ax.plot(xs, [p[2] for p in pts], color=BLUE, lw=2.6, marker="o", ms=7, zorder=5)
    for i, (lab, med, mean, n) in enumerate(pts):
        ax.annotate(f"{mean:.2f}", (i, mean), xytext=(0, 10), textcoords="offset points",
                    ha="center", fontsize=10, color=BLUE, fontweight="bold")
        ax.annotate(f"n={n:,}", (i, mean), xytext=(0, -16), textcoords="offset points",
                    ha="center", fontsize=7.5, color=INK2)
    ax.axvline(0.5, color=GRAY, lw=1, ls=(0, (4, 3)), zorder=2)
    ax.set_xticks(xs); ax.set_xticklabels([p[0] for p in pts], fontsize=9, color=INK2)
    ax.set_xlim(-0.4, len(pts) - 0.6)
    ax.set_xlabel("Worst inspection score the restaurant received  →  (the CAUSE)",
                  fontsize=10, color=INK)
    ax.set_ylabel("Mean inspections received  (the EFFECT)", fontsize=10, color=INK)
    # Zero baseline. The climb is 1.04 -> 2.18, a genuine doubling, and it
    # reads as a doubling from zero. Letting the axis start at 1.0 would make
    # the same numbers fill the panel — the exact lever documented two tabs
    # over on the public site. Consistency is the whole point.
    ax.set_ylim(0, max(p[2] for p in pts) * 1.25)
    ax.yaxis.grid(True, color=GRID, lw=0.8); ax.set_axisbelow(True)
    for s_ in ax.spines.values():
        s_.set_visible(False)
    ax.tick_params(colors=INK2, length=0, labelsize=9)
    # sit the rule note ABOVE the line, clear of the n= labels below each point
    ax.annotate("DOHMH re-inspects any\ninitial scoring ≥14  →", (0.46, 0.80),
                xycoords=("data", "axes fraction"), fontsize=8.5, color=INK2, ha="right")
    ax.set_title("Scoring worse gets you inspected more — the axes now run in the "
                 "direction the rule does", fontsize=12, color=INK, loc="left", pad=30)
    ax.text(0, 1.035, f"Same data, same window ({lo:%Y-%m}..{hi:%Y-%m} excl), same grain as the "
            "facet chart — only the axis assignment changed. Score bands are DOHMH's own grading cuts.",
            transform=ax.transAxes, fontsize=8, color=INK2)
    fig.tight_layout()
    fig.savefig(HERE / "axis_swap.png", facecolor=SURFACE, bbox_inches="tight")

    for lab, med, mean, n in pts:
        print(f"  {lab.splitlines()[0]:<8} mean {mean:.2f} inspections  median {med:.0f}  n={n:,}")
    print("wrote axis_swap.png")


if __name__ == "__main__":
    main()
