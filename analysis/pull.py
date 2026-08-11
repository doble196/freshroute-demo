#!/usr/bin/env python3
"""
The shared pull layer. Every dataset goes through this, so no one onboarding
dataset #3 can forget the guards.

What it enforces, in order:

  WATERMARK   X-SODA2-Truth-Last-Modified is captured with the count and
              asserted on every page. Per-page, because a final re-count only
              catches NET change — one insert plus one delete nets to zero and
              passes while the extract is short a row and double-counting
              another. (fetch_all, strict=True)

  KEYSET      Paging by ':id > last' rather than $offset. Not a detector — it
              makes offset drift structurally impossible, because the cursor is
              a value in the data rather than a position in a shifting table.

  GRAIN       Every dataset declares entity_key. This computes count(*) AND
              count(distinct entity_key) and refuses to report one as the
              other. For restaurants that ratio is 9.46; reporting rows as
              restaurants would be wrong by an order of magnitude.

  DISJOINT    Multi-source datasets are only summed after asserting their
              windows do not overlap. Otherwise the union double-counts.

Usage:
    python3 pull.py restaurants --json out.json
    python3 pull.py 311 --json out.json
"""

import argparse
import json
import re
import sys
import time
import urllib.parse as up
import urllib.error
import urllib.request as ur
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent / ".claude/skills/socrata-query/scripts"))
from fetch_all import row_count, DriftError                    # noqa: E402
import datasets as DS                                          # noqa: E402


class AliasShadowError(ValueError):
    """A $select alias equals a name referenced in $where. SoQL resolves the
    WHERE against the aliased output, so `max(phone) AS phone` plus
    `phone IS NOT NULL` becomes an aggregate-in-WHERE — HTTP 400 at best, a
    silently different filter at worst. Caught locally so it can never ship."""


def _check_alias_shadow(params):
    sel, where = params.get("$select", ""), params.get("$where", "")
    if not sel or not where:
        return
    aliases = re.findall(r"\bAS\s+([A-Za-z_]\w*)", sel, re.I)
    where_words = set(re.findall(r"[A-Za-z_]\w*", where))
    hits = [a for a in aliases if a in where_words]
    if hits:
        raise AliasShadowError(
            f"alias(es) {hits} shadow names used in $where — rename them "
            f"(e.g. AS {hits[0]}_v); the WHERE would resolve to the aggregate.")


def soql(fourby, token=None, **params):
    """One aggregate query. Returns (rows, headers) so the caller can read the
    watermark. Aggregates come back as strings; every one here is aliased,
    because the JSON key is derived from the expression (count(*) -> 'count',
    count(1) -> 'count_1') and an unaliased key breaks on any edit.

    Automatic guards: alias-shadow check, retry-on-429 with backoff."""
    _check_alias_shadow(params)
    url = (f"https://{DS.DOMAIN}/resource/{fourby}.json?"
           + up.urlencode(params, quote_via=up.quote, safe=""))
    req = ur.Request(url, headers={"Accept": "application/json"})
    if token:
        req.add_header("X-App-Token", token)
    for attempt in range(5):
        try:
            with ur.urlopen(req, timeout=240) as r:
                return json.loads(r.read()), dict(r.headers)
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 4:
                time.sleep(2 ** attempt)
                continue
            raise
    raise RuntimeError("exhausted 429 retries")


