/**
 * nyc-sources.js — portable public-data access layer.
 *
 * WHY THIS FILE EXISTS SEPARATELY FROM THE PAGE
 * ---------------------------------------------
 * The pages are currently served as static files from GitHub Pages and talk
 * straight to the city's Socrata API from the browser. That will not be the
 * final home. When this moves behind a real app (ClickReserv's food side, or
 * any fleet host), the ONLY thing that has to change is the transport config
 * below — every query, every verified string literal, and every piece of
 * logic in this module ports unchanged:
 *
 *     configure({ mode: 'proxy', proxyBase: '/api/publicdata' })
 *
 * In 'direct' mode the browser calls data.cityofnewyork.us itself (no key, no
 * secret, fine for a static host). In 'proxy' mode every call goes to a server
 * endpoint that can cache, rate-limit, add an app token, and stop the city's
 * API from being hammered by every page view. Nothing else in the app knows
 * or cares which mode is active.
 *
 * Works unmodified in a browser (ES module) and in Node >= 18 (global fetch),
 * so the same file backs the page, a server route, and a test.
 */

/* ─── dataset registry ─────────────────────────────────────────────── */

export const SOURCES = {
  RESTAURANT_INSPECTIONS: {
    id: '43nn-pn8j',
    portal: 'https://data.cityofnewyork.us',
    label: 'DOHMH Restaurant Inspection Results',
    agency: 'NYC Department of Health and Mental Hygiene',
    performedBy: 'city',
    grain: 'one row per VIOLATION (an inspection appears on many rows)',
  },
  RODENT_INSPECTIONS: {
    id: 'p937-wjvj',
    portal: 'https://data.cityofnewyork.us',
    label: 'Rodent Inspection',
    agency: 'NYC Department of Health and Mental Hygiene',
    performedBy: 'city',
    grain: 'one row per rodent inspection visit at a tax lot',
  },
  SERVICE_311: {
    id: 'erm2-nwe9',
    portal: 'https://data.cityofnewyork.us',
    label: '311 Service Requests (2020–present)',
    agency: 'NYC 311',
    performedBy: 'public', // <-- NEVER a rating input. See governance note.
    grain: 'one row per complaint filed by a member of the public',
  },
  DCWP_INSPECTIONS: {
    id: 'jzhd-m6uv',
    portal: 'https://data.cityofnewyork.us',
    label: 'DCWP Inspections',
    agency: 'NYC Dept of Consumer and Worker Protection',
    performedBy: 'city',
    grain: 'one row per inspection of a licensed business',
  },
  DCWP_LICENSES: {
    id: 'w7w3-xahh',
    portal: 'https://data.cityofnewyork.us',
    label: 'DCWP Issued Licenses',
    agency: 'NYC Dept of Consumer and Worker Protection',
    performedBy: 'city',
    grain: 'one row per issued licence',
  },
};

/**
 * VERIFIED LITERALS — read from the live API's distinct values, never guessed.
 *
 * A wrong string literal here does not error. It returns zero rows and reads
 * like a confident finding. During discovery the guess 'Rat Activity' produced
 * a precise, totally false 0.0% — the real values are below, and they match
 * 526,855 rows. Treat every constant in this block as load-bearing: if you
 * change one, re-derive it from $select=<col>,count(*) AS n&$group=<col>.
 */
export const VERIFIED = {
  RODENT_RAT_FAIL: [
    'Failed for Rat Activity',
    'Failed for Rat Activity and Other Reason',
  ],
  RODENT_ALL_RESULTS: [
    'Passed', 'Bait applied', 'Failed for Rat Activity',
    'Failed for Other Reason', 'Failed for Rat Activity and Other Reason',
    'Monitoring visit', 'Stoppage done', 'Cleanup done',
  ],
  // 311 stores ONE concept under TWO different strings. Filtering either
  // alone silently drops the other.
  C311_RODENT: 'Rodent',
  C311_FOOD_ESTAB: 'Food Establishment',
  C311_FOOD_POISONING: 'Food Poisoning',
  C311_UNSANITARY: ['UNSANITARY CONDITION', 'Unsanitary Condition'],
};

