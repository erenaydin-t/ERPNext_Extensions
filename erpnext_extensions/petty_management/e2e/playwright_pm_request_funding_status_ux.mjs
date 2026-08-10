/**
 * v4.1.3 — PM Request funding/business status UX (dashboard headline + intro).
 * Covers unpaid / partial / fully funded / closed without touching workflow badge.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_funding_status_ux");
const TRACE = path.join(__dirname, "traces", "pm_request_funding_status_ux.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";

function bench(method, kwargs = null) {
  return benchExecute(method, kwargs);
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  const emailSel = (await page.locator("#login_email").count())
    ? "#login_email"
    : 'input[type="email"], input[name="email"]';
  const passSel = (await page.locator("#login_password").count())
    ? "#login_password"
    : 'input[type="password"]';
  await page.locator(emailSel).first().fill(email, { timeout: 60000 });
  await page.locator(passSel).first().fill(password, { timeout: 60000 });
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function openPmRequest(page, name) {
  await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (expected) =>
      window.cur_frm?.doc?.doctype === "PM Request" &&
      window.cur_frm?.doc?.name === expected &&
      !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
  await page.evaluate(async () => {
    if (window.cur_frm?.trigger) {
      await window.cur_frm.trigger("setup_pm_request_toolbar");
    }
  });
  await page.waitForTimeout(1500);
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function pageText(page) {
  return page.evaluate(() => (document.body?.innerText || "").replace(/\s+/g, " "));
}

async function hasCreatePe(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
      /Create Payment Entry/i.test((el.textContent || "").trim())
    )
  );
}

async function checkCase(page, label, name, { expectText, expectCreate }) {
  await openPmRequest(page, name);
  const text = await pageText(page);
  const create = await hasCreatePe(page);
  const okText = expectText.every((t) => text.includes(t));
  const okCreate = expectCreate ? create === true : create === false;
  return {
    label,
    ok: okText && okCreate,
    okText,
    okCreate,
    create,
    missing: expectText.filter((t) => !text.includes(t)),
    screenshot: await shot(page, label),
  };
}

async function run() {
  const evidence = { screenshots: {}, cases: [] };
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();

  try {
    const prep = bench(
      "erpnext_extensions.petty_management.e2e.pm_request_funding_status_ux_prep.prepare_pm_request_funding_status_ux"
    );
    evidence.prep = prep;
    await login(page, prep.user.email, prep.user.password);

    const unpaid = await checkCase(page, "01_unpaid", prep.unpaid.name, {
      expectText: ["Waiting for Payment"],
      expectCreate: true,
    });
    const partial = await checkCase(page, "02_partial", prep.partial.name, {
      expectText: ["Partially Paid"],
      expectCreate: true,
    });
    const funded = await checkCase(page, "03_funded", prep.funded.name, {
      expectText: ["Fully Funded"],
      expectCreate: false,
    });
    // reload funded to ensure no stale indicator
    await page.reload({ waitUntil: "domcontentloaded" });
    await openPmRequest(page, prep.funded.name);
    const fundedReloadText = await pageText(page);
    const fundedReload = {
      ok: /Fully Funded/i.test(fundedReloadText) && !(await hasCreatePe(page)),
      screenshot: await shot(page, "03b_funded_reload"),
    };

    const closed = await checkCase(page, "04_closed", prep.closed.name, {
      expectText: ["Closed"],
      expectCreate: false,
    });
    // Closed must not present Fully Funded as primary competing state in headline area
    const closedText = await pageText(page);
    const closedNotPaidPrimary =
      /Closed/i.test(closedText) &&
      !/Paid \/ Fully Funded/i.test(closedText);

    evidence.cases = { unpaid, partial, funded, fundedReload, closed, closedNotPaidPrimary };
    const ok =
      unpaid.ok &&
      partial.ok &&
      funded.ok &&
      fundedReload.ok &&
      closed.ok &&
      closedNotPaidPrimary;

    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    evidence.trace = TRACE;
    console.log(JSON.stringify({ ok, evidence }, null, 2));
    await browser.close();
    process.exit(ok ? 0 : 1);
  } catch (err) {
    evidence.error = String(err);
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    console.log(JSON.stringify({ ok: false, evidence }, null, 2));
    await browser.close();
    process.exit(1);
  }
}

run();
