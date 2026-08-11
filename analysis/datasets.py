#!/usr/bin/env python3
"""
The onboarded datasets. Adding one is an entry here — nothing else.

Every entry MUST declare `entity_key`. That is the grain contract: the column
that identifies the real-world thing a row is about. Without it the puller
cannot tell you whether 295,054 rows are 295,054 restaurants (they are not —
they are 31,194), and a row count reported as an entity count is the single
most common way these datasets produce a confidently wrong number.

`sources` is a list because a logical dataset is not always one endpoint:
"311 Service Requests from 2010 to Present" is TWO 4x4s. Sources are only
summed when their windows are disjoint, which is asserted, not assumed.
"""

DOMAIN = "data.cityofnewyork.us"

DATASETS = {
    "311": {
        "title": "311 Service Requests",
        "subtitle": "Every service request New York files with its city",
        "sources": [
            {"fourby": "76ig-c548", "label": "2010-2019"},
            {"fourby": "erm2-nwe9", "label": "2020-now"},
        ],
        "entity_key": "unique_key",      # genuinely unique: 22,017,681 of 22,017,681
        "entity_name": "service request",
        "date_col": "created_date",
        # A 311 row IS one request, so rows == entities here. Declaring it
        # anyway means the check runs and PROVES it rather than assuming it.
        "grain_note": "One row is one service request. Rows and entities match — "
                      "but they match because it was checked, not by assumption.",
        "dimensions": [
            {"col": "complaint_type", "label": "Complaint type", "top": 12},
            {"col": "borough", "label": "Borough", "top": 8},
            {"col": "open_data_channel_type", "label": "Channel", "top": 6},
        ],
        "mutable": True,   # 95.3% of rows are updated after creation
        "coord_sentinel": ["latitude", "longitude"],
    },
    "restaurants": {
        "title": "Restaurant Inspections",
        "subtitle": "DOHMH violation citations for active NYC restaurants",
        "sources": [{"fourby": "43nn-pn8j", "label": "rolling 3yr"}],
        "entity_key": "camis",           # 295,054 rows -> 31,194 restaurants
        "entity_name": "restaurant",
        "date_col": "inspection_date",
        "grain_note": "One row is one VIOLATION CITATION, not one restaurant. "
                      "295,054 rows are 31,194 restaurants — 9.46 rows each. "
                      "A row count reported as a restaurant count is off 9.5x.",
        "dimensions": [
            {"col": "boro", "label": "Borough", "top": 8},
            {"col": "critical_flag", "label": "Criticality", "top": 5},
            {"col": "grade", "label": "Grade", "top": 8},
            {"col": "cuisine_description", "label": "Cuisine", "top": 12},
        ],
        # Rows the publisher marks as "never inspected". They carry a sentinel
        # date that poisons min() and no `action` value at all.
        "sentinel_where": "inspection_date > '1900-01-02T00:00:00'",
        # Null Island: 0.0 coordinates that IS NOT NULL does not catch.
        "coord_sentinel": ["latitude", "longitude"],
        # Metric columns and their NATURAL grain. The puller verifies
        # constancy server-side and records exceptions — averaging one of
        # these at row grain is biased by Cov(rows, value)/(E[n]E[s]).
        "metric_cols": [{"col": "score", "grain": "camis, inspection_date"}],
        "caveats": [
            "SURVIVORSHIP: only *active* restaurants are included. Establishments that "
            "failed and closed were removed, so this cannot answer whether bad "
            "inspections predict closure — the closures are gone.",
            "ROLLING WINDOW: three years prior to each restaurant's most recent "
            "inspection, not full history. Long-run trends are window artifacts.",
            "3,621 rows are dated 1900-01-01 (permit issued, never inspected) and are "
            "excluded from date math. They are exactly the rows where `action` is absent.",
            "The data dictionary documents boro as 1-5 numeric. Live values are "
            "title-case names; boro='3' returns 0 rows with HTTP 200.",
        ],
        "mutable": True,   # scores are "updated based on adjudication results"
    },
    "dob": {
        "title": "DOB Violations",
        "subtitle": "Department of Buildings violations, by building (BIN)",
        "sources": [{"fourby": "3h2n-5cm9", "label": "1980s-now"}],
        "entity_key": "bin",
        "entity_name": "building",
        "date_col": "issue_date",
        "grain_note": "One row is one DOB violation against a building. Joined to "
                      "restaurants via bin, which 98% of inspection rows carry.",
        "dimensions": [
            {"col": "violation_category", "label": "Category", "top": 10},
            {"col": "violation_type_code", "label": "Type", "top": 12},
        ],
        # Every column is TEXT, including dates. issue_date is YYYYMMDD as a
        # string and carries garbage (max observed value 'Y9990120'); bin has
        # a '0000000' sentinel plus literal TEST records. Fixed-width digit
        # strings compare correctly lexicographically, so the date fence
        # works as a string range.
        "sentinel_where": ("bin IS NOT NULL AND bin != '0000000' "
                           "AND issue_date >= '19800101' AND issue_date <= '20991231'"),
        "caveats": [
            "All columns are typed text, dates included. issue_date is a YYYYMMDD "
            "string with garbage sentinels — fence it as a string range.",
            "bin '0000000' is a sentinel, and TEST records exist (house_number='TEST').",
            "violation_category encodes open vs closed as substrings like "
            "'V*-DOB VIOLATION - ACTIVE'; ~23% of rows are active.",
            "No zipcode and no coordinates — the ONLY join to restaurants is bin.",
        ],
        "mutable": True,   # dispositions update rows in place
    },
}


def get(key):
    if key not in DATASETS:
        raise KeyError(f"unknown dataset {key!r}; have {list(DATASETS)}")
    return DATASETS[key]
