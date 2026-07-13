/**
 * Facility dimension Link field E2E (Playwright).
 *
 *   bench migrate && bench build --app erpnext_extensions && bench --site development.localhost clear-cache
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/facility_management/e2e/playwright_facility_dimension_links.mjs
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN_DIR = path.join(__dirname, "screenshots");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const USER = process.env.FRAPPE_E2E_USER || "Administrator";
const PASS = process.env.FRAPPE_E2E_PASSWORD || "admin";
const BENCH =
  process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

const results = [];

function log(test, ok, detail = {}) {
  results.push({ test, ok, detail });
  console.log(JSON.stringify({ test, ok, detail }));
}

async function login(page) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill("#login_email", USER);
  await page.fill("#login_password", PASS);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitFormReady(page) {
  await page.waitForFunction(
    () => window.cur_frm && !window.cur_frm.is_loading,
    { timeout: 180000 }
  );
  await page.waitForTimeout(800);
}

const FIELD_DOCTYPE = {
  default_department: "Department",
  default_bank_dimension: "Bank",
  default_bank_account_dimension: "Bank Account",
  department: "Department",
  bank_dimension: "Bank",
  bank_account_dimension: "Bank Account",
};

async function dismissLinkDropdown(page) {
  await page.keyboard.press("Escape");
  await page.waitForTimeout(250);
}

async function linkDropdownHasResults(page, fieldname) {
  const doctype = FIELD_DOCTYPE[fieldname];
  const samples = await page.evaluate(async (dt) => {
    const r = await frappe.call({
      method: "frappe.desk.search.search_link",
      args: { doctype: dt, txt: "", page_length: 10 },
    });
    return r.message || [];
  }, doctype);
  if (!samples.length) {
    return { items: 0, visible: false, fieldname, api_count: 0 };
  }
  const probe = String(samples[0].value || samples[0].description || "a").slice(
    0,
    3
  );
  const control = page
    .locator(`.frappe-control[data-fieldname="${fieldname}"]`)
    .first();
  await control.scrollIntoViewIfNeeded();
  const input = control.locator('input[data-fieldtype="Link"]').first();
  await input.click({ force: true });
  await input.fill("");
  await input.pressSequentially(probe, { delay: 80 });
  await page.waitForTimeout(1500);
  const items = await page
    .locator(`.frappe-control[data-fieldname="${fieldname}"] [role="option"]`)
    .count();
  const visible = await page
    .locator(`.frappe-control[data-fieldname="${fieldname}"] [role="listbox"]`)
    .isVisible()
    .catch(() => false);
  await dismissLinkDropdown(page);
  return { items, visible, fieldname, api_count: samples.length, probe };
}

async function pickFirstLinkOption(page, fieldname) {
  const doctype = FIELD_DOCTYPE[fieldname];
  const sample = await page.evaluate(async (dt) => {
    const r = await frappe.call({
      method: "frappe.desk.search.search_link",
      args: { doctype: dt, txt: "", page_length: 1 },
    });
    return (r.message || [])[0]?.value || null;
  }, doctype);
  if (!sample) {
    throw new Error(`No ${doctype} link search results`);
  }
  const control = page
    .locator(`.frappe-control[data-fieldname="${fieldname}"]`)
    .first();
  const input = control.locator('input[data-fieldtype="Link"]').first();
  await input.click({ force: true });
  await input.fill("");
  await input.pressSequentially(String(sample).slice(0, 4), { delay: 80 });
  await page.waitForTimeout(1200);
  await page.waitForSelector(
    `.frappe-control[data-fieldname="${fieldname}"] [role="option"]`,
    { timeout: 20000 }
  );
  const firstText = await page
    .locator(`.frappe-control[data-fieldname="${fieldname}"] [role="option"]`)
    .first()
    .innerText();
  await page
    .locator(`.frappe-control[data-fieldname="${fieldname}"] [role="option"]`)
    .first()
    .click();
  await page.waitForTimeout(400);
  const val = await input.inputValue();
  await dismissLinkDropdown(page);
  return { picked: firstText.trim(), value: val, sample };
}

async function screenshot(page, name) {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const file = path.join(SCREEN_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

async function run() {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1500, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);
  const consoleErrors = [];
  page.on("pageerror", (e) => consoleErrors.push(e.message));

  try {
    await login(page);

    const prep = benchExecute(
      "erpnext_extensions.facility_management.e2e.facility_dimension_link_prep.prepare"
    );
    log("prep_data", !!prep.company, prep);

    await page.goto(
      `${BASE}/desk/facility-settings/${encodeURIComponent(
        prep.facility_settings_name
      )}`,
      {
        waitUntil: "domcontentloaded",
      }
    );
    await waitFormReady(page);
    await screenshot(page, "01_facility_settings_before");

    const fsFields = [
      "default_department",
      "default_bank_dimension",
      "default_bank_account_dimension",
    ];
    const fsDropdowns = {};
    for (const fn of fsFields) {
      fsDropdowns[fn] = await linkDropdownHasResults(page, fn);
    }
    log(
      "facility_settings_dropdowns",
      fsFields.every(
        (fn) => fsDropdowns[fn].items > 0 && fsDropdowns[fn].api_count > 0
      ),
      {
        fsDropdowns,
        screenshot: await screenshot(page, "02_facility_settings_dropdowns"),
      }
    );

    const fsPicked = {};
    for (const fn of fsFields) {
      fsPicked[fn] = await pickFirstLinkOption(page, fn);
    }
    await page
      .locator('.btn-primary[data-label="Save"], button[data-label="Save"]')
      .first()
      .click();
    await page.waitForTimeout(2500);
    log("facility_settings_saved", true, {
      fsPicked,
      screenshot: await screenshot(page, "03_facility_settings_saved"),
    });

    await page.goto(`${BASE}/desk/facility/new-facility-1`, {
      waitUntil: "domcontentloaded",
    });
    await waitFormReady(page);
    await page.evaluate(async (company) => {
      await cur_frm.set_value("company", company);
    }, prep.company);
    await page.waitForTimeout(600);

    const facFields = [
      "department",
      "bank_dimension",
      "bank_account_dimension",
    ];
    const facDropdowns = {};
    for (const fn of facFields) {
      facDropdowns[fn] = await linkDropdownHasResults(page, fn);
    }
    log(
      "facility_new_dropdowns",
      facFields.every(
        (fn) => facDropdowns[fn].items > 0 && facDropdowns[fn].api_count > 0
      ),
      {
        facDropdowns,
        screenshot: await screenshot(page, "04_facility_new_dropdowns"),
      }
    );

    const facPicked = {};
    for (const fn of facFields) {
      facPicked[fn] = await pickFirstLinkOption(page, fn);
    }

    await page.evaluate(async (prepData) => {
      const f = cur_frm;
      await f.set_value("facility_name", prepData.facility_name);
      await f.set_value("bank", prepData.bank);
      await f.set_value("contract_date", prepData.today);
      await f.set_value("principal_amount", 1000);
      await f.set_value("profit_amount", 100);
      await f.set_value("is_opening_facility", 1);
      await f.set_value("opening_paid_principal_amount", 0);
      await f.set_value("opening_paid_profit_amount", 0);
    }, prep);

    await page
      .locator('.btn-primary[data-label="Save"], button[data-label="Save"]')
      .first()
      .click();
    await page.waitForTimeout(3500);
    const savedName = await page.evaluate(() => cur_frm.doc.name);
    log(
      "facility_created_with_dimensions",
      !!savedName && !String(savedName).startsWith("new-"),
      {
        savedName,
        facPicked,
        screenshot: await screenshot(page, "05_facility_saved"),
      }
    );

    if (consoleErrors.length) {
      log("console_page_errors", false, { consoleErrors });
    } else {
      log("console_page_errors", true, {});
    }
  } finally {
    await browser.close();
  }

  const main = results.filter((r) => r.test !== "console_page_errors");
  const all_ok = main.every((r) => r.ok);
  console.log(JSON.stringify({ all_ok, results }, null, 2));
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
