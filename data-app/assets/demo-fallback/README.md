# Demo fallback pack

Screenshots of the operator page's happy path, captured from the LIVE
GitHub Pages site + live Socrata reads. If the live demo fails on stage,
open these — each is a dated, truthful record of what the page rendered.

- `01-picker-moge-tee.png` — search "moge tee" → the 5-location picker
- `02-record-moge-tee-main-st.png` — the 42-35 Main Street record: the
  5-days-since clock, the 04L pattern banner (3 of 3, 41%, n=2,169), the
  ranked fix-first list, and the "what this cannot tell you" block
- `03-picker-kingston-pizza.png` — the backup subject's picker (2 rows)
- `04-record-kingston-pizza.png` — Kingston Pizza (CAMIS 41555612) record

Regenerate the night before presenting (data drifts as the city inspects):

    node analysis/capture_demo_fallback.mjs

Requires desktop Chrome; uses puppeteer-core (npm i puppeteer-core).
