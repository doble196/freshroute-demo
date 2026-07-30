// FreshRoute morning triage board — DOM + render only.
// All data logic lives in logic.js, which review-test.js exercises directly,
// so the tested code and the shipped code are the same code.

import { C, EXPIRY_WINDOW_DAYS, ALL_LOCATIONS, parseCSV, audit, toSnapshot,
         reorderList, expiringSoon, byLocation, locationCounts, num,
         toCSV, ORDER_COLUMNS, groupByStorage, STORAGE_IS_PACKAGING, orderShortfall,
         morningBrief, briefPrompt, SOURCE_KINDS, DATA_SOURCE,
         bySupplier, supplierOrderText, capWithExemptions } from "./logic.js";

const SOURCE = "data/dairy_dataset.csv";
const EXPECTED_MIN_ROWS = 4000;   // outside expectation — catches a truncated download
const MAX_ROWS_SHOWN = 20;        // attention is the budget, not screen space
const MAX_EXEMPT_SHOWN = 10;      // the exemption needs its own bound, or a bad
                                  // week defeats the cap it's an exception to

const $ = id => document.getElementById(id);
const esc = s => String(s ?? "").replace(/[<>&]/g, c => ({ "<": "&lt;", ">": "&gt;", "&": "&amp;" }[c]));

let STATE = { flagged: [], soon: [], review: [], snapshot: [], location: ALL_LOCATIONS,
              grouped: true, view: "urgency" };

// Two channels, and the routing is the whole point.
//
//   bad  / warn → ALWAYS visible. A parse failure or the DEMO notice changes
//                 whether the numbers can be trusted; burying either behind a
//                 toggle would be the silent failure this app exists to avoid.
//   ok   / info → collapsed. "parse clean — 4325 rows × 23 columns" is me
//                 reassuring myself, in a coordinator's face.
//
// Kept, not deleted: the diagnostics are honest and they prove the tool
// checked itself. They just shouldn't be the first thing she reads.
const QUIET = new Set(["ok", "info"]);   // "done" is deliberately absent — it confirms a user action
let quietCount = 0;


// Clipboard writes fail in plenty of real contexts — permissions policy, an
// iframe, a non-secure origin, a browser that wants a stricter gesture. Found
// by cold-testing: EVERY click here landed in the catch branch, and the
// fallback told a dairy coordinator to "see console".
//
// So the fallback has to be usable by someone who has never opened devtools:
// put the text on screen, selected, with Ctrl/Cmd-C as the instruction.
async function copyOrShow(text, btn, resetLabel) {
  const done = msg => {
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = resetLabel; }, 4000);
  };
  try {
    await navigator.clipboard.writeText(text);
    done("copied");
    return;
  } catch {}

  // Fallback 1 — the old execCommand path still works where the async API doesn't.
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.setAttribute("readonly", "");
  ta.style.cssText = "position:fixed;top:-1000px";
  document.body.appendChild(ta);
  ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch {}
  ta.remove();
  if (ok) { done("copied"); return; }

  // Fallback 2 — show it. Never send anyone to the console.
  const host = btn.parentElement;
  host.querySelector(".copybox")?.remove();
  const box = document.createElement("div");
  box.className = "copybox";
  box.innerHTML = `<p class="copybox-note">Couldn't copy automatically. ` +
    `Press <kbd>${navigator.platform.includes("Mac") ? "\u2318" : "Ctrl"}</kbd>+<kbd>C</kbd> to copy the selected text.</p>`;
  const area = document.createElement("textarea");
  area.className = "copybox-text";
  area.readOnly = true;
  area.value = text;
  area.rows = Math.min(14, text.split("\n").length + 1);
  box.appendChild(area);
  const close = document.createElement("button");
  close.type = "button"; close.className = "copybox-close"; close.textContent = "Done";
  close.onclick = () => box.remove();
  box.appendChild(close);
  host.appendChild(box);
  area.focus(); area.select();
  done("shown below");
}

function note(kind, msg) {
  const d = document.createElement("div");
  d.className = `msg ${kind}`;
  d.textContent = msg;

  if (QUIET.has(kind)) {
    $("techlog").appendChild(d);
    quietCount++;
    $("techSummary").textContent =
      `Technical details — ${quietCount} check${quietCount === 1 ? "" : "s"} passed`;
    $("tech").hidden = false;
  } else {
    $("log").appendChild(d);
  }
}

