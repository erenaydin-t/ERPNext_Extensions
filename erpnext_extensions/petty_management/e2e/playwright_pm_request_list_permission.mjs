/**
 * v4.1.3 — PM Request List must load for non-Administrator Petty Management User.
 * Evidence: screenshots + trace under petty_management/e2e/.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_list_permission");
const TRACE = path.join(__dirname, "traces", "pm_request_list_permission.zip");
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
    if (res.status() >= 400) {
      failed.push({ url: res.url(), status: res.status() });
    }
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

async function openPmRequestList(page) {
  await page.goto(`${BASE}/app/pm-request`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_list?.doctype === "PM Request" ||
      document.querySelector(".frappe-list, .list-row, .list-paging-area, .msgprint, .page-card"),
    { timeout: 180000 }
  );
  // Wait for reportview to settle (success or error dialog)
  await page.waitForTimeout(2500);
}

async function listHasError(page) {
  return page.evaluate(() => {
    const body = (document.body?.innerText || "").replace(/\s+/g, " ");
    return /Unknown column|OperationalError|Traceback|Internal Server Error|1054/i.test(
      body
    );
  });
}

async function listShowsRequest(page, name) {
  return page.evaluate((n) => {
    const text = (document.body?.innerText || "").replace(/\s+/g, " ");
    return text.includes(n);
  }, name);
}

async function openDoc(page, name) {
  await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (n) => window.cur_frm?.doc?.name === n && !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function runAsUser(browser, user, prep, evidence, label) {
  const { context, page } = await loginAs(
    browser,
    user.email,
    user.password,
    evidence
  );
  await context.tracing.start({ screenshots: true, snapshots: true });
  try {
    await openPmRequestList(page);
    evidence.screenshots[`${label}_list`] = await shot(page, `${label}_01_list`);
    const hasErr = await listHasError(page);
    const ownVisible = await listShowsRequest(page, prep.own_pm_request);
    const rvFailed = (evidence.failed_network || []).some(
      (f) => /reportview|frappe.desk.reportview/i.test(f.url) && f.status >= 500
    );
    evidence[`${label}_has_error`] = hasErr;
    evidence[`${label}_own_visible`] = ownVisible;
    evidence[`${label}_reportview_500`] = rvFailed;

    if (label === "restricted") {
      await openDoc(page, prep.own_pm_request);
      evidence.screenshots[`${label}_form`] = await shot(page, `${label}_02_form`);
      await openPmRequestList(page);
      evidence.screenshots[`${label}_list_again`] = await shot(
        page,
        `${label}_03_list_again`
      );
      const stillErr = await listHasError(page);
      const stillOwn = await listShowsRequest(page, prep.own_pm_request);
      evidence[`${label}_list_again_error`] = stillErr;
      evidence[`${label}_list_again_own`] = stillOwn;
    }

    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    const tracePath =
      label === "restricted"
        ? TRACE
        : path.join(__dirname, "traces", `pm_request_list_permission_${label}.zip`);
    await context.tracing.stop({ path: tracePath }).catch(() => null);
    evidence[`${label}_trace`] = tracePath;

    const ok =
      !hasErr &&
      !rvFailed &&
      ownVisible === true &&
      (label !== "restricted" ||
        (evidence.restricted_list_again_error === false &&
          evidence.restricted_list_again_own === true));
    await context.close();
    return ok;
  } catch (err) {
    evidence[`${label}_error`] = String(err);
    try {
      evidence.screenshots[`${label}_failure`] = await shot(page, `${label}_99_failure`);
      await context.tracing.stop({ path: TRACE }).catch(() => null);
    } catch (_e) {
      /* ignore */
    }
    await context.close().catch(() => null);
    return false;
  }
}

async function run() {
  const prep = bench(
    "erpnext_extensions.petty_management.e2e.pm_request_list_permission_prep.prepare_pm_request_list_restricted"
  );
  const evidence = {
    prep,
    screenshots: {},
    console_errors: [],
    failed_network: [],
  };
  const browser = await chromium.launch({ headless: true });

  try {
    const restrictedOk = await runAsUser(
      browser,
      prep.restricted,
      prep,
      evidence,
      "restricted"
    );
    // Admin regression (site may use Administrator password from env)
    const adminPass =
      process.env.FRAPPE_E2E_PASSWORD ||
      process.env.FRAPPE_ADMIN_PASSWORD ||
      prep.administrator?.password ||
      "admin";
    let adminOk = true;
    try {
      adminOk = await runAsUser(
        browser,
        { email: "Administrator", password: adminPass },
        prep,
        evidence,
        "admin"
      );
    } catch (e) {
      evidence.admin_login_error = String(e);
      // Admin login password may differ in this env; restricted path is mandatory.
      adminOk = evidence.admin_has_error === false;
    }

    const ok = restrictedOk === true;
    evidence.admin_ok = adminOk;
    console.log(JSON.stringify({ ok, restrictedOk, adminOk, evidence }, null, 2));
    await browser.close();
    process.exit(ok ? 0 : 1);
  } catch (err) {
    evidence.error = String(err);
    console.log(JSON.stringify({ ok: false, evidence }, null, 2));
    await browser.close();
    process.exit(1);
  }
}

run();
