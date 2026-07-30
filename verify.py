"""Independent cross-check of the JS pipeline.

The point is NOT to reimplement logic.js in Python — a transliteration would
agree by construction, which is the self-referential trap Cheatcode #22 is
about. Where there's a choice, this uses a DIFFERENT technique:

    JS                              pandas (here)
    ------------------------------  ---------------------------------------
    Map + string date comparison    sort_values + drop_duplicates(keep=last)
    regex numeric validation        to_numeric(errors="coerce") + null check
    manual multi-key sort           sort_values on a computed frame

Agreement between two different routes is evidence. Agreement between one
route and a copy of itself is not.

Run:  node dump-js-results.js > /tmp/js.json && python3 verify.py
Exits nonzero on any disagreement.
"""

import csv
import io
import json
import subprocess
import sys
from pathlib import Path

import pandas as pd

# Anchored to this file's directory so verify.py runs from anywhere,
# including the repo root.
HERE = Path(__file__).resolve().parent
CSV = HERE / "data/dairy_dataset.csv"
WINDOW_DAYS = 14

STOCK = "Quantity in Stock (liters/kg)"
THRESH = "Minimum Stock Threshold (liters/kg)"
KEY = ["Product Name", "Brand", "Location"]
MAX_ROWS_SHOWN = 20   # must match script.js

# Mirrors ORDER_COLUMNS in logic.js. Written out, not imported — a change
# over there must be made here on purpose, or this check stops being
# independent and starts agreeing by construction.
EXPORT_COLUMNS = [
    ("Product",        lambda r: r["Product Name"]),
    ("Brand",          lambda r: r["Brand"]),
    ("Location",       lambda r: r["Location"]),
    ("On hand",        lambda r: r["Quantity in Stock (liters/kg)"]),
    ("Min threshold",  lambda r: r["Minimum Stock Threshold (liters/kg)"]),
    ("Order quantity", lambda r: r["Reorder Quantity (liters/kg)"]),
    ("Storage",        lambda r: r["Storage Condition"]),
    ("Short by",       lambda r: round(r["_gap"])),
]


def strict_numeric(series):
    """Reject anything that isn't fully numeric.

    NOT just .isna() — pandas already turns 'N/A' into NaN, but leaves
    'unknown', '42 L' and '-5' looking perfectly valid. Verified: three of
    those four slip past an .isna() check.
    """
    as_str = series.astype(str).str.strip()
    looks_numeric = as_str.str.fullmatch(r"-?\d+(\.\d+)?")
    return pd.to_numeric(as_str.where(looks_numeric), errors="coerce")


