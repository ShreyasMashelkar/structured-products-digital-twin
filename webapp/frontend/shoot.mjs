import { chromium } from "playwright-core";
import { mkdirSync } from "fs";

const OUT = process.env.HOME + "/projects/spdt/docs/img";
mkdirSync(OUT, { recursive: true });

const WORKSPACES = ["How to use", "Overview", "Originate", "Book & Risk", "Counterparty & XVA", "Validate", "Semi-Static Hedging", "Hedge & Execute", "Payoff Explorer", "Option Chain", "Broker", "Outcome Lab"];
const slug = (w) => w.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");

const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 1680, height: 1050 }, deviceScaleFactor: 2 });
page.setDefaultTimeout(60000);

await page.goto("http://localhost:8077/", { waitUntil: "domcontentloaded" });
// background-attachment:fixed doesn't extend past the viewport in fullPage shots
await page.addStyleTag({ content: "body{background:#090b10 !important;background-attachment:scroll !important}" });
// desk payload can take ~30s on a cold cache; masthead spot appears when loaded
await page.waitForSelector("text=NIFTY", { timeout: 120000 });
await page.waitForTimeout(4000);

for (const ws of WORKSPACES) {
  await page.click(`text="${ws}"`);
  await page.waitForTimeout(5000); // let panels fetch + charts animate in
  await page.screenshot({ path: `${OUT}/tab-${slug(ws)}.png`, fullPage: true });
  console.log("shot", ws);
}
await browser.close();
