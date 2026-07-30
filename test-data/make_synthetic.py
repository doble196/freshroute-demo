"""
Synthetic test-data creator — seeded, declared, reproducible.

Reusable core:
    make_vendors(brands, seed)          -> clean vendor reference DataFrame
    inject_dirt(df, faults, id_col)     -> (dirty_df, manifest_df)   <- generic,
                                           works on ANY DataFrame, use it later
                                           for any fixture you need.

Outputs (running this file):
    ../data/vendors.csv            clean vendor reference (SYNTHETIC — declared)
    messy_vendors.csv              vendor table with every dirt type injected
    messy_vendor_stock.csv         stock rows exercising the vendor JOIN
    dirt_manifest.csv              one row per injected fault: file, row, column,
                                   value, guard, expected outcome. The JS test
                                   asserts against THIS, not against hand-memory.

Scientist rules applied:
  - SEEDED: same seed -> byte-identical output. No Date.now, no unseeded random.
  - DECLARED: every fault is a row in the FAULTS table below with a stated
    guard and expectation. A fault without a stated job doesn't get injected.
  - BOUNDED: values drawn from the REAL dataset's observed ranges
    (price 10-100, reorder 20-200) so the shape is realistic; the values are
    invented — SYNTHETIC per logic.js SOURCE_KINDS, never safe to act on.
"""

import random
import pandas as pd
from pathlib import Path

HERE = Path(__file__).parent
SEED = 20260729  # date-stamped so a regeneration is an explicit, visible choice

# The 11 real brands from dairy_dataset.csv — vendor names must match the
# stock file's Brand column or every join test would test the fixture.
BRANDS = ["Amul", "Mother Dairy", "Raj", "Sudha", "Dodla Dairy", "Palle2patnam",
          "Dynamix Dairies", "Warana", "Parag Milk Foods", "Passion Cheese",
          "Britannia Industries"]

VCOLS = ["Vendor", "Address", "Order Cutoff", "Case Size (units)", "Discount (%)",
         "Lead Mon", "Lead Tue", "Lead Wed", "Lead Thu", "Lead Fri", "Lead Sat", "Lead Sun"]


def make_vendors(brands=BRANDS, seed=SEED):
    """Clean vendor reference table. Every field valid; weekend leads longer
    (a vendor that ships Saturday orders Monday), one vendor closed Sunday."""
    rng = random.Random(seed)
    rows = []
    for i, b in enumerate(brands):
        base = rng.randint(1, 3)                       # weekday lead, days
        cutoff = rng.choice(["11:00", "12:30", "14:00", "15:30"])
        case = rng.choice([6, 12, 24, 48])
        disc = rng.choice([0, 2.5, 5, 7.5, 10])
        leads = [base, base, base, base, base + 1, base + 2, base + 2]
        if i == len(brands) - 1:                       # last vendor: no Sunday processing
            leads[6] = ""                              # blank = closed, by declared convention
        rows.append({
            "Vendor": b,
            # commas on purpose: an address is the field most likely to break
            # a naive CSV writer — csvCell() must quote it (RFC 4180).
            "Address": f"{rng.randint(2, 98)} Dairy Rd, Sector {rng.randint(1, 40)}, {rng.choice(['Pune', 'Anand', 'Karnal', 'Erode'])}",
            "Order Cutoff": cutoff,
            "Case Size (units)": case,
            "Discount (%)": disc,
            **dict(zip(["Lead Mon", "Lead Tue", "Lead Wed", "Lead Thu", "Lead Fri", "Lead Sat", "Lead Sun"], leads)),
        })
    return pd.DataFrame(rows, columns=VCOLS)


def inject_dirt(df, faults, id_col):
    """THE reusable function. Copy a base row per fault, corrupt ONE cell,
    record what/where/why. Returns (dirty_df, manifest_df).

    faults: list of dicts {base: value in id_col to copy, rename: new id,
            column: cell to corrupt (None = leave clean control),
            value: the dirt, guard: category, expect: outcome, note: job}
    Works on any DataFrame — nothing here is vendor-specific.
    """
    out, manifest = [], []
    for n, f in enumerate(faults, start=1):
        row = df[df[id_col] == f["base"]].iloc[0].copy()
        if f.get("rename"):
            row[id_col] = f["rename"]
        if f.get("column"):
            row[f["column"]] = f["value"]
        if f.get("extra"):                 # multi-cell faults (e.g. dupe pair)
            for c, v in f["extra"].items():
                row[c] = v
        out.append(row)
        manifest.append({
            "row": n, "id": row[id_col],
            "column": f.get("column") or "(none — control)",
            "value": f.get("value", ""), "guard": f["guard"],
            "expect": f["expect"], "note": f["note"],
        })
    return pd.DataFrame(out).reset_index(drop=True), pd.DataFrame(manifest)


