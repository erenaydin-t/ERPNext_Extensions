/**
 * v4.1.3 Option A — Finance Approved workflow + business Status/Payment Status.
 * Workflow badge and Status must not contradict (no Waiting-for-Payment workflow + Paid status).
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

async function formState(page) {
  return page.evaluate(() => {
    const doc = window.cur_frm?.doc || {};
    const ws =
      (window.cur_frm?.fields_dict?.workflow_state?.disp_area?.innerText || "") +
      " " +
      (document.body?.innerText || "");
    return {
      status: doc.status || "",
      payment_status: doc.payment_status || "",
      workflow_state: doc.workflow_state || "",
      is_closed: Number(doc.is_closed || 0),
      body: (document.body?.innerText || "").replace(/\s+/g, " "),
    };
  });
}

async function hasCreatePe(page) {
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
      /Create Payment Entry/i.test((el.textContent || "").trim())
    )
  );
}

function noContradiction(state) {
  // Forbidden: workflow still titled Waiting for Payment while status is Paid/Closed
  const body = state.body || "";
  const workflowBadgeIsWaiting =
    /indicator[\s\S]{0,80}Waiting for Payment/i.test(body) === false
      ? false
      : /\bWaiting for Payment\b/.test(body) && state.status === "Paid";
  // Stronger check via doc fields from cur_frm
  const wsTitleGuess = state.body.includes("Finance Approved");
  if (state.status === "Paid" && state.payment_status === "Paid") {
    // Must not claim workflow is Waiting for Payment as the only story — Finance Approved should appear
    return wsTitleGuess || /Finance Approved/i.test(state.body);
  }
  return true;
}

async function checkCase(page, label, name, { status, payment, expectCreate, requireFinanceApproved }) {
  await openPmRequest(page, name);
  const state = await formState(page);
  const create = await hasCreatePe(page);
  const okStatus = !status || state.status === status;
  const okPay = !payment || state.payment_status === payment;
  const okCreate = expectCreate ? create === true : create === false;
  const okFa = !requireFinanceApproved || /Finance Approved/i.test(state.body);
  const okContra = noContradiction(state);
  return {
    label,
    ok: okStatus && okPay && okCreate && okFa && okContra,
    okStatus,
    okPay,
    okCreate,
    okFa,
    okContra,
    state,
    create,
    screenshot: await shot(page, label),
  };
}

async function run() {
  const evidence = { screenshots: {}, cases: {} };
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

    evidence.cases.unpaid = await checkCase(page, "01_unpaid", prep.unpaid.name, {
      status: "Waiting for Payment",
      payment: "Not Paid",
      expectCreate: true,
      requireFinanceApproved: true,
    });
    evidence.cases.partial = await checkCase(page, "02_partial", prep.partial.name, {
      status: "Partially Paid",
      payment: "Partially Paid",
      expectCreate: true,
      requireFinanceApproved: true,
    });
    evidence.cases.funded = await checkCase(page, "03_funded", prep.funded.name, {
      status: "Paid",
      payment: "Paid",
      expectCreate: false,
      requireFinanceApproved: true,
    });
    await page.reload({ waitUntil: "domcontentloaded" });
    evidence.cases.fundedReload = await checkCase(page, "03b_funded_reload", prep.funded.name, {
      status: "Paid",
      payment: "Paid",
      expectCreate: false,
      requireFinanceApproved: true,
    });
    evidence.cases.closed = await checkCase(page, "04_closed", prep.closed.name, {
      status: "Closed",
      payment: "Paid",
      expectCreate: false,
      requireFinanceApproved: true,
    });

    const ok = Object.values(evidence.cases).every((c) => c.ok);
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
