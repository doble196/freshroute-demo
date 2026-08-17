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

/* ═══════════════════════════════════════════════════════════════════
   VERTICALS — beyond restaurants
   ═══════════════════════════════════════════════════════════════════

   ClickReserv's template catalogue spans ~197 business types. Only some of
   them are inspected by a public body that publishes the result. This registry
   records which ones ARE, with the dataset, the query shape, and how to read
   the outcome — every value verified against the live API, never guessed.

   Most entries share ONE code path: DCWP inspects many licensed trades and
   files them all in jzhd-m6uv under a `business_category`. Adding another DCWP
   trade is a single object here, no new code.
*/

export const DCWP_CATEGORIES = {
  SALON_BARBERSHOP: 'Salons And Barbershop - 841',
  CAR_WASH: 'Car Wash',
  TAX_PREPARER: 'Tax Preparers - 891',
  IMMIGRATION: 'Immigration Svc Prv - 893',
  MOBILE_FOOD: 'Mobile Food Vendor - 881',
  LAUNDRY: 'Retail Laundry',
  DRY_CLEANER: 'Dry Cleaners - 230',
  GARAGE: 'Garage & Parking Lot - 098',
  RESTAURANT_DCWP: 'Restaurant - 818',
};

/** DCWP inspection_status values, verified by frequency over all 270,138 rows.
 *  Grouped by what they actually mean for a reader. */
export const DCWP_OUTCOME = {
  bad: ['Violation Issued', 'Fail', 'Business Padlocked', 'Posting Order Served'],
  good: ['No Violation Issued', 'Pass', 'No Warning Issued'],
  neutral: ['Re-inspection', 'Completed', 'Warning', 'NOH Withdrawn', 'Mediation'],
  gone: ['Out of Business', 'Closed', 'No Evidence of Activity', 'Unable to Locate'],
};

export function readDcwpOutcome(status) {
  for (const [kind, list] of Object.entries(DCWP_OUTCOME)) {
    if (list.includes(status)) return kind;
  }
  return 'neutral';
}

