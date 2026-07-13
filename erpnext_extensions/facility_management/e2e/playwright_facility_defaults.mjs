/**
 * Facility Settings → new Facility defaults E2E (Desk route, no test fallbacks).
 *
 *   bench --site development.localhost clear-cache
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/facility_management/e2e/playwright_facility_defaults.mjs
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute as sharedBenchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN_DIR = path.join(__dirname, "screenshots", "defaults");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const ROUTE = "/desk/facility/new-facility-1";
const E2E_USER = process.env.FRAPPE_E2E_USER || "Administrator";

const ACCOUNT_FIELDS = [
  "bank_account",
  "loan_payable_account",
  "deferred_loan_interest_account",
  "interest_expense_account",
  "penalty_expense_account",
];
const DIMENSION_FIELDS = [
  "cost_center",
  "department",
  "bank_dimension",
  "bank_account_dimension",
];
const ALL_DEFAULT_FIELDS = [...ACCOUNT_FIELDS, ...DIMENSION_FIELDS];

const results = [];
const report = {
  route: `${BASE}${ROUTE}`,
  user: E2E_USER,
  investigation: {},
  savedFacilityName: null,
  apiFacilityName: null,
};

function log(test, ok, detail = {}) {
  results.push({ test, ok, detail });
  console.log(JSON.stringify({ test, ok, detail }));
}

function benchExecute(method, args = "") {
  return sharedBenchExecute(method);
}

async function login(page) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill("#login_email", E2E_USER);
  await page.fill(
    "#login_password",
    process.env.FRAPPE_E2E_PASSWORD || "admin"
  );
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitForm(page) {
  await page.waitForFunction(
    () => window.cur_frm && !window.cur_frm.is_loading,
    { timeout: 180000 }
  );
  await page.waitForTimeout(800);
}

async function screenshot(page, name) {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const p = path.join(SCREEN_DIR, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openNewFacility(page) {
  await page.goto(`${BASE}${ROUTE}`, { waitUntil: "domcontentloaded" });
  await waitForm(page);
}

async function waitDefaultsApplied(page) {
  await page.waitForFunction(
    () => {
      const d = window.cur_frm?.doc;
      return d?.bank_account && d?.loan_payable_account && d?.cost_center;
    },
    { timeout: 60000 }
  );
  await page.waitForTimeout(1500);
}

async function docSnapshot(page) {
  return page.evaluate((fields) => {
    const doc = {};
    for (const fn of fields) {
      doc[fn] = cur_frm.doc[fn] || "";
    }
    doc.company = cur_frm.doc.company || "";
    return doc;
  }, ALL_DEFAULT_FIELDS);
}

async function investigationDump(page) {
  return page.evaluate(() => {
    const handlers = frappe.ui.form.handlers.Facility || {};
    const jsBundle = frappe.meta?.get_docfield?.("Facility", "company")
      ? null
      : null;
    const formJs = window.cur_frm?.script_manager?.scripts?.length;
    return {
      has_defaults_js:
        typeof erpnext_extensions?.facility_management?.defaults
          ?.apply_from_company === "function",
      handlers: Object.keys(handlers),
      meta_js_has_defaults: String(
        frappe.get_meta("Facility").__js || ""
      ).includes("facility_settings_defaults"),
      meta_js_has_dimension: String(
        frappe.get_meta("Facility").__js || ""
      ).includes("facility_dimension_link_queries"),
      form_script_count: formJs,
    };
  });
}

async function run() {
  const prep = benchExecute(
    "erpnext_extensions.facility_management.e2e.facility_dimension_link_prep.prepare"
  );

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1500, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  const apiResponses = [];
  page.on("response", async (response) => {
    const url = response.url();
    if (
      url.includes("get_facility_settings_defaults") ||
      url.includes("method")
    ) {
      try {
        const postData = response.request().postData() || "";
        if (postData.includes("get_facility_settings_defaults")) {
          const body = await response.json().catch(() => null);
          apiResponses.push({ url, status: response.status(), body });
        }
      } catch {
        /* ignore */
      }
    }
  });

  try {
    await login(page);
    await openNewFacility(page);

    const invBefore = await investigationDump(page);
    report.investigation.beforeCompany = invBefore;
    log(
      "js_loaded_and_handlers_registered",
      invBefore.has_defaults_js && invBefore.handlers.includes("company"),
      {
        invBefore,
      }
    );

    if (!invBefore.has_defaults_js) {
      throw new Error(
        "facility_settings_defaults.js not loaded — aborting (no fallback)"
      );
    }

    const apiBefore = await page.evaluate(async (company) => {
      const r = await frappe.call({
        method:
          "erpnext_extensions.facility_management.doctype.facility.facility.get_facility_settings_defaults",
        args: { company },
      });
      return r.message;
    }, prep.company);
    report.investigation.apiPayload = apiBefore;

    await page.evaluate(async (company) => {
      if (cur_frm.doc.company && cur_frm.doc.company !== company) {
        await cur_frm.set_value("company", "");
      }
      await cur_frm.set_value("company", company);
    }, prep.company);

    await waitDefaultsApplied(page);

    const afterCompany = await docSnapshot(page);
    report.investigation.docAfterCompany = afterCompany;
    const shotA = await screenshot(page, "02_after_company_defaults");

    const accountsOk = ACCOUNT_FIELDS.every(
      (fn) =>
        !!afterCompany[fn] && afterCompany[fn] === apiBefore.defaults?.[fn]
    );
    const dimsOk = DIMENSION_FIELDS.every((fn) => {
      const exp = apiBefore.defaults?.[fn];
      return !exp || afterCompany[fn] === exp;
    });
    log(
      "A_new_facility_defaults_from_desk",
      apiBefore.found && accountsOk && dimsOk,
      {
        afterCompany,
        expected: apiBefore.defaults,
        screenshot: shotA,
      }
    );

    const overrideVal = await page.evaluate(async () => {
      const r = await frappe.call({
        method: "frappe.desk.search.search_link",
        args: {
          doctype: "Account",
          txt: "",
          page_length: 15,
          filters: {
            company: cur_frm.doc.company,
            account_type: "Bank",
            is_group: 0,
          },
        },
      });
      const alt = (r.message || [])
        .map((x) => x.value)
        .find((v) => v && v !== cur_frm.doc.bank_account);
      if (alt) {
        await cur_frm.set_value("bank_account", alt);
      }
      return cur_frm.doc.bank_account;
    });
    await page.waitForTimeout(800);

    await page.evaluate(async () => {
      const co = cur_frm.doc.company;
      await cur_frm.set_value("company", "");
      await cur_frm.set_value("company", co);
    });
    await page.waitForTimeout(4000);

    const bankAfterReapply = (await docSnapshot(page)).bank_account;
    log("B_manual_bank_account_preserved", bankAfterReapply === overrideVal, {
      overrideVal,
      bankAfterReapply,
      screenshot: await screenshot(page, "03_after_reapply_defaults"),
    });

    const saveResult = await page.evaluate(async (prepData) => {
      try {
        await cur_frm.set_value("facility_name", prepData.facility_name);
        await cur_frm.set_value("bank", prepData.bank);
        await cur_frm.set_value("contract_date", prepData.today);
        await cur_frm.set_value("principal_amount", 1000);
        await cur_frm.set_value("profit_amount", 100);
        await cur_frm.set_value("is_opening_facility", 1);
        await cur_frm.save();
        return { ok: true, name: cur_frm.doc.name };
      } catch (e) {
        return { ok: false, error: String(e), name: cur_frm.doc.name };
      }
    }, prep);

    if (saveResult.ok) {
      report.savedFacilityName = saveResult.name;
      await page.goto(
        `${BASE}/desk/facility/${encodeURIComponent(saveResult.name)}`,
        {
          waitUntil: "domcontentloaded",
        }
      );
      await waitForm(page);
      const saved = await docSnapshot(page);
      const reopenedName = await page.evaluate(() => cur_frm.doc.name);
      log(
        "C_save_and_reopen_persisted",
        !!reopenedName &&
          reopenedName === saveResult.name &&
          saved.bank_account === overrideVal,
        {
          reopenedName,
          saved,
          overrideVal,
          screenshot: await screenshot(page, "04_saved_facility"),
        }
      );
    } else {
      log("C_save_and_reopen_persisted", false, { saveResult });
    }

    const noFs = benchExecute(
      "erpnext_extensions.facility_management.e2e.facility_dimension_link_prep.get_company_without_facility_settings"
    );
    if (noFs.company) {
      const pageD = await context.newPage();
      pageD.setDefaultTimeout(180000);
      await pageD.goto(`${BASE}${ROUTE}`, { waitUntil: "domcontentloaded" });
      await waitForm(pageD);

      await pageD.evaluate(async (company) => {
        if (cur_frm.doc.company && cur_frm.doc.company !== company) {
          await cur_frm.set_value("company", "");
        }
        await cur_frm.set_value("company", company);
      }, noFs.company);
      await pageD.waitForTimeout(4000);

      const missingDoc = await pageD.evaluate((fields) => {
        const doc = {};
        for (const fn of fields) {
          doc[fn] = cur_frm.doc[fn] || "";
        }
        return doc;
      }, ALL_DEFAULT_FIELDS);
      const stillUsable = await pageD.evaluate(
        () => !!(window.cur_frm && cur_frm.is_new())
      );
      log(
        "D_missing_facility_settings",
        stillUsable && !missingDoc.bank_account,
        {
          company: noFs.company,
          missingDoc,
          screenshot: await screenshot(pageD, "05_missing_settings"),
        }
      );
      await pageD.close();
    } else {
      log("D_missing_facility_settings", false, {
        error: "could not resolve company without settings",
      });
    }

    const apiInsert = benchExecute(
      "erpnext_extensions.facility_management.e2e.facility_dimension_link_prep.insert_api_facility_with_defaults"
    );
    report.apiFacilityName = apiInsert.name;
    log("E_api_server_fallback", !!apiInsert.bank_account && !!apiInsert.name, {
      apiInsert,
    });
  } finally {
    await browser.close();
  }

  report.investigation.networkSamples = apiResponses.slice(-3);
  const all_ok = results.every((r) => r.ok);
  console.log(JSON.stringify({ all_ok, report, results }, null, 2));
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
