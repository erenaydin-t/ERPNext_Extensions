/**
 * v4.1.3 — Configurable Operational PM Visibility Role (PM Settings).
 * 1) Set role = Petty Management Manager → Manager sees all requests.
 * 2) Restore role = Petty Management Accountant → Manager scoped; Accountant unrestricted.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_visibility_role_setting");
const TRACE = path.join(__dirname, "traces", "pm_visibility_role_setting.zip");
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
  page.on("console", (msg) => {
    if (msg.type() === "error") evidence.console_errors.push(msg.text());
  });
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
  await page.goto(`${BASE}/app/pm-request`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_list?.doctype === "PM Request" ||
      document.querySelector(".frappe-list, .list-row, .list-paging-area"),
    { timeout: 180000 }
  );
  await page.waitForTimeout(2000);
}

async function listShows(page, name) {
  return page.evaluate((n) => {
    const text = (document.body?.innerText || "").replace(/\s+/g, " ");
    return text.includes(n);
  }, name);
}

async function checkUser(browser, user, prep, evidence, label, { requireOther }) {
  const { context, page } = await loginAs(
    browser,
    user.email,
    user.password,
    evidence
  );
  try {
    await openList(page);
    evidence.screenshots[`${label}_list`] = await shot(page, `${label}_list`);
    const own = await listShows(page, prep.own_pm_request);
    const other = await listShows(page, prep.other_pm_request);
    evidence[`${label}_own`] = own;
    evidence[`${label}_other`] = other;
    await context.close();
    const otherOk = requireOther ? other === true : other === false;
    return own === true && otherOk;
  } catch (err) {
    evidence[`${label}_error`] = String(err);
    await context.close().catch(() => null);
    return false;
  }
}

async function run() {
  const evidence = { screenshots: {}, console_errors: [] };
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  await context.tracing.start({ screenshots: true, snapshots: true });

  try {
    const prep = bench(
      "erpnext_extensions.petty_management.e2e.pm_visibility_role_setting_prep.prepare_pm_visibility_role_setting"
    );
    evidence.prep = prep;

    // Phase A: Manager is unrestricted
    const setMgr = bench(
      "erpnext_extensions.petty_management.e2e.pm_visibility_role_setting_prep.set_operational_pm_visibility_role",
      { role: "Petty Management Manager" }
    );
    evidence.set_manager_role = setMgr;

    const managerUnrestricted = await checkUser(
      browser,
      prep.manager,
      prep,
      evidence,
      "manager_as_ops",
      { requireOther: true }
    );

    // Phase B: restore Accountant
    const setAcct = bench(
      "erpnext_extensions.petty_management.e2e.pm_visibility_role_setting_prep.set_operational_pm_visibility_role",
      { role: "Petty Management Accountant" }
    );
    evidence.set_accountant_role = setAcct;

    const managerScoped = await checkUser(
      browser,
      prep.manager,
      prep,
      evidence,
      "manager_restored",
      { requireOther: false }
    );
    const accountantOk = await checkUser(
      browser,
      prep.accountant,
      prep,
      evidence,
      "accountant_restored",
      { requireOther: true }
    );

    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    evidence.trace = TRACE;

    const ok = managerUnrestricted && managerScoped && accountantOk;
    console.log(
      JSON.stringify(
        {
          ok,
          managerUnrestricted,
          managerScoped,
          accountantOk,
          evidence,
        },
        null,
        2
      )
    );
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
