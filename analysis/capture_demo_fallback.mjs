// capture-fallback.mjs — regenerate the demo-fallback screenshots for the
// DataHub operator page. Run any time before a presentation:
//   node capture-fallback.mjs
// Captures the LIVE page (GitHub Pages + live Socrata), so each image is a
// dated, truthful record of what the demo actually renders.
import puppeteer from "puppeteer-core";
import { mkdirSync } from "node:fs";

const OUT = "/Users/Rensley/Desktop/freshroute-demo/data-app/assets/demo-fallback";
const URL = "https://doble196.github.io/freshroute-demo/data-app/operator.html";
const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

mkdirSync(OUT, { recursive: true });

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--hide-scrollbars"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1440, height: 1000, deviceScaleFactor: 2 });

async function search(term) {
  await page.evaluate((t) => {
    document.querySelector("#q").value = t;
    document.querySelector("#form").requestSubmit();
  }, term);
}

async function settle() {
  // The page is vanilla JS with a busy status; give the fetch room, then
  // wait until neither the busy text nor an empty results area remains.
  await page.waitForFunction(
    () => {
      const out = document.querySelector("#out");
      return out && out.textContent.trim().length > 0 &&
        !out.textContent.includes("Asking the city");
    },
    { timeout: 20000 },
  );
  await new Promise((r) => setTimeout(r, 600)); // fonts/layout settle
}

async function openRecord(street) {
  await page.evaluate((s) => {
    const b = [...document.querySelectorAll("button[data-camis]")].find((x) =>
      x.textContent.includes(s),
    );
    if (!b) throw new Error(`no picker row containing "${s}"`);
    b.click();
  }, street);
  await page.waitForFunction(
    () => /days since that inspection|PATTERN ON YOUR RECORD|no dated inspections/i.test(
      document.body.textContent,
    ),
    { timeout: 20000 },
  );
  await new Promise((r) => setTimeout(r, 600));
}

// 1. The happy-path picker: "moge tee" -> 5 locations.
await page.goto(URL, { waitUntil: "networkidle2" });
await search("moge tee");
await settle();
await page.screenshot({ path: `${OUT}/01-picker-moge-tee.png`, fullPage: true });
console.log("captured 01-picker-moge-tee.png");

// 2. The money shot: the 42-35 Main Street record (banner + fix-first list).
await openRecord("42-35 Main Street");
await page.screenshot({ path: `${OUT}/02-record-moge-tee-main-st.png`, fullPage: true });
console.log("captured 02-record-moge-tee-main-st.png");

// 3. The backup subject: Kingston Pizza (2 rows -> pick 04L-on-latest record).
await page.goto(URL, { waitUntil: "networkidle2" });
await search("kingston pizza");
await settle();
const rows = await page.$$eval("button[data-camis]", (bs) =>
  bs.map((b) => b.textContent.replace(/\s+/g, " ").trim()),
);
console.log("kingston picker rows:", JSON.stringify(rows));
if (rows.length) {
  await page.screenshot({ path: `${OUT}/03-picker-kingston-pizza.png`, fullPage: true });
  console.log("captured 03-picker-kingston-pizza.png");
  // CAMIS 41555612 is the demo-grade record (04L on the latest visit).
  await page.evaluate(() => {
    const b = document.querySelector('button[data-camis="41555612"]');
    if (!b) throw new Error("CAMIS 41555612 not in the picker");
    b.click();
  });
  await page.waitForFunction(
    () => /days since that inspection|PATTERN ON YOUR RECORD/i.test(document.body.textContent),
    { timeout: 20000 },
  );
  await new Promise((r) => setTimeout(r, 600));
  await page.screenshot({ path: `${OUT}/04-record-kingston-pizza.png`, fullPage: true });
  console.log("captured 04-record-kingston-pizza.png");
}

await browser.close();
console.log(`done -> ${OUT}`);
