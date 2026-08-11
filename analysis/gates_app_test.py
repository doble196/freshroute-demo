#!/usr/bin/env python3
"""The gates that cover the two shipped browser apps.

Split out of gates_test.py so it runs with NO dependency on the openFDA
provider or the console build - which means the public repo can ship it beside
the pages it checks, and a reader can actually run it:

    python3 gates_app_test.py

Three gates, each one a real failure that already happened:

  GUARD 10  check.html cannot import pull.Guarded, so its protections were
            hand-rewritten in JavaScript. Two implementations of one rule set
            drift silently - change a grade band in Python and the live page
            keeps showing the old threshold, both claiming to be "the city's".

  GUARD 11  (a) These pages ship with no <meta charset>, so a single non-ASCII
            byte renders as mojibake. Broken three times: mojibake, entities
            printed as literal text, and a smart quote typed into a JS string.
            (b) "Handle errors" collapsing back into one catch block is how a
            200 carrying an error body once rendered as "no restaurant matched"
            - an outage printed as reassurance.

  GUARD 12  operator.html ranks violations by rates it cannot compute in a
            browser, so they ship EMBEDDED. Rerun the analysis, forget the
            page, and it keeps quoting last month's rates with this month's
            confidence. Nothing about the page would look wrong.

Every gate is paired with a negative test that proves it FIRES. A guard that
only ever passes on clean input proves nothing (Cheatcode #22).
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))


def find(name):
    """Locate a shipped page in either repo layout.

    War room: scripts and pages share a folder. Public repo: evidence in
    analysis/, pages in data-app/. Handling both here is what lets these files
    stay byte-identical across the two repos - and a copy that has to be edited
    per repo is a copy that drifts per repo.
    """
    for c in (HERE / name, HERE.parent / "data-app" / name):
        if c.exists():
            return c
    sys.exit(f"cannot find {name} beside {Path(__file__).name} or in ../data-app/")


P = F = 0


def check(label, cond, detail=""):
    global P, F
    P, F = (P + 1, F) if cond else (P, F + 1)
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n      -> {detail}" if detail else ""))


# ── GUARD 10: the browser guard must not drift from the Python guard ──────
# check.html cannot import pull.Guarded — a Python module does not run in a
# browser tab — so its protections were hand-rewritten in JavaScript. Two
# implementations of one rule set drift silently: change a grade band in the
# Python chart and the live page keeps showing the old threshold, with both
# claiming to be "the city's scale". This gate makes that drift fail loudly.
print("\n=== GUARD 10: JS/Python guard parity (the duplicated-rules risk) ===")

def parity(js_text):
    """Mismatches between the browser rules and the Python rules. Empty = agree."""
    ds = (HERE / "datasets.py").read_text()
    vz = (HERE / "viz_axis_swap.py").read_text()
    bad = []

    # 1. same dataset
    m = re.search(r"resource/([0-9a-z]{4}-[0-9a-z]{4})\.json", js_text)
    js_id = m.group(1) if m else None
    if js_id not in re.findall(r'"fourby":\s*"([0-9a-z-]+)"', ds):
        bad.append(f"dataset {js_id!r} is not in the Python registry")

    # 2. same null-date sentinel. Python fences with a > comparison one day
    #    past the sentinel; the browser compares the sentinel date itself.
    m = re.search(r'"sentinel_where":\s*"inspection_date > \'(1900-\d\d-\d\d)', ds)
    py_fence = m.group(1) if m else None
    js_sent = set(re.findall(r'"(1900-\d\d-\d\d)"', js_text))
    if not py_fence:
        bad.append("Python sentinel fence for inspection_date not found")
    elif not js_sent:
        bad.append("browser drops no 1900-xx-xx sentinel at all")
    elif py_fence[:7] != next(iter(js_sent))[:7]:
        bad.append(f"sentinel month differs: python {py_fence} vs js {js_sent}")

    # 3. same grade cut points. Python bands are half-open [lo, hi); the
    #    browser states them inclusive, so hi_js == hi_py - 1.
    js_b = {g: (int(lo), int(hi)) for g, lo, hi in
            re.findall(r'\{g:"([ABC])",\s*lo:(\d+),\s*hi:(\d+)', js_text)}
    py_b = [(int(lo), hi) for lo, hi in
            re.findall(r",\s*(\d+),\s*(10\*\*6|\d+)\)", vz)]
    if len(js_b) < 3 or len(py_b) < 3:
        bad.append("could not read three bands from both sides")
    else:
        want = {"A": (py_b[0][0], int(py_b[0][1]) - 1),
                "B": (py_b[1][0], int(py_b[1][1]) - 1)}
        for g, (lo, hi) in want.items():
            if js_b.get(g) != (lo, hi):
                bad.append(f"band {g}: python says {lo}-{hi}, browser says "
                           f"{js_b.get(g, ('?', '?'))[0]}-{js_b.get(g, ('?', '?'))[1]}")
        if js_b["C"][0] != py_b[2][0]:
            bad.append(f"band C starts at {py_b[2][0]} in python, {js_b['C'][0]} in browser")
    return bad

CHECK_HTML = find("check.html")
live = CHECK_HTML.read_text()
drift = parity(live)
check("shipped check.html agrees with the Python rules", not drift,
      "; ".join(drift) if drift else "dataset, sentinel and A/B/C cut points all match")

# The gate must FIRE, not merely pass on clean input (Cheatcode #22).
mutated = live.replace('{g:"A", lo:0,  hi:13', '{g:"A", lo:0,  hi:15')
check("a hand-edited grade band in the browser is CAUGHT",
      mutated != live and any("band A" in b for b in parity(mutated)),
      "; ".join(parity(mutated))[:90])

mutated2 = live.replace('d === "1900-01-01"', 'd === "1899-01-01"')
check("a drifted null-date sentinel in the browser is CAUGHT",
      mutated2 != live and any("sentinel" in b for b in parity(mutated2)),
      "; ".join(parity(mutated2))[:90])

# ── GUARD 11: ASCII-only bytes, and a failure taxonomy that stays split ───
# Two separate real failures are fenced here.
#
# (a) Encoding. check.html ships with no <meta charset> — the Artifact wrapper
#     owns <head> — so every byte must be ASCII and every typographic mark an
#     escape. This has broken three times now: mojibake, entities printed as
#     literal text, and a right single quote typed straight into a JS string.
#     Three repeats is not bad luck, it is a missing gate.
#
# (b) The taxonomy. "Handle errors" wants to collapse back into one catch
#     block. It did once, and a 200 carrying an error body rendered on screen
#     as "No NYC restaurant matched" — an outage printed as reassurance. So:
#     every failure kind the code can throw must carry its own explanation,
#     the wrong-shape check must exist, and the fetch must be cancellable —
#     without a timeout a hang leaves the button dead at "Looking...".
print("\n=== GUARD 11: ASCII-only bytes and a real failure taxonomy ===")

SILENT = {"superseded"}          # deliberately never rendered: a newer search won

def encoding_faults(text):
    return sorted({"U+%04X" % ord(c) for c in text if ord(c) > 127})

def taxonomy_faults(js):
    bad = []
    kinds = set(re.findall(r'fail\("(\w+)"', js))
    m = re.search(r"const WHY = \{(.*?)\};", js, re.S)
    why = set(re.findall(r"^\s*(\w+):", m.group(1), re.M)) if m else set()
    if not m:
        bad.append("no WHY table: failures have no per-kind explanation")
    shown = kinds - SILENT
    for k in sorted(shown - why):
        bad.append(f"kind {k!r} can be thrown but has no explanation")
    for k in sorted(why - shown):
        bad.append(f"explanation for {k!r} is dead copy - nothing throws it")
    if len(shown) < 4:
        bad.append(f"only {len(shown)} distinct failure kinds - the taxonomy collapsed")
    if "Array.isArray" not in js:
        bad.append("no shape check: a 200 with the wrong body reads as zero rows")
    if not ("AbortController" in js and "TIMEOUT_MS" in js and "signal" in js):
        bad.append("fetch is not cancellable: a hang leaves the button dead")
    return bad

faults = encoding_faults(live)
check("check.html is pure ASCII (no charset tag can save it)", not faults,
      "found " + ", ".join(faults[:6]) if faults else "0 bytes above U+007F")

tax = taxonomy_faults(live)
shown_kinds = sorted(set(re.findall(r'fail\("(\w+)"', live)) - SILENT)
check("every failure kind has its own honest explanation", not tax,
      "; ".join(tax) if tax else
      f"{len(shown_kinds)} kinds ({', '.join(shown_kinds)}), each with copy, "
      "shape-checked and cancellable")

# Each half must FIRE, not merely pass on clean input (Cheatcode #22).
smart = live.replace("Look it up", "Look it up" + chr(0x2019), 1)   # never type the glyph
check("one smart quote typed into the source is CAUGHT",
      smart != live and encoding_faults(smart) == ["U+2019"],
      "detected " + str(encoding_faults(smart)))

collapsed = re.sub(r"^\s*badshape:.*$", "", live, count=1, flags=re.M)
check("deleting one failure's explanation is CAUGHT",
      collapsed != live and any("badshape" in b for b in taxonomy_faults(collapsed)),
      "; ".join(taxonomy_faults(collapsed))[:90])

# NB: prefixing the name is not a removal - "XAbortController" still contains
# "AbortController", so a substring gate sails straight past it. Cut it out.
nohang = live.replace("new AbortController()", "null")
check("removing the timeout machinery is CAUGHT",
      nohang != live and any("cancellable" in b for b in taxonomy_faults(nohang)),
      "; ".join(taxonomy_faults(nohang))[:90])

# ── GUARD 12: operator.html — embedded evidence must not drift ───────────
# operator.html ranks a restaurant's open violations by measured persistence.
# Those rates cannot be computed in a browser tab (a join across two inspection
# cycles for ~7,000 restaurants), so they ship EMBEDDED in the page. Embedded
# numbers are the single easiest thing in this repo to leave behind: rerun
# reinspect_join.py, forget the page, and it keeps quoting last month's rates
# with this month's confidence. Nothing about the page would look wrong.
#
# The second half is taxonomy parity. operator.html has its own copy of the
# fetch layer, so it is a THIRD implementation of the same rules (after Python
# and check.html) and drifts for the same reason GUARD 10 exists.
print("\n=== GUARD 12: operator.html embedded evidence and taxonomy ===")

import build_operator as bo  # noqa: E402

OP_HTML = find("operator.html")
op = OP_HTML.read_text()
joined = json.loads((HERE / "reinspect_join.json").read_text())

check("operator.html is pure ASCII", not encoding_faults(op),
      "found " + ", ".join(encoding_faults(op)[:6]) if encoding_faults(op)
      else "0 bytes above U+007F")

op_kinds = set(re.findall(r'fail\("(\w+)"', op))
check_kinds = set(re.findall(r'fail\("(\w+)"', live))

op_tax = taxonomy_faults(op)
check("operator.html carries the same failure taxonomy", not op_tax,
      "; ".join(op_tax) if op_tax else
      f"{len(op_kinds - SILENT)} kinds, shape-checked and cancellable")

check("both pages name the SAME failure kinds", op_kinds == check_kinds,
      f"identical: {', '.join(sorted(op_kinds))}" if op_kinds == check_kinds
      else f"checker {sorted(check_kinds)} vs operator {sorted(op_kinds)}")

# The embedded table must be byte-for-byte what build_operator.py would emit.
fresh_block = bo.block(joined)
check("embedded persistence table is current with reinspect_join.json",
      fresh_block in op,
      f"{len(joined['per_code_all'])} codes, min n={joined['min_cited']}, "
      f"{joined['pairs']:,} pairs" if fresh_block in op
      else "STALE - run: python3 build_operator.py")

# The failure threshold the page prints is the one the pairing actually used.
m_py = re.search(r"^FAIL_SCORE\s*=\s*(\d+)", (HERE / "reinspect_join.py").read_text(), re.M)
m_js = re.search(r"const FAIL_SCORE\s*=\s*(\d+)", op)
check("operator.html's failure threshold matches the pairing that measured it",
      bool(m_py and m_js) and m_py.group(1) == m_js.group(1),
      f"python {m_py.group(1) if m_py else '?'} vs browser {m_js.group(1) if m_js else '?'}")

# Both halves must FIRE (Cheatcode #22).
stale_data = json.loads(json.dumps(joined))
stale_data["per_code_all"][0]["persist_rate"] += 0.05
check("a rate that moved in the JSON but not the page is CAUGHT",
      bo.block(stale_data) not in op,
      "regenerated block no longer matches the shipped page")

drifted = op.replace("const FAIL_SCORE = 14", "const FAIL_SCORE = 20")
m_bad = re.search(r"const FAIL_SCORE\s*=\s*(\d+)", drifted)
check("a hand-edited failure threshold is CAUGHT",
      drifted != op and m_bad.group(1) != m_py.group(1),
      f"python {m_py.group(1)} vs browser {m_bad.group(1)}")

print(f"\n{P} passed, {F} failed")
sys.exit(1 if F else 0)