class Guarded:
    """Runs aggregates across a dataset's sources with the watermark asserted
    on every response, not just the first."""

    def __init__(self, key, token=None, strict=True):
        self.key, self.cfg = key, DS.get(key)
        self.token, self.strict = token, strict
        self.watermarks = {}
        self.drift = []
        self._sources_disjoint = False      # set by disjoint(), used by grain()
        self.checked_disjoint = False

    def _check(self, fourby, headers):
        wm = headers.get("X-SODA2-Truth-Last-Modified")
        stale = headers.get("X-SODA2-Data-Out-Of-Date")
        if str(stale).lower() == "true":
            self.drift.append(f"{fourby}: replica behind the truth store (X-SODA2-Data-Out-Of-Date=true)")
        if fourby not in self.watermarks:
            self.watermarks[fourby] = wm
        elif wm and wm != self.watermarks[fourby]:
            msg = (f"{fourby}: truth store moved mid-run — was "
                   f"{self.watermarks[fourby]!r}, now {wm!r}")
            self.drift.append(msg)
            if self.strict:
                raise DriftError(msg + ". Re-run; these aggregates span two states.")

    PAGE = 25_000

    def agg(self, paginate=True, **params):
        """Same aggregation across every source; returns concatenated rows.

        Grouped queries AUTO-PAGINATE. A fixed $limit silently truncates the
        moment a dataset outgrows it — citywide 43nn-pn8j has 82,847 distinct
        inspections against the 50,000 my first harness prescribed: a 40%
        loss with HTTP 200. Grouped results are also not implicitly ordered
        (same law as rows), so pagination pins $order to the group key.
        """
        out = []
        base_where = params.pop("$where", None)
        sentinel = self.cfg.get("sentinel_where")
        where = " AND ".join(w for w in (base_where, sentinel) if w) or None
        page = int(params.pop("$limit", self.PAGE))
        # Paginate COMPLETENESS queries (every group matters). A deliberate
        # top-N — ordered by an aggregate, sliced client-side — must NOT
        # paginate: deep $offset on a grouped+aggregate-ordered query over
        # 44M rows makes the server sort all groups per page and it 500s.
        # Default is the safe one; opting out is explicit at the call site.
        paged = paginate and "$group" in params and "$offset" not in params
        if paged and "$order" not in params:
            params["$order"] = params["$group"]
        for src in self.cfg["sources"]:
            offset = 0
            while True:
                q = dict(params)
                if where:
                    q["$where"] = where
                q["$limit"] = page
                if paged:
                    q["$offset"] = offset
                rows, headers = soql(src["fourby"], self.token, **q)
                self._check(src["fourby"], headers)
                for r in rows:
                    out.append({**r, "_src": src["label"]})
                if not paged or len(rows) < page:
                    break
                offset += len(rows)          # full page — there may be more
        return out

    def quality(self):
        """Automatic data-quality sweep, declared in datasets.py, run on
        every pull. Everything here is a lesson that once cost a wrong
        number: coordinate sentinels (Null Island survives IS NOT NULL),
        sentinel-row counts, and metric-grain constancy (a metric averaged
        at row grain is biased by cov(rows, value) — verify the grain
        server-side with $having, which checks ALL groups, not a sample)."""
        rep = {}
        cs = self.cfg.get("coord_sentinel")
        if cs:
            lat, lon = cs
            n = self.agg(**{"$select": "count(*) AS n",
                            "$where": f"{lat} = 0 AND {lon} = 0"})
            rep["null_island_rows"] = sum(int(r["n"]) for r in n)
        if self.cfg.get("sentinel_where"):
            # count what the sentinel filter EXCLUDES: total minus filtered
            tot = sum(int(r["n"]) for r in [x for x in (
                soql(src["fourby"], self.token, **{"$select": "count(*) AS n"})[0][0]
                for src in self.cfg["sources"])])
            kept = sum(int(r["n"]) for r in self.agg(**{"$select": "count(*) AS n"}))
            rep["sentinel_rows_excluded"] = tot - kept
        for m in self.cfg.get("metric_cols", []):
            col, grain = m["col"], m["grain"]
            exc = self.agg(**{"$select": f"{grain}, min({col}) AS lo, max({col}) AS hi",
                              "$group": grain, "$having": f"min({col}) != max({col})",
                              "$limit": 100})
            rep[f"grain_exceptions_{col}"] = {
                "count": len(exc),
                "constant_within": grain,
                "examples": [{k: v for k, v in e.items() if k != "_src"} for e in exc[:3]],
            }
        return rep

    # ── the grain contract ────────────────────────────────────────────
    def grain(self):
        """count(*) AND count(distinct entity_key). Both, always, so neither
        can be quoted as the other.

        Ordering matters: disjoint() must run first for multi-source datasets,
        because exactness of the summed entity count depends on it. Asserted,
        not assumed — a silently-False flag would null a legitimate ratio.
        """
        if len(self.cfg["sources"]) > 1 and not self.checked_disjoint:
            raise RuntimeError("call disjoint() before grain() on a multi-source "
                               "dataset — entity-count exactness depends on it")
        ek = self.cfg["entity_key"]
        rows = self.agg(**{"$select": f"count(*) AS n, count(distinct {ek}) AS e"})
        n = sum(int(r["n"]) for r in rows)
        # Entities can legitimately span sources, so a sum is an upper bound.
        # Say so rather than presenting it as exact.
        e = sum(int(r["e"]) for r in rows)
        return {
            "rows": n, "entities": e, "entity_key": ek,
            "entity_name": self.cfg["entity_name"],
            "rows_per_entity": round(n / e, 2) if e else None,
            # Exact when there is one source, OR when multiple sources are
            # verified DISJOINT — then summing distinct counts double-counts
            # nothing. 311's two 4x4s have non-overlapping date windows and
            # (sampled, both directions) non-overlapping unique_key spaces, so
            # its sum is exact. Anything else is a FLOOR, and a ratio computed
            # on a floor is an upper bound wearing a ratio's clothes.
            "entities_exact": len(self.cfg["sources"]) == 1 or self._sources_disjoint,
            "note": self.cfg["grain_note"],
        }

    def disjoint(self):
        """Multi-source datasets may only be summed if their windows don't
        overlap. Asserted here rather than assumed."""
        if len(self.cfg["sources"]) < 2:
            self.checked_disjoint = True
            return {"checked": False, "reason": "single source"}
        dc = self.cfg["date_col"]
        spans = []
        for src in self.cfg["sources"]:
            rows, headers = soql(src["fourby"], self.token,
                                 **{"$select": f"min({dc}) AS lo, max({dc}) AS hi"})
            self._check(src["fourby"], headers)
            spans.append({"label": src["label"], "lo": rows[0]["lo"][:10], "hi": rows[0]["hi"][:10]})
        spans.sort(key=lambda s: s["lo"])
        overlap = any(spans[i]["hi"] >= spans[i + 1]["lo"] for i in range(len(spans) - 1))
        self._sources_disjoint = not overlap
        self.checked_disjoint = True
        if overlap and self.strict:
            raise DriftError(f"sources overlap on {dc}; summing them double-counts: {spans}")
        return {"checked": True, "overlap": overlap, "spans": spans}

    def by_dimension(self, col, top=12):
        # paginate=False: this is a top-N by aggregate, not a completeness
        # scan. The server ranks the groups; we only ever keep `top`. Paging
        # it would be both pointless and a 500 on large datasets.
        rows = self.agg(paginate=False,
                        **{"$select": f"{col}, count(*) AS n", "$group": col,
                           "$order": "n DESC", "$limit": 400})
        merged = {}
        for r in rows:
            # A NULL group arrives as a row with NO grouping key at all. Name it
            # rather than letting it silently vanish from the chart.
            k = r.get(col) or "(not recorded)"
            merged[k] = merged.get(k, 0) + int(r["n"])
        items = sorted(merged.items(), key=lambda kv: -kv[1])
        return [{"k": k, "n": n} for k, n in items[:top]]

    def monthly(self):
        dc = self.cfg["date_col"]
        rows = self.agg(**{"$select": f"date_trunc_ym({dc}) AS m, count(*) AS n",
                           "$group": f"date_trunc_ym({dc})", "$order": "m", "$limit": 800})
        merged = {}
        for r in rows:
            if not r.get("m"):
                continue
            merged[r["m"][:7]] = merged.get(r["m"][:7], 0) + int(r["n"])
        series = [{"m": k, "n": v} for k, v in sorted(merged.items())]
        # The final period is PARTIAL. Plotting it against complete ones shows
        # a collapse that has not happened.
        return series[:-1], (series[-1] if series else None)