const HEAD = `<thead><tr>
    <th>Product</th><th>Brand</th><th>Location</th>
    <th class="n">On hand</th><th class="n">Min</th><th class="n">Supplier qty</th><th></th>
  </tr></thead>`;

// A cap may hide rows it ranked low. It may NOT hide a row that carries a
// second, different kind of urgency the ranking doesn't measure.
//
// This is an EXEMPTION, not a promotion. The severity ranking is untouched —
// these items are not claimed to be more urgent, only unmissable. Promoting
// them would mean blending "how short" with "how soon it expires" into one
// score, and nothing in the data supports a weighting.
//
// Replaces an earlier fix that only stated a COUNT of hidden conflicts. A
// count she can't act on without leaving the view is evidence where a
// decision belongs.
function exemptBlock(hiddenRows, label) {
  const { exempt: shown, exemptOverflow: over } =
    capWithExemptions(hiddenRows, 0, MAX_EXEMPT_SHOWN);
  const conflicts = { length: shown.length + over };
  if (!shown.length) return "";
  return `<div class="exempt">
    <p class="exempt-head">Shown regardless of rank — ${conflicts.length} item${conflicts.length === 1 ? "" : "s"}
       ${label} ${conflicts.length === 1 ? "is" : "are"} also expiring soon.</p>
    <table><tbody>${bodyRows(shown)}</tbody></table>
    ${over ? `<p class="more">+ ${over} more expiring — see the expiry panel.</p>` : ""}
  </div>`;
}

const expiryTag = r => r._expiresInDays !== undefined
  ? `<span class="tag warn-tag">expires in ${r._expiresInDays}d</span>` : "";

// The supplier's stated quantity, and — when it does not close the gap — how
// far short it leaves you. Silence here is what made the panel misleading.
const qtyCell = r => {
  const left = orderShortfall(r);
  return `<td class="n${left ? " short" : ""}">${Math.round(num(r[C.reorder]))}` +
    (left ? `<span class="short-tag" title="Ordering this leaves the item ${left} below its minimum">still ${left} short</span>` : "") +
    `</td>`;
};

const bodyRows = rows => rows.map(r => `<tr class="${r._expiresInDays !== undefined ? "conflict" : r._severity > 0.75 ? "critical" : ""}">
    <td><strong>${esc(r[C.product])}</strong></td><td>${esc(r[C.brand])}</td><td>${esc(r[C.location])}</td>
    <td class="n bad">${esc(r[C.stock])}</td><td class="n">${Math.round(num(r[C.threshold]))}</td>
    ${qtyCell(r)}<td>${expiryTag(r)}</td>
  </tr>`).join("");

// Grouped view: every group shows its FULL count in the header, and caps its
// visible rows. So the cap never hides the fact that a group is large.
function renderReorder(rows, grouped) {
  if (!rows.length) return `<p class="empty">Nothing below threshold here.</p>`;

  if (!grouped) {
    const shown = rows.slice(0, MAX_ROWS_SHOWN);
    const hidden = rows.slice(MAX_ROWS_SHOWN);
    const more = rows.length > MAX_ROWS_SHOWN
      ? `<p class="more">+ ${hidden.length} more below threshold — showing the ${MAX_ROWS_SHOWN} most urgent.</p>` : "";
    return `<table>${HEAD.replace("</tr>", "<th>Storage</th></tr>")}<tbody>` +
      rows.slice(0, MAX_ROWS_SHOWN).map(r => `<tr class="${r._expiresInDays !== undefined ? "conflict" : r._severity > 0.75 ? "critical" : ""}">
        <td><strong>${esc(r[C.product])}</strong></td><td>${esc(r[C.brand])}</td><td>${esc(r[C.location])}</td>
        <td class="n bad">${esc(r[C.stock])}</td><td class="n">${Math.round(num(r[C.threshold]))}</td>
        ${qtyCell(r)}<td>${esc(r[C.storage])} ${expiryTag(r)}</td>
      </tr>`).join("") + `</tbody></table>` + more + exemptBlock(hidden, "below the cut");
  }

  const groups = groupByStorage(rows);
  const perGroup = Math.max(5, Math.ceil(MAX_ROWS_SHOWN / groups.length));
  return groups.map(g => {
    const shown = g.rows.slice(0, perGroup);
    const hidden = g.rows.length - shown.length;
    const tag = STORAGE_IS_PACKAGING.has(g.storage)
      ? `<span class="tag" title="This value is packaging, not a storage temperature">packaging</span>` : "";
    const warn = g.unknown ? `<span class="tag warn-tag">not in declared order</span>` : "";
    return `<div class="group">
      <h3>${esc(g.storage)} ${tag}${warn}<span class="count">${g.rows.length} item${g.rows.length === 1 ? "" : "s"}</span></h3>
      <table>${HEAD}<tbody>${bodyRows(shown)}</tbody></table>
      ${hidden ? `<p class="more">+ ${hidden} more in this group.</p>` : ""}
      ${exemptBlock(g.rows.slice(perGroup), "in this group")}
    </div>`;
  }).join("");
}