# ── The fault catalog: every row exists to prove ONE specific thing ─────────
# LAW: a vendor name appears on more than one row ONLY when collision IS the
# job (fold / conflict / dedupe pairs). Single-field faults get a unique
# "#tagged" name, or they'd collide into accidental repeat-conflicts and the
# row would stop proving its stated point.
VENDOR_FAULTS = [
    # controls — keys that the join tests and weekday tests depend on
    dict(base="Amul", guard="control", expect="clean",
         note="valid vendor — must join and compute; the control that must NOT be flagged"),
    dict(base="Britannia Industries", guard="control", expect="clean",
         note="valid vendor whose Lead Sun is blank = closed Sunday; ordering Sunday -> review, Monday -> clean"),

    # pairs — collision is the point
    dict(base="Mother Dairy", guard="spelling", expect="fold-base",
         note="clean base the variant below must fold ONTO"),
    dict(base="Mother Dairy", rename=" mother dairy ", guard="spelling", expect="fold",
         note="case/whitespace variant folds onto Mother Dairy; must NOT create an extra vendor"),
    dict(base="Raj", guard="repeats", expect="conflict-base",
         note="clean base of the discount-conflict pair"),
    dict(base="Raj", column="Discount (%)", value="2.0", guard="repeats", expect="conflict",
         note="same vendor, different discount — keep the LOWER (honest cost estimate), report it"),
    dict(base="Sudha", guard="repeats", expect="dedupe-base",
         note="clean base of the byte-identical pair"),
    dict(base="Sudha", guard="repeats", expect="dedupe",
         note="byte-identical duplicate — silently collapses to one; the join must NOT multiply order lines"),

    # single-field faults — unique names, one corrupted cell each
    dict(base="Dodla Dairy", rename="Dodla Dairy#case-blank", column="Case Size (units)", value="",
         guard="blanks", expect="review", note="blank case size -> review; must not divide by nothing"),
    dict(base="Palle2patnam", rename="Palle2patnam#disc-na", column="Discount (%)", value="N/A",
         guard="blanks", expect="review", note="a WORD meaning empty is caught, not just an empty cell"),
    dict(base="Dynamix Dairies", rename="Dynamix Dairies#lead-unit", column="Lead Mon", value="3 days",
         guard="types", expect="review", note="unit smuggled into a number — parseFloat would return 3"),
    dict(base="Warana", rename="Warana#disc-pct", column="Discount (%)", value="10%",
         guard="types", expect="review", note="percent sign smuggled in — same trap, other column"),
    dict(base="Parag Milk Foods", rename="Parag#case-neg", column="Case Size (units)", value="-6",
         guard="types", expect="review", note="negative case size is impossible, not merely small"),
    dict(base="Passion Cheese", rename="Passion#case-zero", column="Case Size (units)", value="0",
         guard="types", expect="review", note="zero case size -> ceil(q/0) is Infinity; the division guard"),
    dict(base="Dodla Dairy", rename="Dodla#case-half", column="Case Size (units)", value="12.5",
         guard="types", expect="review", note="half a case does not exist; integers only"),
    dict(base="Palle2patnam", rename="Palle2patnam#disc-150", column="Discount (%)", value="150",
         guard="bounds", expect="review", note="discount >100% means being paid to take stock — bounds check"),
    dict(base="Dynamix Dairies", rename="Dynamix#disc-100", column="Discount (%)", value="100",
         guard="bounds", expect="review", note="exactly 100% = free goods — a red-flag boundary, review not accept"),
    dict(base="Warana", rename="Warana#cutoff-2599", column="Order Cutoff", value="25:99",
         guard="types", expect="review", note="impossible clock time"),
    dict(base="Parag Milk Foods", rename="Parag#cutoff-word", column="Order Cutoff", value="noon",
         guard="types", expect="review", note="a word where HH:MM belongs"),
    dict(base="Passion Cheese", rename="Passion#lead-45", column="Lead Fri", value="45",
         guard="bounds", expect="review", note="45-day lead is a magnitude red flag (>30) — investigate, not accept"),
    dict(base="Dodla Dairy", rename="Dodla#lead-neg", column="Lead Sat", value="-1",
         guard="types", expect="review", note="negative lead time — arrives before you order it"),
    dict(base="Palle2patnam", rename="Palle2patnam#addr", column="Address",
         value='Plot 7, "Gate B", Milk Colony, Pune', guard="quoting", expect="clean",
         note="comma AND quotes in address — must survive the CSV round trip intact"),
]

