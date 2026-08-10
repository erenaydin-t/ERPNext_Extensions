/**
 * v4.1.3 — PM Clearance List for restricted holder + named manager approver.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_list_permission");
const TRACE = path.join(__dirname, "traces", "pm_clearance_list_permission.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";

function bench(method, kwargs = null) {
  return benchExecute(method, kwargs);
}

async function loginAs(browser, email, password, evidence) {
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  const failed = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") evidence.console_errors.push(msg.text());
  });
  page.on("response", (res) => {
    if (res.status() >= 400) failed.push({ url: res.url(), status: res.status() });
  });
  evidence.failed_network = failed;
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  const emailSel = (await page.locator("#login_email").count())
    ? "#login_email"
    : 'input[type="email"], input[name="email"], #login_email';
  const passSel = (await page.locator("#login_password").count())
    ? "#login_password"
    : 'input[type="password"], #login_password';
  await page.locator(emailSel).first().fill(email, { timeout: 60000 });
  await page.locator(passSel).first().fill(password, { timeout: 60000 });
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
  return { context, page };
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openList(page) {
  await page.goto(`${BASE}/app/pm-clearance`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForTimeout(2500);
}

async function hasSqlError(page) {
  return page.evaluate(() =>
    /Unknown column|OperationalError|Traceback|Internal Server Error|1054/i.test(
      (document.body?.innerText || "").replace(/\s+/g, " ")
    )
  );
}

async function shows(page, name) {
  return page.evaluate(
    (n) => (document.body?.innerText || "").replace(/\s+/g, " ").includes(n),
    name
  );
}

async function openDoc(page, name) {
  await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (n) => window.cur_frm?.doc?.name === n && !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function run() {
  const prep = bench(
    "erpnext_extensions.petty_management.e2e.pm_clearance_list_permission_prep.prepare_pm_clearance_list_permission"
  );
  const evidence = { prep, screenshots: {}, console_errors: [], failed_network: [] };
  const browser = await chromium.launch({ headless: true });
  let context = null;
  let page = null;

  try {
    // Holder
    ({ context, page } = await loginAs(
      browser,
      prep.holder.email,
      prep.holder.password,
      evidence
    ));
    await context.tracing.start({ screenshots: true, snapshots: true });
    await openList(page);
    evidence.screenshots.holder_list = await shot(page, "01_holder_list");
    const holderErr = await hasSqlError(page);
    const holderOwn = await shows(page, prep.own_pm_clearance);
    const holderOther = await shows(page, prep.other_pm_clearance);
    const rv500 = (evidence.failed_network || []).some(
      (f) => /reportview/i.test(f.url) && f.status >= 500
    );
    await openDoc(page, prep.own_pm_clearance);
    evidence.screenshots.holder_form = await shot(page, "02_holder_form");
    await openList(page);
    evidence.screenshots.holder_list_again = await shot(page, "03_holder_list_again");
    await context.close();

    // Named manager approver (no elevated Petty role)
    ({ context, page } = await loginAs(
      browser,
      prep.manager.email,
      prep.manager.password,
      evidence
    ));
    await openList(page);
    evidence.screenshots.manager_list = await shot(page, "04_manager_list");
    const mgrErr = await hasSqlError(page);
    const mgrOwn = await shows(page, prep.own_pm_clearance);
    await openDoc(page, prep.own_pm_clearance);
    evidence.screenshots.manager_form = await shot(page, "05_manager_form");
    await context.close();

    // No-employee fail-closed: list loads empty / no 500
    ({ context, page } = await loginAs(
      browser,
      prep.no_emp.email,
      prep.no_emp.password,
      evidence
    ));
    await openList(page);
    evidence.screenshots.noemp_list = await shot(page, "06_noemp_list");
    const noEmpErr = await hasSqlError(page);
    const noEmpOwn = await shows(page, prep.own_pm_clearance);
    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    evidence.trace = TRACE;
    await context.close();

    evidence.checks = {
      holderErr,
      holderOwn,
      holderOther,
      rv500,
      mgrErr,
      mgrOwn,
      noEmpErr,
      noEmpOwn,
    };
    const ok =
      holderErr === false &&
      rv500 === false &&
      holderOwn === true &&
      holderOther === false &&
      mgrErr === false &&
      mgrOwn === true &&
      noEmpErr === false &&
      noEmpOwn === false;

    console.log(JSON.stringify({ ok, evidence }, null, 2));
    await browser.close();
    process.exit(ok ? 0 : 1);
  } catch (err) {
    evidence.error = String(err);
    try {
      if (page) evidence.screenshots.failure = await shot(page, "99_failure");
      if (context) {
        fs.mkdirSync(path.dirname(TRACE), { recursive: true });
        await context.tracing.stop({ path: TRACE }).catch(() => null);
        await context.close().catch(() => null);
      }
    } catch (_e) {
      /* ignore */
    }
    console.log(JSON.stringify({ ok: false, evidence }, null, 2));
    await browser.close();
    process.exit(1);
  }
}

run();