function renderExpiry(rows) {
  if (!rows.length) return `<p class="empty">Nothing expiring in the next ${EXPIRY_WINDOW_DAYS} days here.</p>`;
  return `<table><thead><tr><th>Product</th><th>Brand</th><th>Location</th>
      <th class="n">Days left</th><th class="n">On hand</th><th>Storage</th></tr></thead><tbody>` +
    rows.slice(0, MAX_ROWS_SHOWN).map(r => `<tr class="${r._daysLeft <= 3 ? "critical" : ""}">
      <td><strong>${esc(r[C.product])}</strong></td><td>${esc(r[C.brand])}</td><td>${esc(r[C.location])}</td>
      <td class="n bad">${r._daysLeft}</td><td class="n">${esc(r[C.stock])}</td><td>${esc(r[C.storage])}</td>
    </tr>`).join("") + `</tbody></table>`;
}

function renderReview(rows) {
  // Was: "(Verified by review-test.js — 12 deliberately broken rows, all
  // caught.)" — a test filename in a coordinator's face. The reassurance is
  // worth keeping; it's the reason an empty panel here means "checked and
  // clear" rather than "the check didn't run". Say that in her terms.
  if (!rows.length)
    return `<p class="empty">Nothing needs review — every item had a readable ` +
           `stock count, reorder level and expiry date.</p>`;
  return `<table><thead><tr><th>Product</th><th>Location</th><th>Why</th></tr></thead><tbody>` +
    rows.map(r => `<tr><td>${esc(r[C.product])}</td><td>${esc(r[C.location])}</td>
      <td class="reason">${esc(r._reason)}</td></tr>`).join("") + `</tbody></table>`;
}


// Supplier cards. Conflicts lead, because a call where something shouldn't
// be reordered needs care more than the biggest call needs speed.
function renderSuppliers(groups, asOf) {
  if (!groups.length) return `<p class="empty">Nothing to order here.</p>`;
  return groups.map((g, i) => `
    <div class="supplier${g.conflicts ? " has-conflict" : ""}">
      <h3>${esc(g.supplier)}
        <span class="count">${g.rows.length} item${g.rows.length === 1 ? "" : "s"} ·
        ${g.sites} site${g.sites === 1 ? "" : "s"} · ${g.units} units</span></h3>
      ${g.conflicts ? `<p class="conflict-note">${g.conflicts} item${g.conflicts === 1 ? " is" : "s are"}
        also expiring within ${EXPIRY_WINDOW_DAYS} days — confirm before ordering.</p>` : ""}
      <table><thead><tr><th>Product</th><th>Location</th>
        <th class="n">On hand</th><th class="n">Min</th><th class="n">Supplier qty</th><th></th>
      </tr></thead><tbody>${g.rows.map(r => `<tr class="${r._expiresInDays !== undefined ? "conflict" : ""}">
        <td><strong>${esc(r[C.product])}</strong></td><td>${esc(r[C.location])}</td>
        <td class="n bad">${esc(r[C.stock])}</td><td class="n">${Math.round(num(r[C.threshold]))}</td>
        ${qtyCell(r)}
        <td>${r._expiresInDays !== undefined
          ? `<span class="tag warn-tag">expires in ${r._expiresInDays}d</span>` : ""}</td>
      </tr>`).join("")}</tbody></table>
      <button class="copyOrder" data-i="${i}" type="button">Copy order for ${esc(g.supplier)}</button>
    </div>`).join("");
}