# Stock rows that exercise the JOIN — realistic ranges from the real file.
STOCK_FAULTS_COLS = ["Location", "Date", "Product Name", "Brand",
                     "Price per Unit", "Quantity in Stock (liters/kg)",
                     "Minimum Stock Threshold (liters/kg)", "Reorder Quantity (liters/kg)"]

def make_join_stock(vendors):
    """Expected units/cases are COMPUTED from the vendor table, never
    hand-written — a manifest that disagrees with its own fixture is worse
    than no manifest. The JS test asserts against these columns."""
    import math
    case = int(vendors.loc[vendors["Vendor"] == "Amul", "Case Size (units)"].iloc[0])

    def cases_for(reorder):
        n = math.ceil(reorder / case)
        return n, n * case

    rows = [
        # control: joins Amul; reorder 100 rounds UP to whole cases
        ["Haryana", "2022-12-01", "Milk", "Amul", "42.61", "5", "50", "100"],
        # unknown vendor: flagged for reorder but NO vendor record -> vendor review, not a crash
        ["Kerala", "2022-12-01", "Ghee", "Nandini", "85.72", "5", "50", "100"],
        # spelling: 'AMUL' must fold onto Amul and still join
        ["Delhi", "2022-12-01", "Curd", "AMUL", "30.00", "5", "50", "100"],
        # one unit past a case boundary must round UP, never down
        ["Punjab", "2022-12-01", "Butter", "Amul", "99.99", "5", "50", str(case + 1)],
    ]
    c100, u100 = cases_for(100)
    cover, uover = cases_for(case + 1)
    manifest = pd.DataFrame([
        {"row": 1, "id": "Amul/Milk", "column": "(none — control)", "value": "",
         "guard": "join", "expect": "clean", "expected_units": u100, "expected_cases": c100,
         "note": f"clean join: reorder 100 @ case {case} -> {u100} units, {c100} cases"},
        {"row": 2, "id": "Nandini/Ghee", "column": "Brand", "value": "Nandini",
         "guard": "join", "expect": "review", "expected_units": "", "expected_cases": "",
         "note": "no vendor record — review, never a silent unpriced order"},
        {"row": 3, "id": "AMUL/Curd", "column": "Brand", "value": "AMUL",
         "guard": "spelling", "expect": "clean", "expected_units": u100, "expected_cases": c100,
         "note": "brand variant folds and still joins"},
        {"row": 4, "id": "Amul/Butter", "column": "Reorder Quantity (liters/kg)", "value": str(case + 1),
         "guard": "join", "expect": "clean", "expected_units": uover, "expected_cases": cover,
         "note": f"{case + 1} @ case {case} -> {uover} units {cover} cases, NOT {case} — cases round UP"},
    ])
    return pd.DataFrame(rows, columns=STOCK_FAULTS_COLS), manifest


if __name__ == "__main__":
    vendors = make_vendors()
    vendors.to_csv(HERE.parent / "data" / "vendors.csv", index=False)

    messy, manifest_v = inject_dirt(vendors, VENDOR_FAULTS, id_col="Vendor")
    messy.to_csv(HERE / "messy_vendors.csv", index=False)

    stock, manifest_s = make_join_stock(vendors)
    stock.to_csv(HERE / "messy_vendor_stock.csv", index=False)

    manifest_v["file"] = "messy_vendors.csv"
    manifest_s["file"] = "messy_vendor_stock.csv"
    manifest = pd.concat([manifest_v, manifest_s], ignore_index=True)
    manifest.to_csv(HERE / "dirt_manifest.csv", index=False)

    print(f"vendors.csv           {len(vendors)} clean vendors (SYNTHETIC, seed {SEED})")
    print(f"messy_vendors.csv     {len(messy)} rows, every one with a stated job")
    print(f"messy_vendor_stock.csv {len(stock)} join-test rows")
    print(f"dirt_manifest.csv     {len(manifest)} declared faults")
    print()
    print(manifest[["file", "row", "id", "guard", "expect"]].to_string(index=False))