/* ─── transport (the one swappable thing) ──────────────────────────── */

const transport = {
  mode: 'direct',       // 'direct' | 'proxy'
  proxyBase: null,      // e.g. '/api/publicdata'
  appToken: null,       // optional Socrata app token (proxy mode only)
  fetchImpl: null,      // injectable for tests
};

export function configure(opts = {}) {
  Object.assign(transport, opts);
  return { ...transport };
}
export function currentTransport() {
  return { ...transport };
}

function getFetch() {
  const f = transport.fetchImpl || (typeof fetch !== 'undefined' ? fetch : null);
  if (!f) throw new Error('nyc-sources: no fetch available; pass fetchImpl');
  return f;
}

/** Double single quotes — the SoQL string-literal escape. Katz's broke this once. */
export function soqlEscape(value) {
  return String(value).replace(/'/g, "''");
}

/** Build an `in(...)` clause from a list, escaped. */
export function soqlIn(values) {
  return values.map((v) => `'${soqlEscape(v)}'`).join(',');
}

/**
 * Run a SoQL query. `params` uses bare names ('select','where',…) and is
 * translated to the $-prefixed form, so callers never fight URL encoding.
 */
export async function query(source, params = {}) {
  const src = typeof source === 'string' ? { id: source, portal: SOURCES.RESTAURANT_INSPECTIONS.portal } : source;
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v === undefined || v === null) continue;
    qs.set(k.startsWith('$') ? k : `$${k}`, String(v));
  }
  const url = transport.mode === 'proxy'
    ? `${transport.proxyBase.replace(/\/$/, '')}/${src.id}?${qs}`
    : `${src.portal}/resource/${src.id}.json?${qs}`;

  const headers = {};
  if (transport.mode === 'proxy' && transport.appToken) headers['X-App-Token'] = transport.appToken;

  const res = await getFetch()(url, { headers });
  if (!res.ok) throw new Error(`${src.id} HTTP ${res.status}`);
  return res.json();
}

/* ─── pure helpers (no IO — unit-testable, portable to TS) ─────────── */

/** A usable Borough-Block-Lot is exactly 10 digits. 1.97% of restaurants
 *  carry a malformed one (e.g. the bare string "4") and 1.13% carry none. */
export function bblIsValid(bbl) {
  return typeof bbl === 'string' && /^\d{10}$/.test(bbl);
}

/** Lot occupancy governs what a lot-level fact is allowed to claim.
 *  46.4% of NYC restaurants share a lot with another restaurant. */
export function lotSharing(occupantCount) {
  if (occupantCount <= 1) {
    return {
      shared: false,
      strength: 'attributable',
      note: 'Sole business of its kind on this tax lot, so lot-level records are unambiguous.',
    };
  }
  return {
    shared: true,
    strength: occupantCount > 5 ? 'weak' : 'ambiguous',
    note: `${occupantCount} businesses share this tax lot. Lot-level records are shared by all of them and cannot say which one they concern.`,
  };
}

/** Collapse the violation-grain inspection rows into one row per inspection. */
export function dedupeInspections(rows) {
  const seen = new Map();
  for (const r of rows) {
    const key = `${r.inspection_date}|${r.score ?? ''}|${r.grade ?? ''}`;
    if (!seen.has(key)) seen.set(key, r);
  }
  return [...seen.values()].sort((a, b) =>
    String(b.inspection_date).localeCompare(String(a.inspection_date)));
}

export function daysAgoISO(days) {
  return new Date(Date.now() - days * 86400000).toISOString().slice(0, 19);
}

/* ─── composite reads ──────────────────────────────────────────────── */

export async function searchRestaurants(term, limit = 12) {
  const t = soqlEscape(term.toUpperCase());
  const rows = await query(SOURCES.RESTAURANT_INSPECTIONS, {
    select: 'camis,dba,building,street,boro,zipcode,bbl,cuisine_description',
    where: `upper(dba) like '%${t}%'`,
    group: 'camis,dba,building,street,boro,zipcode,bbl,cuisine_description',
    limit,
  });
  return rows;
}

