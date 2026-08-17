# DataHub — how this survives leaving GitHub Pages

GitHub Pages is the current host, not the destination. This note records what
was built so the move is a config change rather than a rewrite, and what has to
be true before any of it lands inside ClickReserv's food side.

## The one rule that makes it portable

**All city-data access goes through `lib/nyc-sources.js`. Pages never call an
API directly.** That module owns the dataset registry, the verified string
literals, SoQL escaping, the pure logic, and — critically — a swappable
transport:

```js
configure({ mode: 'direct' })                                  // static host, today
configure({ mode: 'proxy', proxyBase: '/api/publicdata' })     // inside an app
```

`direct` has the browser call `data.cityofnewyork.us` itself: no key, no
secret, correct for a static host. `proxy` sends every read to a server route
that can cache, rate-limit, attach an app token, and keep a city API from being
hit once per page view. Nothing else in the codebase knows which is active.

The module runs unchanged in a browser (ES module) and in Node ≥ 18 (global
`fetch`), so the same file backs the page, a future server route, and tests.

## What is already app-shaped

| Concern | State |
|---|---|
| Data access | one module, swappable transport |
| Verified literals | `VERIFIED` block, with the false-zero lesson written into the comment |
| Identity/eligibility logic | pure functions (`bblIsValid`, `lotSharing`, `dedupeInspections`) — no IO, portable to TypeScript as-is |
| Governance | `isRatingEligible(source)` is mechanical: `performedBy === 'city'` |
| Tool registration | one manifest line, no build step |
| Secrets | none in the client, by construction |

## What still has to be built before the move

1. **A caching proxy route.** `GET /api/publicdata/:datasetId?$select=…`, passing
   SoQL through to Socrata with a short TTL cache keyed on the full query
   string. Restaurant inspections update roughly daily, so a 6–12h TTL is
   generous. This is the single new server component.
2. **A cache warmer or nothing.** Live-read is honest and simple; if page
   volume ever makes that rude to the city, the proxy is where a warm store
   goes — not the page.
3. **A rate limit and a circuit breaker.** When the city's API is down the page
   must say so (it already does) rather than show a stale number as if fresh.
4. **Server-side render or not.** Nothing here needs it. If SEO on individual
   restaurants ever matters, the proxy plus a static generator is the path;
   the logic module is already the shared core.

## If this becomes ClickReserv's food side

The pieces map cleanly, but three boundaries from the existing architecture
apply and must not be quietly crossed:

- **Public-record display is not the rating.** IRC v1 stays locked at
  registration `64c5bcd80c34f5e7ede884ab7f1ca9ccd382b940`. Building context is
  a separate panel that reads city records; it is never an input. Making it an
  input requires a new methodology version, a new registration, and a fresh
  validation window — the process registered in
  `IRC-V2-ENRICHMENT-PREREG.md` (`8a64204e…`).
- **311 is permanently display-only.** Public-submitted signals can be created
  by a competitor. `isRatingEligible()` enforces this in code so it cannot be
  forgotten in review.
- **Lot ≠ business.** 46.4% of NYC restaurants share a tax lot; the largest
  holds 93. Any surface showing lot-level facts must show the occupant count
  and say what it cannot attribute. The page does this today; a port must keep
  it.

The identity question this raises inside CR is the same one the
canonical-location work already answers: a BBL identifies a parcel, a
`canonical_location_id` identifies the physical business. Building context
attaches to the BBL; the merchant's reservable identity attaches to the
canonical location. They are different keys and must stay different columns.

## Cost of moving hosts, honestly

Low. The pages are static HTML with no build step, no framework, no
dependencies except a vendored `scrollama.min.js` used by one unrelated tool.
Moving to any static host is a file copy. Moving behind an app is the one-line
`configure()` change plus the proxy route above. The reason to move is not
capability — it is control over caching, rate limits, and uptime messaging.