export const VERTICALS = {
  restaurant: {
    label: 'Restaurant / café / bar',
    crTemplates: ['restaurant', 'coffee-shop', 'bakery', 'bar-cocktail-lounge', 'tapas-wine-bar', 'live-music-bar'],
    kind: 'dohmh_restaurant',
    source: SOURCES.RESTAURANT_INSPECTIONS,
    nameField: 'dba',
    dateField: 'inspection_date',
    outcomeLabel: 'Score and letter grade',
    inspector: 'NYC Health Dept (DOHMH)',
    note: 'The most complete inspection record the city publishes. 31,274 businesses.',
  },
  salon_barbershop: {
    label: 'Barbershop / hair / nail / lash salon',
    crTemplates: ['barbershop', 'hair-salon', 'nail-salon', 'blow-dry-bar', 'hair-braiding',
      'hair-extensions', 'lash-brow-studio', 'waxing-studio', 'threading-salon', 'mens-grooming-lounge'],
    kind: 'dcwp',
    category: DCWP_CATEGORIES.SALON_BARBERSHOP,
    outcomeLabel: 'Violation issued, or not',
    inspector: 'NYC Consumer & Worker Protection (DCWP)',
    note: '8,487 distinct salons and barbershops with inspections on file; 99.1% carry a tax lot.',
  },
  car_wash: {
    label: 'Car wash',
    crTemplates: ['car-wash', 'auto-detailing'],
    kind: 'dcwp', category: DCWP_CATEGORIES.CAR_WASH,
    outcomeLabel: 'Violation issued, or not',
    inspector: 'NYC Consumer & Worker Protection (DCWP)',
    note: 'Licensed car washes only.',
  },
  tax_prep: {
    label: 'Tax preparer',
    crTemplates: ['tax-prep', 'bookkeeping-accounting'],
    kind: 'dcwp', category: DCWP_CATEGORIES.TAX_PREPARER,
    outcomeLabel: 'Violation issued, or not',
    inspector: 'NYC Consumer & Worker Protection (DCWP)',
    note: 'DCWP enforces disclosure rules for paid preparers.',
  },
  immigration: {
    label: 'Immigration services provider',
    crTemplates: ['immigration-visa-consultant'],
    kind: 'dcwp', category: DCWP_CATEGORIES.IMMIGRATION,
    outcomeLabel: 'Violation issued, or not',
    inspector: 'NYC Consumer & Worker Protection (DCWP)',
    note: 'A trade with strong consumer-protection enforcement.',
  },
  food_truck: {
    label: 'Mobile food vendor / food truck',
    crTemplates: ['food-truck'],
    kind: 'dcwp', category: DCWP_CATEGORIES.MOBILE_FOOD,
    outcomeLabel: 'Violation issued, or not',
    inspector: 'NYC Consumer & Worker Protection (DCWP)',
    note: 'Mobile vendors also appear in DOHMH food data under separate permits.',
  },
  pool: {
    label: 'Swimming pool (swim school, gym pool, spa)',
    crTemplates: ['swim-school', 'local-gym', 'wellness-spa'],
    kind: 'pool',
    source: { id: '3kfa-rvez', portal: 'https://data.cityofnewyork.us', label: 'Pool Inspections',
      agency: 'NYC Department of Health and Mental Hygiene', performedBy: 'city' },
    outcomeLabel: 'Counted violations, including critical ones',
    inspector: 'NYC Health Dept (DOHMH)',
    note: '7,080 inspections. Publishes violation COUNTS, including a separate critical count.',
  },
  childcare: {
    label: 'Daycare / childcare centre',
    crTemplates: ['daycare', 'summer-camp'],
    kind: 'childcare',
    source: { id: 'dsg6-ifza', portal: 'https://data.cityofnewyork.us', label: 'Childcare Center Inspections',
      agency: 'NYC Department of Health and Mental Hygiene', performedBy: 'city' },
    outcomeLabel: 'Violation rate vs the city average',
    inspector: 'NYC Health Dept (DOHMH)',
    note: '27,828 rows. Publishes each centre\'s violation rate AND the city average beside it.',
  },
};

/** Search any vertical by business name. Returns a normalised shape so the UI
 *  does not branch per dataset. */
export async function searchVertical(verticalKey, term, limit = 12) {
  const v = VERTICALS[verticalKey];
  if (!v) throw new Error(`unknown vertical ${verticalKey}`);
  const t = soqlEscape(term.toUpperCase());

  if (v.kind === 'dohmh_restaurant') {
    const rows = await query(v.source, {
      select: 'camis,dba,building,street,boro,zipcode,bbl',
      where: `upper(dba) like '%${t}%'`,
      group: 'camis,dba,building,street,boro,zipcode,bbl', limit,
    });
    return rows.map((r) => ({ id: r.camis, name: r.dba, bbl: r.bbl,
      address: `${r.building ?? ''} ${r.street ?? ''}`.trim(), locality: `${r.boro ?? ''} ${r.zipcode ?? ''}`.trim() }));
  }
  if (v.kind === 'dcwp') {
    const rows = await query(SOURCES.DCWP_INSPECTIONS, {
      select: 'business_name,bbl,street_1,city,zip_code',
      where: `business_category='${soqlEscape(v.category)}' AND upper(business_name) like '%${t}%'`,
      group: 'business_name,bbl,street_1,city,zip_code', limit,
    });
    return rows.map((r) => ({ id: r.business_name, name: r.business_name, bbl: r.bbl,
      address: r.street_1 ?? '', locality: `${r.city ?? ''} ${r.zip_code ?? ''}`.trim() }));
  }
  if (v.kind === 'pool') {
    const rows = await query(v.source, {
      select: 'facility_name,bbl,address_no,address_st,bo,zip',
      where: `upper(facility_name) like '%${t}%'`,
      group: 'facility_name,bbl,address_no,address_st,bo,zip', limit,
    });
    return rows.map((r) => ({ id: r.facility_name, name: r.facility_name, bbl: r.bbl,
      address: `${r.address_no ?? ''} ${r.address_st ?? ''}`.trim(), locality: `${r.bo ?? ''} ${r.zip ?? ''}`.trim() }));
  }
  if (v.kind === 'childcare') {
    const rows = await query(v.source, {
      select: 'centername,building,street,borough,zipcode,bin',
      where: `upper(centername) like '%${t}%'`,
      group: 'centername,building,street,borough,zipcode,bin', limit,
    });
    return rows.map((r) => ({ id: r.centername, name: r.centername, bin: r.bin, bbl: null,
      address: `${r.building ?? ''} ${r.street ?? ''}`.trim(), locality: `${r.borough ?? ''} ${r.zipcode ?? ''}`.trim() }));
  }
  throw new Error(`vertical kind ${v.kind} has no search`);
}