// Everything the filter touches re-renders from STATE — one path, so the
// summary can never disagree with the tables below it.
function draw() {
  const loc = STATE.location;
  const flagged = byLocation(STATE.flagged, loc);
  const soon    = byLocation(STATE.soon, loc);
  const review  = byLocation(STATE.review, loc);
  const tracked = byLocation(STATE.snapshot, loc);

  // "Position" was my word for the data grain (product × brand × location).
  // A coordinator reorders "Amul Butter in Haryana" — that's an ITEM at a
  // site. Nobody says "I have 600 positions of milk." Renamed everywhere it
  // faces the user; the internal grain is unchanged.
  const sites = new Set(STATE.snapshot.map(r => r[C.location])).size;
  const scope = loc === ALL_LOCATIONS
    ? `tracking ${STATE.snapshot.length} items across ${sites} locations`
    : `tracking ${tracked.length} items in ${loc}`;

  $("summary").textContent =
    `${flagged.length} below reorder threshold · ${soon.length} expiring within ${EXPIRY_WINDOW_DAYS} days · ` +
    `${review.length} need review · ${scope}`;

  // When filtered, say what's being hidden. A quiet filter is a lying filter.
  $("scope").innerHTML = loc === ALL_LOCATIONS ? "" :
    `<span class="filtered">Filtered to <strong>${esc(loc)}</strong> — ` +
    `${STATE.flagged.length - flagged.length} flagged item(s) in other locations are hidden. ` +
    `<button id="clear" type="button">Show all</button></span>`;

  const brief = morningBrief(tracked, flagged, soon, review, STATE.conflicts ?? []);
  $("briefHeading").textContent = `— what ${tracked.length} items add up to`;
  $("brief").innerHTML =
    `<ul>${brief.map(l => `<li>${esc(l)}</li>`).join("")}</ul>` +
    `<button id="copyBrief" type="button">Copy this brief for your AI</button>` +
    `<span id="copied" class="copied"></span>`;
  $("copyBrief").onclick = async () => {
    await copyOrShow(briefPrompt(brief, flagged, STATE.asOf), $("copyBrief"), "Copy this brief for your AI");
  };

  // Annotate once, before either view renders. Previously the expiry conflict
  // was attached inside bySupplier(), so it existed in the supplier view and
  // NOT in the default urgency view — same item, two views, one warning.
  const expKey = r => `${r[C.product]}|${r[C.brand]}|${r[C.location]}`;
  const expDays = new Map(soon.map(r => [expKey(r), r._daysLeft]));
  const flaggedAnnotated = flagged.map(r => {
    const d = expDays.get(expKey(r));
    return d === undefined ? r : { ...r, _expiresInDays: d };
  });

  const suppliers = bySupplier(flaggedAnnotated, soon);
  $("reorder").innerHTML = STATE.view === "supplier"
    ? renderSuppliers(suppliers, STATE.asOf)
    : renderReorder(flaggedAnnotated, STATE.grouped);

  $("reorder").querySelectorAll(".copyOrder").forEach(btn => {
    btn.onclick = () => copyOrShow(
      supplierOrderText(suppliers[+btn.dataset.i], STATE.asOf), btn,
      `Copy order for ${suppliers[+btn.dataset.i].supplier}`);
  });

  const vt = $("viewToggle");
  vt.value = STATE.view;
  vt.onchange = () => { STATE.view = vt.value; draw(); };
  $("groupToggle").parentElement.style.display = STATE.view === "supplier" ? "none" : "";
  $("expiry").innerHTML  = renderExpiry(soon);
  $("review").innerHTML  = renderReview(review);

  const clear = $("clear");
  if (clear) clear.onclick = () => { $("location").value = ALL_LOCATIONS; STATE.location = ALL_LOCATIONS; draw(); };

  // Export EVERY flagged item in scope, not just the 20 on screen. The cap
  // is about attention; the order is about action. Say which, so the button
  // never quietly ships a shorter list than it claims.
  const g = $("groupToggle");
  g.checked = STATE.grouped;
  g.onchange = () => { STATE.grouped = g.checked; draw(); };

  const btn = $("export");
  btn.disabled = flagged.length === 0;
  btn.textContent = flagged.length
    ? `Download reorder list (${flagged.length} item${flagged.length === 1 ? "" : "s"})`
    : "Nothing to reorder";
  btn.onclick = () => downloadCSV(flagged, loc);
}