def compute():
    df = pd.read_csv(CSV)
    n_columns = len(df.columns)   # BEFORE we add _date — counting after was a bug

    # ── snapshot: latest row per product x brand x location ──
    # Deliberately NOT groupby().last() — that returns the last non-null value
    # per column independently and stitches together rows that never existed.
    # sort + drop_duplicates keeps whole rows intact.
    df["_date"] = pd.to_datetime(df["Date"], errors="coerce")
    positions = (df.sort_values("_date", kind="mergesort")
                   .drop_duplicates(subset=KEY, keep="last")
                   .reset_index(drop=True))

    stock = strict_numeric(positions[STOCK])
    thresh = strict_numeric(positions[THRESH])
    expiry = pd.to_datetime(positions["Expiration Date"], errors="coerce")

    unreadable = stock.isna() | thresh.isna() | expiry.isna()
    negative = (stock < 0) | (thresh < 0)
    review = unreadable | negative

    usable = positions[~review].copy()
    u_stock, u_thresh = stock[~review], thresh[~review]
    usable["_severity"] = (u_thresh - u_stock) / u_thresh.where(u_thresh != 0)

    flagged = usable[u_stock < u_thresh].copy()
    flagged["_gap"] = (u_thresh - u_stock)[u_stock < u_thresh]
    flagged["_k"] = flagged["Product Name"] + "|" + flagged["Brand"] + "|" + flagged["Location"]
    flagged = flagged.sort_values(["_severity", "_gap", "_k"], ascending=[False, False, True])

    file_today = df["_date"].max()
    exp_usable = pd.to_datetime(usable["Expiration Date"], errors="coerce")
    days_left = (exp_usable - file_today).dt.days
    expiring = usable[days_left.between(0, WINDOW_DAYS)]

    k = lambda d: (d["Product Name"] + "|" + d["Brand"] + "|" + d["Location"]).tolist()

    # ── UI logic, derived independently ──
    # Group order comes from the DECLARED urgency ranking, not from counts and
    # not alphabetically. Written out here rather than imported, so a change to
    # logic.js has to be made here too — deliberately, not silently.
    storage_order = ["Frozen", "Refrigerated", "Polythene Packet", "Tetra Pack", "Ambient"]
    rank = {s: i for i, s in enumerate(storage_order)}
    present = flagged["Storage Condition"].unique().tolist()
    ordered_groups = sorted(present, key=lambda s: (rank.get(s, len(storage_order)), s))
    group_order = [{"storage": s, "count": int((flagged["Storage Condition"] == s).sum())}
                   for s in ordered_groups]
    per_group_cap = max(5, -(-MAX_ROWS_SHOWN // len(ordered_groups)))   # ceil div
    group_shown = {s: k(flagged[flagged["Storage Condition"] == s].head(per_group_cap))
                   for s in ordered_groups}

    per_location = {loc: k(flagged[flagged["Location"] == loc])
                    for loc in flagged["Location"].unique()}

    # CSV built with Python's stdlib csv writer — a genuinely different
    # implementation from the hand-rolled csvCell() in logic.js. If they
    # produce identical bytes, the quoting is right in both.
    def to_csv(frame):
        buf = io.StringIO()
        w = csv.writer(buf, lineterminator="\r\n")
        w.writerow([c[0] for c in EXPORT_COLUMNS])
        for _, row in frame.iterrows():
            w.writerow([fn(row) for _, fn in EXPORT_COLUMNS])
        return buf.getvalue()

    return {
        "rows": len(df),
        "columns": n_columns,
        "positions": len(positions),
        "flagged": len(flagged),
        "expiring": len(expiring),
        "review": int(review.sum()),
        "file_today": file_today.date().isoformat(),
        "flagged_keys": sorted(k(flagged)),
        "expiring_keys": sorted(k(expiring)),
        "position_keys": sorted(k(positions)),
        "by_location": flagged["Location"].value_counts().to_dict(),
        "by_storage": flagged["Storage Condition"].value_counts().to_dict(),
        "top20": k(flagged.head(MAX_ROWS_SHOWN)),
        "group_order": group_order,
        "group_shown": group_shown,
        "per_location": per_location,
        "csv_all": to_csv(flagged),
        "csv_haryana": to_csv(flagged[flagged["Location"] == "Haryana"]),
        "top5": [
            {"key": r, "severity": round(s, 6)}
            for r, s in zip(k(flagged.head(5)), flagged.head(5)["_severity"])
        ],
    }


def main():
    js = json.loads(subprocess.run(
        ["node", str(HERE / "dump-js-results.js")],
        capture_output=True, text=True, check=True).stdout)
    py = compute()

    failures = []

    def cmp(label, a, b, show=None):
        ok = a == b
        print(f"{'PASS' if ok else 'FAIL'}  {label}")
        if not ok:
            failures.append(label)
            print(f"      js: {show(a) if show else a}")
            print(f"      py: {show(b) if show else b}")
        elif not isinstance(a, (list, dict)):
            print(f"      → {a}")

    print("=== scalars ===")
    for f in ["rows", "columns", "positions", "flagged", "expiring", "review", "file_today"]:
        cmp(f, js[f], py[f])

    print("\n=== sets (which rows, not just how many) ===")
    for f in ["position_keys", "flagged_keys", "expiring_keys"]:
        ok = js[f] == py[f]
        print(f"{'PASS' if ok else 'FAIL'}  {f} ({len(js[f])} vs {len(py[f])})")
        if not ok:
            failures.append(f)
            only_js = sorted(set(js[f]) - set(py[f]))
            only_py = sorted(set(py[f]) - set(js[f]))
            if only_js: print(f"      only in js ({len(only_js)}): {only_js[:5]}")
            if only_py: print(f"      only in py ({len(only_py)}): {only_py[:5]}")

    print("\n=== breakdowns ===")
    cmp("by_location", js["by_location"], py["by_location"])
    cmp("by_storage", js["by_storage"], py["by_storage"])

    print("\n=== ranking (order, not just membership) ===")
    cmp("top5", js["top5"], py["top5"],
        show=lambda t: " ".join(f"{x['key'].split('|')[0]}:{x['severity']}" for x in t))

    print("\n=== UI logic ===")
    cmp("top20 (the 20 rows rendered, in order)", js["top20"], py["top20"],
        show=lambda t: f"{len(t)} rows, first={t[0] if t else None}")
    cmp("group_order (declared urgency, not alphabetical)", js["group_order"], py["group_order"],
        show=lambda g: " ".join(f"{x['storage']}({x['count']})" for x in g))
    cmp("group_shown (rows after the per-group cap)", js["group_shown"], py["group_shown"],
        show=lambda g: " ".join(f"{s}:{len(v)}" for s, v in g.items()))

    ok_loc = js["per_location"] == py["per_location"]
    print(f"{'PASS' if ok_loc else 'FAIL'}  per_location ({len(js['per_location'])} locations, "
          f"each slice compared row-by-row)")
    if not ok_loc:
        failures.append("per_location")
        for loc in sorted(set(js["per_location"]) | set(py["per_location"])):
            a, b = js["per_location"].get(loc, []), py["per_location"].get(loc, [])
            if a != b:
                print(f"      {loc}: js={len(a)} py={len(b)} | only-js={sorted(set(a)-set(b))[:3]}")

    print("\n=== exported bytes (hand-rolled JS quoting vs python stdlib csv) ===")
    for f in ["csv_all", "csv_haryana"]:
        ok = js[f] == py[f]
        print(f"{'PASS' if ok else 'FAIL'}  {f} ({len(js[f])} vs {len(py[f])} bytes)")
        if not ok:
            failures.append(f)
            a, b = js[f].splitlines(), py[f].splitlines()
            for i, (x, y) in enumerate(zip(a, b)):
                if x != y:
                    print(f"      first diff at line {i}:\n        js: {x!r}\n        py: {y!r}")
                    break
            else:
                print(f"      line counts differ: js={len(a)} py={len(b)}")

    print(f"\n{'DISAGREEMENT: ' + ', '.join(failures) if failures else 'Two independent implementations agree.'}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