/** Inspection history for one business, normalised across datasets. */
export async function getVerticalInspections(verticalKey, id, limit = 12) {
  const v = VERTICALS[verticalKey];
  const key = soqlEscape(id);

  if (v.kind === 'dohmh_restaurant') {
    const rows = dedupeInspections(await query(v.source, {
      select: 'inspection_date,score,grade',
      where: `camis='${key}' AND score IS NOT NULL`,
      group: 'inspection_date,score,grade', order: 'inspection_date DESC', limit: 30,
    }));
    return rows.slice(0, limit).map((r) => ({
      date: String(r.inspection_date).slice(0, 10),
      headline: r.grade ? `Grade ${r.grade}` : `Score ${r.score}`,
      detail: `score ${r.score}`,
      kind: Number(r.score) >= 28 ? 'bad' : Number(r.score) >= 14 ? 'neutral' : 'good',
    }));
  }
  if (v.kind === 'dcwp') {
    const rows = await query(SOURCES.DCWP_INSPECTIONS, {
      select: 'date_of_occurrence,inspection_status,inspection_type',
      where: `business_category='${soqlEscape(v.category)}' AND business_name='${key}'`,
      order: 'date_of_occurrence DESC', limit,
    });
    return rows.map((r) => ({
      date: String(r.date_of_occurrence).slice(0, 10),
      headline: r.inspection_status,
      detail: r.inspection_type,
      kind: readDcwpOutcome(r.inspection_status),
    }));
  }
  if (v.kind === 'pool') {
    const rows = await query(v.source, {
      select: 'inspection_date,inspection_type,of_all_violations,of_critical_violations',
      where: `facility_name='${key}'`, order: 'inspection_date DESC', limit,
    });
    return rows.map((r) => {
      const crit = Number(r.of_critical_violations ?? 0), all = Number(r.of_all_violations ?? 0);
      return {
        date: String(r.inspection_date).slice(0, 10),
        headline: crit > 0 ? `${crit} critical violation${crit > 1 ? 's' : ''}` : all > 0 ? `${all} violation${all > 1 ? 's' : ''}` : 'No violations',
        detail: r.inspection_type ?? '',
        kind: crit > 0 ? 'bad' : all > 0 ? 'neutral' : 'good',
      };
    });
  }
  if (v.kind === 'childcare') {
    const rows = await query(v.source, {
      select: 'inspectiondate,violationratepercent,violationavgratepercent,programtype,maximumcapacity',
      where: `centername='${key}'`, limit,
    }).catch(() => query(v.source, {
      select: 'violationratepercent,violationavgratepercent,programtype,maximumcapacity',
      where: `centername='${key}'`, limit,
    }));
    return rows.map((r) => {
      const rate = Number(r.violationratepercent ?? 0), avg = Number(r.violationavgratepercent ?? 0);
      return {
        date: r.inspectiondate ? String(r.inspectiondate).slice(0, 10) : '—',
        headline: `${rate}% violation rate`,
        detail: `city average ${avg}%${r.programtype ? ' · ' + r.programtype : ''}`,
        kind: avg > 0 && rate > avg ? 'bad' : rate === 0 ? 'good' : 'neutral',
      };
    });
  }
  throw new Error(`vertical kind ${v.kind} has no history reader`);
}
