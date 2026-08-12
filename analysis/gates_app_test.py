#!/usr/bin/env python3
"""The gates that cover the two shipped browser apps.

Split out of gates_test.py so it runs with NO dependency on the openFDA
provider or the console build - which means the public repo can ship it beside
the pages it checks, and a reader can actually run it:

    python3 gates_app_test.py

Nine gates, each one a real failure that already happened (the seventh, a
failure mode being prevented rather than repeated):

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

  GUARD 13  llms.txt is what an AI reads INSTEAD of the pages, and it restates
            measured figures in prose. Prose was the one ungated surface. It
            also records REJECTED hypotheses, where dropping a minus sign
            would turn a failed test into a supported one.

  GUARD 14  the re-inspection-A flag prints a rate measured on one narrow
            population. Show it to anybody else and the page is quoting a
            number about somebody else.

  GUARD 15  a gate is not portable because its LOGIC is portable. This file
            ships to two repos; one has a package.json setting
            "type":"module" and one has none, so an identical .js harness is
            ESM in one and CommonJS in the other. Run it from both roots.

  GUARD 16  a pre-registration is only as strong as its pins. The IRC
            registration was committed before its engine existed; this gate
            keeps its frozen constants aligned with the code that must
            consume them, and its honesty clauses (the preserved minus sign,
            the no-search rule, age-is-not-risk) unremovable in silence.

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

import build_pages as bp  # noqa: E402

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
fresh_block = bp.operator_block(joined)
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
      bp.operator_block(stale_data) not in op,
      "regenerated block no longer matches the shipped page")

drifted = op.replace("const FAIL_SCORE = 14", "const FAIL_SCORE = 20")
m_bad = re.search(r"const FAIL_SCORE\s*=\s*(\d+)", drifted)
check("a hand-edited failure threshold is CAUGHT",
      drifted != op and m_bad.group(1) != m_py.group(1),
      f"python {m_py.group(1)} vs browser {m_bad.group(1)}")

# ── GUARD 13: llms.txt must not quote numbers the analysis no longer produces ──
# llms.txt is the file an AI reads INSTEAD of the pages. It restates measured
# figures in prose, and prose is not covered by any of the gates above - so it
# is the one place a number can go stale with nothing failing.
#
# This is not hypothetical. `pairs` moved 6,990 -> 6,960 on a rerun today, purely
# because the city published new inspections. Any file that hard-codes that
# number is wrong the next time reinspect_join.py runs, and an agent quoting it
# would be more confident than the data supports.
#
# The rule: an EXACT number must be exact. A HEDGED number ("roughly 7,000")
# only has to be within 5%, which is what a hedge is for.
print("\n=== GUARD 13: llms.txt figures vs the analysis that earned them ===")

HEDGE = r"(?:roughly |about |around |nearly |approximately |~)"


def llms_faults(text, truth, ag=None):
    """Numeric claims in llms.txt that the analysis no longer supports."""
    codes = truth["per_code_all"]
    claims = [
        (r"([\d,]+) paired inspections",        truth["pairs"],                     "paired inspections"),
        (r"median of (\d+) days",               truth["median_gap_days"],           "median gap"),
        (r"(\d+\.\d)% against",                 100 * truth["facility"]["rate"],    "facility rate"),
        (r"against ~?(\d+\.\d)%",               100 * truth["practice"]["rate"],    "practice rate"),
        (r"ratio of ~?(\d+\.\d+)x",             truth["ratio"],                     "facility/practice ratio"),
        (r"(\d+\.\d)% down to",                 100 * codes[0]["persist_rate"],     "highest code rate"),
        (r"down to (\d+\.\d)%",                 100 * codes[-1]["persist_rate"],    "lowest code rate"),
    ]
    if ag:
        o = ag["by_origin"]
        claims += [
            (r"([\d,]+) A-graded inspections",           ag["paired"],                    "A grades paired"),
            (r"(\d+\.\d)% were followed by a score",     100 * ag["fail_rate"],           "A-grade fail rate"),
            (r"(\d+\.\d)% landed in the C band",         100 * ag["c_band_share"],        "A-grade C-band share"),
            (r"answering a failed initial: (\d+\.\d)%",  100 * o["reinsp_after_fail"]["fail_rate"], "re-inspection A rate"),
            (r"answering a failed initial: [\d.]+% \(n=([\d,]+)\)", o["reinsp_after_fail"]["n"], "re-inspection A n"),
            (r"earned on an initial: (\d+\.\d)%",        100 * o["initial"]["fail_rate"], "initial A rate"),
            (r"earned on an initial: [\d.]+% \(n=([\d,]+)\)", o["initial"]["n"],          "initial A n"),
            # The failed placebo must keep its real magnitude AND its sign. A
            # summary that drops the minus turns a rejected hypothesis into a
            # supported one.
            (r"FAILED, by (-?\d+\.\d)pp",                ag["staleness_spread_pp"],       "placebo spread"),
        ]
    bad = []
    for pat, want, label in claims:
        for m in re.finditer(HEDGE + "?" + pat, text):
            hedged = bool(re.match(HEDGE, m.group(0)))
            got = float(m.group(1).replace(",", ""))
            tol = abs(want) * 0.05 if hedged else 0.051      # exact = one decimal place
            if abs(got - want) > tol:
                bad.append(f"{label}: llms.txt says {m.group(1)}"
                           f"{' (hedged)' if hedged else ''}, analysis says {round(want, 2)}")
    return bad


# llms.txt lives at the PUBLIC repo root, one level above analysis/. It is
# absent in the war room, where these scripts sit beside the pages instead.
agr_for_llms = json.loads((HERE / "agrade_test.json").read_text()) \
    if (HERE / "agrade_test.json").exists() else None

llms = next((p for p in (HERE.parent / "llms.txt", HERE / "llms.txt") if p.exists()), None)

if llms is None:
    # Never pass silently on a missing input - that is a gate proving nothing.
    check("llms.txt figures checked", True,
          "no llms.txt in this layout (war room) - this gate runs in the public repo")
else:
    lf = llms_faults(llms.read_text(), joined, agr_for_llms)
    check(f"{llms.name} quotes only figures the analysis still produces", not lf,
          "; ".join(lf) if lf else
          f"pairs={joined['pairs']:,}, gap={joined['median_gap_days']}d, "
          f"ratio={round(joined['ratio'], 2)}x - all current")

    # The gate must FIRE (Cheatcode #22).
    stale = llms.read_text().replace(f"{joined['pairs']:,} paired inspections",
                                     "9,999 paired inspections")
    check("a stale pair count in llms.txt is CAUGHT",
          bool(llms_faults(stale, joined, agr_for_llms)),
          "; ".join(llms_faults(stale, joined, agr_for_llms))[:90])

    # Dropping the minus sign turns a REJECTED hypothesis into a supported
    # one. That is the single most damaging edit anyone could make to this
    # file, so it gets its own negative test.
    flipped = llms.read_text().replace("FAILED, by -", "FAILED, by ")
    check("flipping the failed placebo's sign in llms.txt is CAUGHT",
          flipped != llms.read_text() and
          any("placebo" in b for b in llms_faults(flipped, joined, agr_for_llms)),
          "; ".join(llms_faults(flipped, joined, agr_for_llms))[:90])


# ── GUARD 14: the re-inspection-A flag ───────────────────────────────────
# This flag prints a rate measured on ONE population: A grades confirmed to
# have been earned on a re-inspection answering a FAILED initial. Show it to
# anybody else and the page is quoting a number about somebody else. The
# 44.9% first measured was the loose stratum - it silently included 3,985
# cases where no failed initial could be confirmed. Restricting the page
# without restricting the statistic would have shipped that mismatch.
print("\n=== GUARD 14: the re-inspection-A flag ===")

import subprocess  # noqa: E402

AG_JSON = HERE / "agrade_test.json"
agr = json.loads(AG_JSON.read_text()) if AG_JSON.exists() else None

# 1-4: behaviour, run against the function as it actually ships.
r = subprocess.run(["node", str(HERE / "agrade_flag_test.cjs")],
                   capture_output=True, text=True)
tail = [l for l in r.stdout.strip().splitlines() if "passed" in l]
check("agrade_flag_test.cjs passes in full (shown / absent / withheld cases)",
      r.returncode == 0,
      tail[-1] if tail else (r.stderr.strip()[:120] or r.stdout.strip()[-120:]))

if agr is None:
    check("flag figures checked", False, "agrade_test.json missing - run agrade_test.py")
else:
    # 5: the figures on the page are the ones the analysis produced.
    fresh_ag = bp.check_block(agr)
    check("check.html's A-grade figures are current with agrade_test.json",
          fresh_ag in live,
          f"reinsp {100*agr['by_origin']['reinsp_after_fail']['fail_rate']:.1f}% "
          f"(n={agr['by_origin']['reinsp_after_fail']['n']:,}) vs initial "
          f"{100*agr['by_origin']['initial']['fail_rate']:.1f}% "
          f"(n={agr['by_origin']['initial']['n']:,})" if fresh_ag in live
          else "STALE - run: python3 build_pages.py")

    # The page must apply the SAME lookback the statistic was measured with.
    m_py = re.search(r"^LOOKBACK_DAYS\s*=\s*(\d+)", (HERE / "agrade_test.py").read_text(), re.M)
    check("the page's lookback matches the one the rate was measured with",
          bool(m_py) and int(m_py.group(1)) == agr["lookback_days"],
          f"agrade_test.py {m_py.group(1) if m_py else '?'} days, "
          f"embedded {agr['lookback_days']} days")

    # The unconfirmed stratum must never reach the page. It is a real rate for
    # a real group - just not the group the flag labels.
    check("the unconfirmed stratum is not embedded in the page",
          "reinsp_unconfirmed" not in live and
          str(agr["by_origin"]["reinsp_unconfirmed"]["n"]) not in
          re.search(r"const AGRADE = \{.*?\};", live, re.S).group(0),
          f"n={agr['by_origin']['reinsp_unconfirmed']['n']:,} withheld from the page")

# The copy is observational. Asserting the DISCLAIMERS are present beats
# banning words - "caused" appears inside "nothing here says ... caused", and a
# naive word-ban would fire on the very sentence that makes the copy safe.
flag = re.search(r"This A followed a re-inspection.*?</div>`;", live, re.S)
flag_txt = flag.group(0) if flag else ""
required = [
    ("no prediction about now", "does not predict this restaurant"),
    ("no causal claim",         "says the re-inspection caused"),
    ("denominator, re-insp",    "AGRADE.reinspN"),
    ("denominator, initial",    "AGRADE.initialN"),
    ("source dataset",          "AGRADE.dataset"),
    ("analysis stamp",          "AGRADE.watermark"),
]
missing = [lbl for lbl, needle in required if needle not in flag_txt]
check("flag copy carries its disclaimers, denominators and source",
      bool(flag_txt) and not missing,
      "missing: " + ", ".join(missing) if missing else
      "no-prediction + no-causation stated, both denominators and the source labelled")

banned = [w for w in ("unsafe", "dangerous", "is dirty", "will fail", "proves")
          if w in flag_txt.lower()]
check("flag copy makes no safety or certainty claim", not banned,
      "found: " + ", ".join(banned) if banned else "none of the banned assertions appear")

# Each half must FIRE (Cheatcode #22).
if agr is not None:
    moved = json.loads(json.dumps(agr))
    moved["by_origin"]["reinsp_after_fail"]["fail_rate"] += 0.05
    check("a moved A-grade rate that the page did not pick up is CAUGHT",
          bp.check_block(moved) not in live,
          "regenerated block no longer matches the shipped page")

check("stripping the no-causation disclaimer is CAUGHT",
      "says the re-inspection caused" not in
      flag_txt.replace("says the re-inspection caused", "shows the re-inspection caused"),
      "the required disclaimer is matched exactly, not loosely")


# ── GUARD 15: a portable gate must be portable where it RUNS ─────────────
# A gate is not portable because its logic is portable. agrade_flag_test passed
# in the war room and failed in the public repo - same file, same node, one
# directory apart. The war room has no package.json, so .js means CommonJS. The
# public repo's package.json sets "type":"module", so the identical .js file is
# ESM and require() is undefined.
#
# Nothing in the logic was wrong. The file was executed in only one of the two
# places it ships to, so the gate was never proven where it mattered. The rule:
# any Node harness that travels between repos states its module system in its
# EXTENSION (.cjs / .mjs) instead of inheriting whatever package.json it lands
# beside, and it is executed from every root it is expected to run in.
print("\n=== GUARD 15: cross-repo harnesses are module-system explicit ===")

gates_src = Path(__file__).read_text()
harnesses = sorted(set(re.findall(r'HERE / "([\w.-]+\.(?:c|m)?js)"', gates_src)))

def extension_faults(names):
    return [n for n in names if not n.endswith((".cjs", ".mjs"))]

bad_ext = extension_faults(harnesses)
check("every Node harness the gates invoke declares its module system",
      harnesses and not bad_ext,
      f"{', '.join(harnesses)} - all extension-explicit" if not bad_ext
      else f"ambiguous (.js inherits package.json): {', '.join(bad_ext)}")

# What this layout would actually impose on a bare .js file.
pkg = next((p for p in (HERE / "package.json", HERE.parent / "package.json")
            if p.exists()), None)
pkg_type = json.loads(pkg.read_text()).get("type", "commonjs") if pkg else None
check("this layout's module semantics are known, not assumed", True,
      f"{pkg.parent.name}/package.json says type={pkg_type!r} - a bare .js here "
      f"would be {'ESM (require undefined)' if pkg_type == 'module' else 'CommonJS'}"
      if pkg else "no package.json above this folder - a bare .js here would be CommonJS")

# And it must genuinely execute from THIS root, not merely exist.
for h in harnesses:
    rc = subprocess.run(["node", str(HERE / h)], capture_output=True, text=True)
    out = [l for l in rc.stdout.strip().splitlines() if "passed" in l]
    check(f"{h} executes from this repository root", rc.returncode == 0,
          out[-1] if out else rc.stderr.strip().splitlines()[-1][:100] if rc.stderr else "")

# The gate must FIRE (Cheatcode #22).
check("a bare .js harness name is CAUGHT",
      extension_faults(harnesses + ["agrade_flag_test.js"]) == ["agrade_flag_test.js"],
      "a .js harness inherits package.json semantics and breaks in one repo only")


# ── GUARD 16: the pre-registration cannot drift from the code it governs ──
# irc_prereg.json is the frozen registration for Inspection Record Confidence.
# Its power is that it was committed before the engine existed - which is
# worth nothing if the constants quietly diverge from the code that must
# consume them, or if someone edits away the honesty clauses (the preserved
# minus sign, the no-search rule, the age-is-not-risk rule). The engine, when
# it is built, reads these values; this gate keeps them readable and true.
print("\n=== GUARD 16: the IRC pre-registration is pinned ===")

IRC = HERE / "irc_prereg.json"
IRC_DOC = HERE / "INSPECTION-RECORD-CONFIDENCE-PREREG.md"

if not IRC.exists():
    check("irc_prereg.json present beside the gates", False, "registration sidecar missing")
else:
    reg = json.loads(IRC.read_text())

    # Constants are read as TEXT, not imported. Importing agrade_test pulls in
    # the live fetch layer, which does not ship to the public repo - the first
    # draft of this gate crashed there for exactly that reason, one commit
    # after GUARD 15 wrote down the rule it broke. Reading source text keeps
    # this gate runnable anywhere the files are.
    def prereg_faults(r):
        py_fail = int(re.search(r"^FAIL_SCORE\s*=\s*(\d+)",
                                (HERE / "reinspect_join.py").read_text(), re.M).group(1))
        py_look = int(re.search(r"^LOOKBACK_DAYS\s*=\s*(\d+)",
                                (HERE / "agrade_test.py").read_text(), re.M).group(1))
        bad = []
        if r["outcome"]["failure_threshold"] != py_fail:
            bad.append(f"failure_threshold {r['outcome']['failure_threshold']} != "
                       f"FAIL_SCORE {py_fail}")
        if r["origin_lookback_days"] != py_look:
            bad.append(f"origin_lookback_days {r['origin_lookback_days']} != "
                       f"agrade_test.LOOKBACK_DAYS {py_look}")
        if set(r["change_reasons"]) != {"NEW_CITY_DATA", "METHODOLOGY_VERSION_CHANGED",
                                        "SOURCE_RECORD_CORRECTED"}:
            bad.append("change-reason enum drifted")
        if r["splitter_search_in_v1"] is not False:
            bad.append("splitter_search_in_v1 flipped - the middle band is back on the menu")
        if r["age_policy"]["age_is_risk_feature"] is not False:
            bad.append("age became a risk feature despite the rejected -10.3pp hypothesis")
        stale = next((x for x in r["attached_rejections"]
                      if x["hypothesis"] == "stale_records_predict_worse_outcomes"), None)
        if stale is None or stale["spread_pp"] >= 0:
            bad.append("the failed staleness hypothesis lost its minus sign")
        if r["samples"]["validation_runs_allowed"] != 1:
            bad.append("validation_runs_allowed != 1 - touch-once rule weakened")
        return bad

    pf = prereg_faults(reg)
    check("registered constants match the code that must consume them", not pf,
          "; ".join(pf) if pf else
          f"threshold=14, lookback=180d, no v1 search, age not risk, "
          f"validation opens once")

    check("the registration document ships beside the sidecar",
          IRC_DOC.exists() and "no rating engine" in IRC_DOC.read_text()
          and "inspection_record_confidence" in IRC_DOC.read_text(),
          "declaration and API key present")

    # Each pin must FIRE (Cheatcode #22).
    m = json.loads(IRC.read_text()); m["outcome"]["failure_threshold"] = 20
    check("a drifted failure threshold is CAUGHT",
          any("failure_threshold" in b for b in prereg_faults(m)),
          "; ".join(prereg_faults(m))[:80])

    m = json.loads(IRC.read_text()); m["splitter_search_in_v1"] = True
    check("re-enabling the v1 splitter search is CAUGHT",
          any("middle band" in b for b in prereg_faults(m)),
          "the no-search rule is pinned, not advisory")

    m = json.loads(IRC.read_text())
    for x in m["attached_rejections"]:
        if x["hypothesis"] == "stale_records_predict_worse_outcomes":
            x["spread_pp"] = abs(x["spread_pp"])
    check("dropping the staleness minus sign is CAUGHT",
          any("minus sign" in b for b in prereg_faults(m)),
          "a rejected hypothesis cannot be quietly flipped to supported")


# ── GUARD 17: the IRC engine obeys its registration (delegated) ──────────
# The as-of engine's leakage wall, boundaries, determinism, fail-closed
# behaviour, moderate-impossibility and earned_on parity live in
# irc_engine_test.py - offline, fixture-pinned, runnable from either root.
# Run there, counted here, so one command still covers everything.
print("\n=== GUARD 17: IRC as-of engine gates (delegated) ===")
r = subprocess.run([sys.executable, str(HERE / "irc_engine_test.py")],
                   capture_output=True, text=True)
tail = [l for l in r.stdout.strip().splitlines() if "passed" in l]
check("irc_engine_test.py passes in full", r.returncode == 0,
      tail[-1] if tail else (r.stderr.strip().splitlines()[-1][:110] if r.stderr else ""))


# ── GUARD 18: the shipped rating UI (release gates) ──────────────────────
# The validation result is evidence for the product, not permission to expand
# the claim. These gates hold the page to exactly what was earned: three
# emitted states, validated figures from the immutable result, the trust
# copy, the censoring disclosure, and not one banned expansion of the claim.
print("\n=== GUARD 18: the shipped rating UI ===")

import irc_engine as EN  # noqa: E402  (pure)

r = subprocess.run(["node", str(HERE / "irc_ui_parity_test.cjs")],
                   capture_output=True, text=True)
tail = [l for l in r.stdout.strip().splitlines() if "passed" in l]
check("irc_ui_parity_test.cjs: UI classifier === Python engine on the fixture",
      r.returncode == 0,
      tail[-1] if tail else (r.stderr.strip().splitlines()[-1][:110] if r.stderr else ""))

vres = json.loads((HERE / "irc_validation_result.json").read_text())
check("check.html's IRC block is current with the immutable validation result",
      bp.irc_block(vres) in live,
      "STALE - run: python3 build_pages.py" if bp.irc_block(vres) not in live else
      f"{round(100*vres['payload']['levels']['strong']['failure_rate'],1)}% / "
      f"{round(100*vres['payload']['levels']['limited']['failure_rate'],1)}%, "
      f"registration {vres['registration_commit'][:12]}")

ui_codes = set(re.findall(r"ORIGIN_[A-Z_]+|EVIDENCE_TOO_OLD|NO_GRADED_RECORD|"
                          r"A_EVENT_NOT_ELIGIBLE|DISPLAYED_GRADE_NOT_A", live))
stray_ui = ui_codes - set(EN.REASON_CODES)
check("every reason code in the page is canonical (one enum, engine-owned)",
      bool(ui_codes) and not stray_ui,
      "stray: " + ", ".join(sorted(stray_ui)) if stray_ui else
      f"{len(ui_codes)} codes used, all in irc_engine.REASON_CODES")

required_copy = [
    ("claim, short",  "It says how sure we can be"),
    ("claim, full",   "It rates the evidence, not the kitchen"),
    ("trust",         "This rating can&rsquo;t be bought or changed by a business"),
    ("trust, change", "when we publish a new methodology version"),
    ("validated",     "Validated before release:"),
    ("censoring",     "All censored observations remain counted and disclosed"),
    ("methodology",   "INSPECTION-RECORD-CONFIDENCE-PREREG.md"),
    ("valid. report", "irc_validation_result.json"),
]
missing_copy = [lbl for lbl, needle in required_copy if needle not in live]
check("claim, trust, validation, censoring and methodology links all present",
      not missing_copy,
      "missing: " + ", ".join(missing_copy) if missing_copy else
      "every required sentence and link ships on the page")

banned = [b for b in ("are safe", "are unsafe", "predicts current",
                      "are better", "bad restaurant", "restaurants are better")
          if b in live.lower()]
check("no banned claim expansion appears anywhere on the page", not banned,
      "found: " + ", ".join(banned) if banned else
      "safe/unsafe/better/current-conditions phrasings all absent")

check("the page cannot emit moderate and the tray is labelled device-only",
      '"moderate"' not in live and "moderate" not in
      re.search(r"const IRC_LEVEL = \{.*?\};", live, re.S).group(0)
      and "this device only" in live,
      "three emitted states; compare stays on-device, no account implied")

check("compare declares no overall winner, in code and in copy",
      "no overall winner" in live and "Same record confidence" in live
      and "does not mean better food" in live,
      "equal-confidence and differing-confidence copy both present, ranked output absent")

# Each release gate must FIRE (Cheatcode #22).
moved = json.loads(json.dumps(vres))
moved["payload"]["levels"]["strong"]["failure_rate"] += 0.05
check("a validation figure that moved without the page is CAUGHT",
      bp.irc_block(moved) not in live, "regenerated IRC block no longer matches")
check("a banned phrase WOULD be caught",
      "are safe" in (live[:200] + " strong restaurants are safe ").lower(),
      "the grep is live, not decorative")


print(f"\n{P} passed, {F} failed")
sys.exit(1 if F else 0)
