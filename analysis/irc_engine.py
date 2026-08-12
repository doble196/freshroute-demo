#!/usr/bin/env python3
"""Inspection Record Confidence v1 - the historical as-of engine.

THE SPECIFICATION IS THE REGISTRATION, committed alone before this file
existed. This module implements it and adds nothing:

    registration commit 64c5bcd80c34f5e7ede884ab7f1ca9ccd382b940
    (public mirror beb5bba; pins in gates_app_test.py GUARD 16)

Every output envelope embeds that hash. If this code and the registration
disagree, the registration wins and this code is wrong.

PURE AND DETERMINISTIC. No network. Nothing is fetched at import time or any
other time - acquisition lives in separate runner scripts, and this module
runs identically against a pinned local fixture from either repository
layout. Same input rows in any order produce byte-identical canonical output.

LAYERS, kept separate on purpose:
    normalize()        raw source rows -> canonical inspection events
    reconstruct()      the record as it stood on the as-of date (leakage wall)
    classify()         registered mapping -> state + reason codes
    pair_outcome()     the NEXT full inspection, used ONLY as outcome
    envelope()         stable serialization with provenance + hash

REGISTERED INTERPRETATION NOTE (recorded before first execution, not an
amendment): section 9.4 assigns "earned on a re-inspection" to `limited`,
enumerating confirmed-after-fail and unconfirmable. Two rarer origins exist
that the enumeration does not name: a re-inspection whose parent initial
PASSED, and an eligible cycle A that is neither initial nor re-inspection
(e.g. compliance). Both are mapped to `limited` under the head clause and the
fail-closed principle (section 8), each with its own reason code so the
strata stay distinct in every report. Neither is folded into the confirmed
stratum.

`moderate` is not emitted anywhere in this module. There is no code path
that can produce it; the gate suite proves that against the source.
"""
import json
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent

REGISTRATION_COMMIT = "64c5bcd80c34f5e7ede884ab7f1ca9ccd382b940"
ENGINE_VERSION = "1.0.0-candidate-engine.1"

# The complete set of states this engine can emit. `moderate` is reserved by
# the registration and deliberately absent - not filtered out, absent.
STATES = ("strong", "limited", "not_enough_current_evidence", "displayed_grade_not_a")

# The canonical reason-code enum. Engine outputs and gates share THIS tuple;
# a code that is not here is a bug, not a new feature.
REASON_CODES = (
    "ORIGIN_INITIAL",
    "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL",
    "ORIGIN_REINSP_AFTER_PASSED_INITIAL",       # limited via section 9.4 head clause
    "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED",
    "ORIGIN_OTHER_CYCLE_FAILS_CLOSED",          # e.g. compliance-cycle A
    "EVIDENCE_TOO_OLD",
    "NO_GRADED_RECORD",
    "A_EVENT_NOT_ELIGIBLE",
    "DISPLAYED_GRADE_NOT_A",
    "OUTCOME_CENSORED",
)

_SENTINEL = "1900-01-01"


def load_prereg(path=None):
    """The registered constants. Read from the committed sidecar, never
    redeclared here - a constant redeclared in code is a constant that
    drifts (the reason GUARD 16 exists)."""
    p = Path(path) if path else HERE / "irc_prereg.json"
    return json.loads(p.read_text())


def _parse_date(s):
    s = (s or "")[:10]
    if not s or s == _SENTINEL:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


def normalize(rows):
    """Raw source rows -> canonical, deduplicated, stably ordered events.

    One event per (camis, date, type). Duplicate rows merge exactly the way
    the upstream grouped pull does: max() of score, max() of grade - stated
    here so determinism is a documented rule, not an accident of dict order.
    Sentinel-dated and undateable rows are dropped, as registered.
    """
    merged = {}
    for r in rows:
        d = _parse_date(r.get("inspection_date"))
        if d is None:
            continue
        camis = str(r.get("camis") or "").strip()
        if not camis:
            continue
        t = (r.get("inspection_type") or "").strip()
        key = (camis, d, t)
        s = r.get("score")
        try:
            s = None if s is None or s == "" else float(s)
        except (TypeError, ValueError):
            s = None
        g = (r.get("grade") or "").strip().upper() or None
        cur = merged.get(key)
        if cur is None:
            merged[key] = {"camis": camis, "date": d, "type": t, "score": s, "grade": g}
        else:
            if s is not None and (cur["score"] is None or s > cur["score"]):
                cur["score"] = s
            if g is not None and (cur["grade"] is None or g > cur["grade"]):
                cur["grade"] = g
    # Stable total order: camis, date, type. Input order can never matter.
    return sorted(merged.values(), key=lambda e: (e["camis"], e["date"], e["type"]))


def reconstruct(events, asof):
    """The leakage wall: the record as it stood on `asof`.

    Registered availability rule (declared limitation in the registration):
    a row is visible from its inspection_date. Nothing dated after `asof`
    exists for any downstream computation except outcome pairing, which is
    the outcome precisely because it is on the far side of this wall.
    """
    return [e for e in events if e["date"] <= asof]


def _is_cycle(t):
    return t.lower().startswith("cycle inspection")


def _is_eligible_a_event(e):
    """Registered eligibility (section 4): a cycle inspection carrying grade A
    and a score; re-opening, administrative and grade-pending events are not
    eligible."""
    t = e["type"].lower()
    return (e["grade"] == "A" and e["score"] is not None and _is_cycle(t)
            and "reopen" not in t)


