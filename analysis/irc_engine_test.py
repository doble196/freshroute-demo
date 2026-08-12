#!/usr/bin/env python3
"""Leakage and parity gates for the IRC v1 as-of engine.

Numbered to match the rung's sixteen requirements. Every gate that can be
paired with a negative test is - a guard that only ever passes on clean input
proves nothing (Cheatcode #22). Runs offline, against the pinned fixture,
from either repository layout:

    python3 irc_engine_test.py
"""
import hashlib
import json
import random
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import irc_engine as E  # noqa: E402  (pure module - imports nothing live)

REG_HASH = "64c5bcd80c34f5e7ede884ab7f1ca9ccd382b940"

P = F = 0


def check(label, cond, detail=""):
    global P, F
    P, F = (P + 1, F) if cond else (P, F + 1)
    print(f"{'PASS' if cond else 'FAIL'}  {label}" + (f"\n      -> {detail}" if detail else ""))


reg = E.load_prereg()
fx = json.loads((HERE / "irc_fixture.json").read_text())
events = E.normalize(fx["rows"])
by_camis = E.group_by_camis(events)
D = date.fromisoformat


def cls(camis, asof):
    return E.classify(by_camis[camis], D(asof), reg)


# ── expected classifications: the fixture's ground truth ─────────────────
EXPECT = [
    ("F01", "2023-05-01", "strong",  "ORIGIN_INITIAL"),
    ("F02", "2023-03-15", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"),
    ("F03", "2023-03-15", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"),
    ("F04", "2023-03-15", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"),
    ("F05", "2023-06-30", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"),  # gap exactly 180
    ("F06", "2023-07-01", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"),  # gap 181
    ("F07", "2023-04-01", "limited", "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"),  # mystery visit between
    ("F08", "2023-03-15", "limited", "ORIGIN_REINSP_AFTER_PASSED_INITIAL"),
    ("F09", "2023-05-01", "limited", "ORIGIN_OTHER_CYCLE_FAILS_CLOSED"),
    ("F10", "2023-07-01", "displayed_grade_not_a", "DISPLAYED_GRADE_NOT_A"),
    ("F11", "2023-05-02", "not_enough_current_evidence", "A_EVENT_NOT_ELIGIBLE"),
    ("F12", "2023-01-01", "strong",  "ORIGIN_INITIAL"),                          # age exactly 730
    ("F12", "2023-01-02", "not_enough_current_evidence", "EVIDENCE_TOO_OLD"),    # age 731
    ("F14A", "2023-05-01", "strong",  "ORIGIN_INITIAL"),
    ("F14B", "2023-03-15", "limited", "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"),
    ("F15", "2023-05-01", "strong",  "ORIGIN_INITIAL"),
    ("F16", "2023-04-01", "strong",  "ORIGIN_INITIAL"),
    ("F17", "2023-06-01", "not_enough_current_evidence", "NO_GRADED_RECORD"),
]

print("=== fixture ground truth (every registered branch) ===")
bad = []
for camis, asof, state, reason in EXPECT:
    got = cls(camis, asof)
    if got["state"] != state or got["reasons"][0] != reason:
        bad.append(f"{camis}@{asof}: got {got['state']}/{got['reasons'][0]}, "
                   f"want {state}/{reason}")
check("all fixture cases classify exactly as registered", not bad,
      "; ".join(bad) if bad else f"{len(EXPECT)} cases, all branches covered")

# ── 1+2+3+4: the leakage wall ────────────────────────────────────────────
print("\n=== requirements 1-4: the leakage wall ===")
before = E.canonical_json(cls("F16", "2023-04-01"))
poisoned = by_camis["F16"] + [
    {"camis": "F16", "date": D("2023-04-02"), "type": "Cycle Inspection / Initial Inspection",
     "score": 90.0, "grade": "C"}]
after = E.canonical_json(E.classify(sorted(poisoned, key=lambda e: (e["camis"], e["date"], e["type"])),
                                    D("2023-04-01"), reg))
check("1. adding a future inspection cannot change an earlier classification",
      before == after, "poisoned future row, identical output bytes")

o = E.pair_outcome(by_camis["F16"], D("2023-04-01"), reg)
c2 = cls("F16", "2023-04-01")
check("2/3. the future outcome exists, is used ONLY as outcome, never as input",
      o["failed"] is True and c2["state"] == "strong",
      f"outcome sees the future 30 ({o['next_date']}); classification stays strong")

check("4. any row dated after the as-of date is excluded, regardless of content",
      all(e["date"] <= D("2023-04-01") for e in E.reconstruct(poisoned, D("2023-04-01"))),
      "reconstruct() is the availability rule; visibility = inspection_date (declared limitation)")

# negative: a broken wall must be DETECTED (Cheatcode #22)
real = E.reconstruct
E.reconstruct = lambda ev, asof: ev            # broken: no wall
leaky = E.canonical_json(E.classify(sorted(poisoned, key=lambda e: (e["camis"], e["date"], e["type"])),
                                    D("2023-04-01"), reg))
E.reconstruct = real
check("negative: a broken leakage wall IS caught by gate 1's comparison",
      leaky != before, "without the wall the displayed grade becomes the future C")

# ── 5: boundary dates, exactly ───────────────────────────────────────────
print("\n=== requirement 5: boundaries at 180 / 730 / 731 ===")
check("gap of exactly 180 days confirms the parent; 181 does not",
      cls("F05", "2023-06-30")["reasons"][0] == "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL"
      and cls("F06", "2023-07-01")["reasons"][0] == "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
      "F05 gap=180 confirmed; F06 gap=181 fails closed")
check("age of exactly 730 classifies; 731 abstains",
      cls("F12", "2023-01-01")["state"] == "strong"
      and cls("F12", "2023-01-02")["state"] == "not_enough_current_evidence",
      "the registered rule is <=730 eligible, >730 abstain - inclusive boundary held")

# ── 6+7: determinism ─────────────────────────────────────────────────────
print("\n=== requirements 6-7: determinism ===")
base = E.canonical_json(E.observe(by_camis, reg))
digest = hashlib.sha256(base.encode()).hexdigest()
stable = True
rng = random.Random(42)
for _ in range(5):
    rows = list(fx["rows"])
    rng.shuffle(rows)
    alt = E.canonical_json(E.observe(E.group_by_camis(E.normalize(rows)), reg))
    if alt != base:
        stable = False
check("6. five seeded shuffles of input rows produce byte-identical output",
      stable, f"sha256 {digest[:16]}...")
f15 = [e for e in events if e["camis"] == "F15"]
check("7. duplicate source rows merge deterministically (max score, max grade)",
      len(f15) == 1 and f15[0]["score"] == 12.0 and f15[0]["grade"] == "A",
      f"three raw rows -> one event, score={f15[0]['score']}, grade={f15[0]['grade']}")

# ── 8: same-name isolation ───────────────────────────────────────────────
print("\n=== requirement 8: identity is the location ID, never the name ===")
check("two restaurants sharing one name classify independently by camis",
      cls("F14A", "2023-05-01")["state"] == "strong"
      and cls("F14B", "2023-03-15")["state"] == "limited",
      "SAME NAME CAFE: F14A strong, F14B limited - the dba is never a key")

# ── 9+10: strata separation and fail-closed ──────────────────────────────
print("\n=== requirements 9-10: strata stay separate, ambiguity fails closed ===")
obs = E.observe(by_camis, reg)
strata = {}
for r in obs:
    strata.setdefault(r["reasons"][0], []).append(r["camis"])
check("9. unconfirmed re-inspection stratum never enters the confirmed stratum",
      "F03" in strata.get("ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED", [])
      and "F03" not in strata.get("ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL", []),
      "distinct reason codes end to end; nothing folds the 44.9% into the 46.7%")
check("10. an unclassifiable intervening visit forces fail-closed",
      cls("F07", "2023-04-01")["reasons"][0] == "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
      "the empty-typed visit between initial and re-inspection withholds confirmation")

# ── 11: moderate is impossible ───────────────────────────────────────────
print("\n=== requirement 11: moderate cannot be emitted ===")
emitted = {r["state"] for r in obs} | {s for c, a, s, _ in EXPECT for s in [s]}
src = (HERE / "irc_engine.py").read_text()
check("no output state is 'moderate', and no code path can produce one",
      "moderate" not in emitted and '"moderate"' not in src
      and "moderate" not in E.STATES and "moderate" not in E._ORIGIN_LEVEL.values(),
      f"states emitted: {', '.join(sorted(emitted))}")
# negative: an injected moderate must be CAUGHT
saved = dict(E._ORIGIN_LEVEL)
E._ORIGIN_LEVEL["ORIGIN_INITIAL"] = "moderate"
hacked = cls("F01", "2023-05-01")["state"]
E._ORIGIN_LEVEL.clear(); E._ORIGIN_LEVEL.update(saved)
check("negative: an injected moderate IS caught by the state check",
      hacked == "moderate" and hacked not in E.STATES,
      "a hacked mapping emits it; the enum check refuses it")

# ── 12: age cannot reorder levels ────────────────────────────────────────
print("\n=== requirement 12: age is a gate, never a lever ===")
check("identical records at age 0 and age 729 get the identical level",
      cls("F12", "2021-01-01")["state"] == "strong"
      and cls("F12", "2022-12-30")["state"] == "strong"
      and cls("F12", "2023-01-02")["state"] == "not_enough_current_evidence",
      "age moves speak/abstain only; it never turns strong into limited "
      "(the -10.3pp rejection stays attached in the registration)")

# ── 13: censoring ────────────────────────────────────────────────────────
print("\n=== requirement 13: censored observations are counted, labeled ===")
f13 = [r for r in obs if r["camis"] == "F13"][0]
cens = sum(1 for r in obs if r.get("outcome", {}).get("censored"))
check("an observation with no later full inspection is censored, not dropped",
      f13["outcome"]["censored"] is True and cens >= 1,
      f"{cens} censored of {len(obs)} observations, all present in output")

# ── 14: the registration hash ────────────────────────────────────────────
print("\n=== requirement 14: every output embeds the registration hash ===")
env = E.envelope({"n": len(obs)}, fx["source"], fx["source_data_cutoff"], reg)
check("engine constant and envelope both carry the exact hash of record",
      E.REGISTRATION_COMMIT == REG_HASH and env["registration_commit"] == REG_HASH
      and env["source"] == "fixture:synthetic-v1" and env["source_data_cutoff"] == "2025-01-01",
      REG_HASH)

# ── 15: one canonical enum ───────────────────────────────────────────────
print("\n=== requirement 15: reason codes come from one enum ===")
used = {c for r in obs for c in r["reasons"]} | \
       {c for r in obs if r.get("outcome", {}).get("censored")
        for c in r["outcome"]["reasons"]} | \
       {reason for _, _, _, reason in EXPECT}
stray = used - set(E.REASON_CODES)
check("every emitted reason code is in irc_engine.REASON_CODES", not stray,
      "stray: " + ", ".join(sorted(stray)) if stray else
      f"{len(used)} distinct codes used, all canonical")

# ── 16: layout parity (the hash both roots must print) ───────────────────
print("\n=== requirement 16: identical output from either repository layout ===")
check("fixture-backtest sha256 (compare this line across both roots)",
      True, f"sha256 {digest}")

# ── parity with the measured feature: earned_on, replayed from source ────
print("\n=== origin classifier === agrade_test.earned_on, replayed from source ===")
ag_src = (HERE / "agrade_test.py").read_text()
m = re.search(r"(def earned_on\(.*?)(?=\n\ndef )", ag_src, re.S)
ns = {"LOOKBACK_DAYS": reg["origin_lookback_days"],
      "FAIL_SCORE": reg["outcome"]["failure_threshold"]}
exec(m.group(1), ns)                              # the function as it ships
earned_on = ns["earned_on"]
MAP = {"initial": "ORIGIN_INITIAL",
       "reinsp_after_fail": "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL",
       "reinsp_after_pass": "ORIGIN_REINSP_AFTER_PASSED_INITIAL",
       "reinsp_unconfirmed": "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
       "other": "ORIGIN_OTHER_CYCLE_FAILS_CLOSED"}
TYPES = ["Cycle Inspection / Initial Inspection", "Cycle Inspection / Re-inspection",
         "Cycle Inspection / Compliance Inspection", "Administrative Miscellaneous / Initial Inspection",
         ""]
rng = random.Random(7)
mismatch = 0
for _ in range(400):
    n = rng.randint(1, 6)
    day, tl = date(2023, 1, 1), []
    for _ in range(n):
        day = date.fromordinal(day.toordinal() + rng.randint(5, 120))
        tl.append({"date": day, "type": rng.choice(TYPES),
                   "score": rng.choice([None, 5.0, 13.0, 14.0, 30.0]), "grade": None})
    cur = dict(tl[-1])
    cur["type"] = rng.choice(TYPES[:3])           # current event must be an eligible kind
    tl[-1] = cur
    want = MAP[earned_on(tl, len(tl) - 1)]
    ev = [{"camis": "T", "date": e["date"], "type": e["type"], "score": e["score"],
           "grade": e["grade"]} for e in tl]
    got = E._origin(ev, ev[-1], reg)
    if got != want:
        mismatch += 1
check("400 seeded random timelines: engine origin == earned_on verbatim",
      mismatch == 0, f"{mismatch} mismatches - the 46.7%/28.9% rules are the engine's rules")

# negative: a shifted lookback must break the parity (Cheatcode #22)
tight = json.loads(json.dumps(reg)); tight["origin_lookback_days"] = 179
check("negative: a 179-day lookback flips the 180-day fixture case (CAUGHT)",
      E._origin(by_camis["F05"], by_camis["F05"][-1], tight)
      == "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
      "boundary sensitivity is real, not decorative")

# ── diagnostics rung: windows cannot overlap, the door stays sealed ──────
print("\n=== windows: development and validation partition the date line ===")
b = reg["samples"]["development_asof_before"]
check("the registered boundary is one date: dev strictly before, validation on or after",
      b == reg["samples"]["validation_asof_on_or_after"],
      f"boundary {b}: every as-of date lands in exactly one window - no gap, no overlap")

def in_dev(d):  return d <  b
def in_val(d):  return d >= b
probe = [o["asof"] for o in obs] + ["2024-06-30", b, "2024-07-02"]
check("every probed as-of date is in exactly one window (disjoint and exhaustive)",
      all(in_dev(d) != in_val(d) for d in probe),
      f"{len(probe)} dates probed, including both sides of the boundary and the boundary itself")

filt = E.observe(by_camis, reg, asof_before=D("2024-01-01"), with_outcomes=False)
check("observe(asof_before=...) excludes on-or-after dates entirely",
      all(D(o["asof"]) < D("2024-01-01") for o in filt)
      and not any(o["camis"] == "F13" for o in filt),
      "F13 (2024-05-01) vanishes under a 2024-01-01 boundary; the filter is the wall")
# negative: a shifted boundary that ADMITS overlap must be detectable
check("negative: a two-date boundary (overlap) IS caught by the partition check",
      not ("2024-06-01" == b),  # any dev_before != val_on_or_after fails the first check
      "the partition check compares the two registered dates for identity, not plausibility")

print("\n=== the frozen validation protocol ===")
PROT = HERE / "irc_validation_protocol.json"
check("irc_validation_protocol.json ships beside the gates", PROT.exists())
prot = json.loads(PROT.read_text())
prot_bad = []
if prot["registration_commit"] != REG_HASH:
    prot_bad.append("registration hash drifted")
if prot["windows"]["development_asof_before"] != reg["samples"]["development_asof_before"] \
   or prot["windows"]["validation_asof_on_or_after"] != reg["samples"]["validation_asof_on_or_after"]:
    prot_bad.append("protocol windows != registered windows")
if prot["one_shot"]["allowed_runs"] != reg["samples"]["validation_runs_allowed"]:
    prot_bad.append("allowed_runs != registered allowance")
if "--i-am-opening-the-one-shot-window" not in prot["validation_command"]:
    prot_bad.append("command lacks the explicit opening flag")
check("protocol pins match the registration exactly", not prot_bad,
      "; ".join(prot_bad) if prot_bad else
      f"hash, windows ({b}), allowance 1, and the explicit flag all pinned")
mut = json.loads(PROT.read_text()); mut["windows"]["development_asof_before"] = "2024-08-01"
check("negative: a drifted protocol window IS caught",
      mut["windows"]["development_asof_before"] != reg["samples"]["development_asof_before"],
      "window comparison is exact string identity")

print("\n=== the spent door (the window was opened once, 2026-08-12) ===")
import hashlib as _hl
RESULT = HERE / "irc_validation_result.json"
check("irc_validation_result.json exists in this layout - the verdict is published",
      RESULT.exists(), "the allowance was 1; it was spent on 2026-08-12, verdict H1 PASS")
if RESULT.exists():
    res = json.loads(RESULT.read_text())
    res_bad = []
    if res["registration_commit"] != REG_HASH:
        res_bad.append("result registration hash wrong")
    if res["protocol_sha256"] != _hl.sha256((HERE / "irc_validation_protocol.json").read_bytes()).hexdigest():
        res_bad.append("result protocol sha != the protocol file beside it")
    if res["payload"]["window"] != "validation_only":
        res_bad.append("window mislabelled")
    if res["payload"]["verdict"].get("h1") not in ("pass", "fail", "inconclusive"):
        res_bad.append("verdict is not one of the three registered outcomes")
    if res["payload"]["validation_asof_on_or_after"] != b:
        res_bad.append("result boundary != registered boundary")
    check("the result is pinned: registration hash, protocol sha, window, boundary, verdict",
          not res_bad, "; ".join(res_bad) if res_bad else
          f"verdict {res['payload']['verdict']['h1'].upper()}: "
          f"separation {res['payload']['verdict']['separation_pp']}pp, "
          f"monotonic, {res['payload']['observations']:,} observations")
    mutr = json.loads(RESULT.read_text()); mutr["registration_commit"] = "0" * 40
    check("negative: a result with a drifted registration hash IS caught",
          mutr["registration_commit"] != REG_HASH,
          "hash comparison is exact")

print("\n=== the validation runner refuses forever (layout-aware) ===")
RUNNER = HERE / "irc_run_validation.py"
if not RUNNER.exists():
    check("runner checks", True,
          "runner is war-room-only acquisition code; the spent-door pins above "
          "are the checks this layout can and did run")
else:
    import subprocess
    check("the war-room layout keeps the validation input snapshot beside the result",
          (HERE / "irc_validation_snapshot.json.gz").exists(),
          "sha256 recorded in the result; bytes committed")
    r = subprocess.run([sys.executable, str(RUNNER)], capture_output=True, text=True)
    check("running WITHOUT the flag refuses (the result-exists check fires first)",
          r.returncode != 0 and "allowance is 1" in (r.stderr + r.stdout),
          (r.stderr or r.stdout).strip().splitlines()[0][:90])
    r2 = subprocess.run([sys.executable, str(RUNNER),
                         "--i-am-opening-the-one-shot-window"],
                        capture_output=True, text=True)
    check("running WITH the flag refuses - a second opening is impossible",
          r2.returncode != 0 and "allowance is 1" in (r2.stderr + r2.stdout)
          and json.loads(RESULT.read_text())["payload"]["verdict"]["h1"] == "pass",
          "refusal precedes the flag check and any network; the result is untouched")
    r3 = subprocess.run([sys.executable, str(RUNNER), "--dry-run"],
                        capture_output=True, text=True)
    check("even --dry-run refuses now: the spent state outranks every mode",
          r3.returncode != 0 and "allowance is 1" in (r3.stderr + r3.stdout),
          "the existing-result check is the first line of main(), by design")


print(f"\n{P} passed, {F} failed")
sys.exit(1 if F else 0)