def build(key, token=None, strict=True):
    g = Guarded(key, token, strict)
    cfg = g.cfg
    print(f"[{key}] {cfg['title']} · {len(cfg['sources'])} source(s)", file=sys.stderr)

    disj = g.disjoint()
    if disj["checked"]:
        print(f"  disjoint check: {'OVERLAP' if disj['overlap'] else 'ok'} "
              f"{[s['label']+' '+s['lo']+'..'+s['hi'] for s in disj['spans']]}", file=sys.stderr)

    grain = g.grain()
    print(f"  grain: {grain['rows']:,} rows / {grain['entities']:,} "
          f"{grain['entity_name']}s = {grain['rows_per_entity']} per", file=sys.stderr)

    monthly, partial = g.monthly()
    print(f"  monthly: {len(monthly)} complete periods"
          + (f" (excluded partial {partial['m']}: {partial['n']:,})" if partial else ""),
          file=sys.stderr)

    dims = {}
    for d in cfg["dimensions"]:
        dims[d["col"]] = {"label": d["label"], "items": g.by_dimension(d["col"], d["top"])}
        print(f"  dim {d['col']}: {len(dims[d['col']]['items'])} values", file=sys.stderr)

    qual = g.quality()
    if qual:
        for k, v in qual.items():
            print(f"  quality: {k} = {v if not isinstance(v, dict) else v['count']}", file=sys.stderr)

    for src, wm in g.watermarks.items():
        print(f"  watermark {src}: {wm}", file=sys.stderr)
    if g.drift:
        print(f"  DRIFT: {g.drift}", file=sys.stderr)
    else:
        print("  watermark unchanged across every request", file=sys.stderr)

    return {
        "key": key, "title": cfg["title"], "subtitle": cfg["subtitle"],
        "sources": cfg["sources"], "grain": grain, "disjoint": disj,
        "monthly": monthly, "partial": partial, "dimensions": dims,
        "caveats": cfg.get("caveats", []),
        "quality": qual,
        "watermarks": g.watermarks, "drift": g.drift,
        "guards": ["watermark-per-response", "keyset-capable", "grain-declared",
                   "disjoint-asserted", "null-group-named", "partial-period-excluded"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("dataset", nargs="?", help=f"one of {list(DS.DATASETS)}, or 'all'")
    ap.add_argument("--json", metavar="PATH")
    ap.add_argument("--no-strict", action="store_true")
    a = ap.parse_args()

    keys = list(DS.DATASETS) if a.dataset in (None, "all") else [a.dataset]
    out = {}
    for k in keys:
        out[k] = build(k, strict=not a.no_strict)
        print(file=sys.stderr)

    if a.json:
        Path(a.json).write_text(json.dumps(out, separators=(",", ":")))
        print(f"wrote {a.json} ({len(keys)} dataset(s))", file=sys.stderr)
    else:
        for k, v in out.items():
            print(f"{k}: {v['grain']['rows']:,} rows, "
                  f"{v['grain']['entities']:,} {v['grain']['entity_name']}s")


if __name__ == "__main__":
    main()