function downloadCSV(rows, location) {
  const csv = toCSV(rows, ORDER_COLUMNS);
  const stamp = new Date().toISOString().slice(0, 10);
  const where = location === ALL_LOCATIONS ? "all-locations" : location.toLowerCase().replace(/\s+/g, "-");
  const name = `reorder_${where}_${stamp}.csv`;

  // BOM so Excel reads it as UTF-8 instead of mangling non-ASCII names.
  const blob = new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  document.body.appendChild(a); a.click(); a.remove();
  URL.revokeObjectURL(url);
  // "done", not "ok" — this confirms an action SHE took. Routing it to the
  // quiet channel made the download silent: click, and the app says nothing.
  note("done", `Downloaded ${rows.length} item${rows.length === 1 ? "" : "s"} to ${name}`);
}

function buildLocationFilter() {
  const sel = $("location");
  const rows = locationCounts(STATE.flagged, STATE.snapshot);
  sel.innerHTML =
    `<option value="${ALL_LOCATIONS}">All locations (${STATE.flagged.length} flagged)</option>` +
    rows.map(r => `<option value="${esc(r.location)}">${esc(r.location)} — ${r.flagged} flagged of ${r.tracked}</option>`).join("");
  sel.onchange = () => { STATE.location = sel.value; draw(); };
}

(async function () {
  try {
    const res = await fetch(SOURCE, { cache: "no-store" });
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
    const parsed = parseCSV(await res.text());

    const problems = audit(parsed, EXPECTED_MIN_ROWS);
    problems.length
      ? problems.forEach(p => note("bad", "PARSE: " + p))
      : note("ok", `parse clean — ${parsed.rows.length} rows × ${parsed.headers.length} columns`);

    const src = SOURCE_KINDS[DATA_SOURCE];
    document.getElementById("source").innerHTML =
      `<span class="badge badge-${DATA_SOURCE}">${src.label}</span>` +
      `<span class="src-note">${src.note}</span>`;

    const snapshot = toSnapshot(parsed.rows);
    note("info", `${parsed.rows.length} history rows → ${snapshot.length} items, each showing its most recent count`);

    const { flagged, unknown } = reorderList(snapshot);

    // This export ends in 2023, so a real "next 14 days" window is empty.
    // Run the real logic against the file's own timeline and SAY SO —
    // a demoed feature must never look like a live one.
    // "As of" = the last day the DATA describes, not a date reverse-engineered
    // to guarantee output. This is the morning Alicia would actually have seen.
    const recordDates = snapshot.map(r => new Date(r[C.date])).filter(d => !isNaN(d));
    const fileToday = new Date(Math.max(...recordDates));
    const stale = (Date.now() - fileToday.getTime()) / 86400000 > 30;
    const asOf = stale ? fileToday : new Date();
    const { soon, unparseable } = expiringSoon(snapshot, asOf, EXPIRY_WINDOW_DAYS);

    if (stale)
      note("warn", `DEMO: this export's last recorded day is ${fileToday.toISOString().slice(0,10)}. ` +
                   `The expiry panel shows what a coordinator would have seen that morning. ` +
                   `The reorder panel reads the same file — each item's latest recorded count, not live inventory.`);

    // Spread the existing STATE so view prefs (grouped) survive — a bare
    // object literal here silently dropped `grouped` and forced the flat view.
    STATE = { ...STATE, flagged, soon, review: [...unknown, ...unparseable], snapshot,
              location: ALL_LOCATIONS, conflicts: snapshot.conflicts ?? [],
              asOf: asOf.toISOString().slice(0, 10) };
    buildLocationFilter();
    draw();
  } catch (err) {
    note("bad", "FAILED TO LOAD: " + err.message);
    $("summary").textContent = "Could not load inventory.";
  }
})();