/**
 * Building context for one restaurant. Everything returned here is a
 * LOT-LEVEL fact except `inspections`, which is the restaurant's own record.
 */
export async function getBuildingContext(camis, { windowDays = 365 } = {}) {
  const id = soqlEscape(camis);
  const base = await query(SOURCES.RESTAURANT_INSPECTIONS, {
    select: 'camis,dba,building,street,boro,zipcode,bbl,cuisine_description',
    where: `camis='${id}'`,
    limit: 1,
  });
  if (!base.length) return null;
  const restaurant = base[0];
  const bbl = restaurant.bbl;

  const inspections = dedupeInspections(await query(SOURCES.RESTAURANT_INSPECTIONS, {
    select: 'inspection_date,score,grade',
    where: `camis='${id}' AND score IS NOT NULL`,
    group: 'inspection_date,score,grade',
    order: 'inspection_date DESC',
    limit: 20,
  }));

  if (!bblIsValid(bbl)) {
    return {
      restaurant, bbl, eligible: false, inspections,
      ineligibleReason:
        'This record carries no usable Borough-Block-Lot number, so it cannot be linked to building records. About 3 in 100 restaurants are in this state.',
    };
  }

  const cutoff = daysAgoISO(windowDays);
  const [occupants, rodentFails, rodentAll, c311Rodent, c311Food] = await Promise.all([
    query(SOURCES.RESTAURANT_INSPECTIONS, {
      select: 'camis,dba', where: `bbl='${bbl}'`, group: 'camis,dba', limit: 300,
    }),
    query(SOURCES.RODENT_INSPECTIONS, {
      select: 'inspection_date,result',
      where: `bbl='${bbl}' AND inspection_date>'${cutoff}' AND result in(${soqlIn(VERIFIED.RODENT_RAT_FAIL)})`,
      order: 'inspection_date DESC', limit: 50,
    }),
    query(SOURCES.RODENT_INSPECTIONS, {
      select: 'count(*) AS n', where: `bbl='${bbl}' AND inspection_date>'${cutoff}'`,
    }),
    query(SOURCES.SERVICE_311, {
      select: 'count(*) AS n',
      where: `bbl='${bbl}' AND complaint_type='${VERIFIED.C311_RODENT}' AND created_date>'${cutoff}'`,
    }),
    query(SOURCES.SERVICE_311, {
      select: 'count(*) AS n',
      where: `bbl='${bbl}' AND complaint_type='${VERIFIED.C311_FOOD_ESTAB}' AND created_date>'${cutoff}'`,
    }),
  ]);

  return {
    restaurant, bbl, eligible: true, inspections, windowDays,
    occupants,
    sharing: lotSharing(occupants.length),
    cityPerformed: {
      rodentInspections: Number(rodentAll[0]?.n ?? 0),
      rodentRatFailures: rodentFails.length,
      rodentFailureRows: rodentFails,
    },
    publicReported: {
      rodentComplaints: Number(c311Rodent[0]?.n ?? 0),
      foodEstablishmentComplaints: Number(c311Food[0]?.n ?? 0),
    },
  };
}

/* ─── governance ───────────────────────────────────────────────────── */

/**
 * Which sources may ever feed a published rating.
 *
 * The Inspection Record Confidence lock reads: "This rating can't be bought or
 * changed by a business. It changes when the city record changes or when we
 * publish a new methodology version."
 *
 * 311 complaints are filed by members of the public. Admitting them to a
 * rating would hand a competitor, a landlord, or anyone with a grudge a lever
 * on a business's score. That is not what the lock promises, so the rule is
 * mechanical rather than a matter of judgement: only city-performed
 * observations are rating-eligible. 311 may be displayed, always attributed.
 */
export function isRatingEligible(source) {
  return source.performedBy === 'city';
}