def _origin(visible, a_event, reg):
    """How the displayed A was earned. Mirrors agrade_test.earned_on exactly -
    the 46.7%/28.9% rates were measured with these rules, so any deviation
    here would quote numbers about a different population. The equivalence is
    enforced by a gate that extracts earned_on from its source and replays
    both on generated timelines.
    """
    lookback = int(reg["origin_lookback_days"])
    fail = float(reg["outcome"]["failure_threshold"])
    t = a_event["type"].lower()
    if "initial" in t:
        return "ORIGIN_INITIAL"
    if "re-inspection" not in t:
        return "ORIGIN_OTHER_CYCLE_FAILS_CLOSED"
    prior = [e for e in visible if e["camis"] == a_event["camis"]
             and (e["date"], e["type"]) < (a_event["date"], a_event["type"])
             and e["date"] <= a_event["date"]]
    for prev in reversed(prior):
        if (a_event["date"] - prev["date"]).days > lookback:
            break                                   # too far back to be its parent
        pt = prev["type"].lower()
        if not pt:
            return "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"   # unclassifiable between
        if "initial" not in pt:
            continue                                # walk past other visits
        if prev["score"] is None:
            return "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"   # cannot confirm it failed
        return ("ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL" if prev["score"] >= fail
                else "ORIGIN_REINSP_AFTER_PASSED_INITIAL")
    return "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED"           # no parent in range


# The registered mapping from origin to level. `moderate` appears nowhere.
_ORIGIN_LEVEL = {
    "ORIGIN_INITIAL": "strong",
    "ORIGIN_REINSP_CONFIRMED_FAILED_INITIAL": "limited",
    "ORIGIN_REINSP_AFTER_PASSED_INITIAL": "limited",
    "ORIGIN_REINSP_UNCONFIRMED_FAILS_CLOSED": "limited",
    "ORIGIN_OTHER_CYCLE_FAILS_CLOSED": "limited",
}


def classify(events, asof, reg):
    """The registered mapping (section 9), evaluated in registered order:
    scope, then abstention, then levels. Age is a currentness gate only - it
    decides whether the engine speaks, never which ordered level it says.
    """
    visible = reconstruct(events, asof)             # defensive: enforce the wall here too

    graded = [e for e in visible if e["grade"] in ("A", "B", "C")]
    if not graded:
        return {"state": "not_enough_current_evidence",
                "reasons": ["NO_GRADED_RECORD"], "evidence_age_days": None}
    displayed = graded[-1]

    if displayed["grade"] != "A":
        return {"state": "displayed_grade_not_a",
                "reasons": ["DISPLAYED_GRADE_NOT_A"],
                "displayed_grade": displayed["grade"],
                "evidence_age_days": (asof - displayed["date"]).days}

    if not _is_eligible_a_event(displayed):
        return {"state": "not_enough_current_evidence",
                "reasons": ["A_EVENT_NOT_ELIGIBLE"],
                "evidence_age_days": (asof - displayed["date"]).days}

    age = (asof - displayed["date"]).days
    if age > int(reg["age_policy"]["abstain_after_days"]):
        return {"state": "not_enough_current_evidence",
                "reasons": ["EVIDENCE_TOO_OLD"], "evidence_age_days": age}

    origin = _origin(visible, displayed, reg)
    return {"state": _ORIGIN_LEVEL[origin], "reasons": [origin],
            "evidence_age_days": age,
            "a_event_date": displayed["date"].isoformat(),
            "a_event_score": displayed["score"]}


def pair_outcome(events, asof, reg):
    """The registered outcome and nothing else: the next Cycle Initial
    Inspection with a score, STRICTLY after the as-of date. This function is
    the only place future rows are read, and classify() never calls it."""
    fail = float(reg["outcome"]["failure_threshold"])
    for e in events:
        if e["date"] <= asof:
            continue
        t = e["type"].lower()
        if _is_cycle(t) and "initial" in t and "reopen" not in t and e["score"] is not None:
            return {"censored": False, "next_date": e["date"].isoformat(),
                    "next_score": e["score"], "failed": e["score"] >= fail}
    return {"censored": True, "reasons": ["OUTCOME_CENSORED"]}


def observe(events_by_camis, reg, with_outcomes=True, asof_before=None):
    """Backtest units, per the registration (section 4): one observation per
    (camis, eligible graded full-cycle A event), as-of that event's date.

    `asof_before` bounds which as-of dates are observed at all - the runner
    uses it to keep this rung inside the development window. Censored and
    excluded strata are counted, never silently dropped.
    """
    obs = []
    for camis in sorted(events_by_camis):
        evs = events_by_camis[camis]
        for e in evs:
            if not _is_eligible_a_event(e):
                continue
            if asof_before is not None and e["date"] >= asof_before:
                continue
            asof = e["date"]
            row = {"camis": camis, "asof": asof.isoformat()}
            row.update(classify(evs, asof, reg))
            if with_outcomes:
                row["outcome"] = pair_outcome(evs, asof, reg)
            obs.append(row)
    return obs


def group_by_camis(events):
    out = {}
    for e in events:
        out.setdefault(e["camis"], []).append(e)
    return out


def canonical_json(obj):
    """Stable serialization: sorted keys, fixed separators, pure ASCII.
    Byte-identical output is a promise the gates verify, not a hope."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def envelope(payload, source, cutoff, reg):
    """Every result carries its provenance: the registration hash of record,
    engine version, methodology version, source identity, and data cutoff."""
    return {
        "registration_commit": REGISTRATION_COMMIT,
        "engine_version": ENGINE_VERSION,
        "methodology_version": reg["methodology_version"],
        "source": source,
        "source_data_cutoff": cutoff,
        "payload": payload,
    }
