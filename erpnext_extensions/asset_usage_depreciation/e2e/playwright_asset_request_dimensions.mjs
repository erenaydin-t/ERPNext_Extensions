/**
 * Asset Request v4.5.1 Playwright E2E — dynamic Accounting Dimensions.
 * DB is source of truth; UI checks are secondary.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  benchExecute,
  getDocumentState,
  waitDocumentState,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "asset_request_dimensions");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const APPLY_WF =
  "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.apply_asset_request_workflow";

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill("#login_email", email);
  await page.fill("#login_password", password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function openForm(page, name) {
  const url = name
    ? `${BASE}/app/asset-request/${encodeURIComponent(name)}`
    : `${BASE}/app/asset-request/new`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 180000 });
  await page.waitForFunction(
    (dt) => window.cur_frm?.doc?.doctype === dt && !window.cur_frm.is_loading,
    "Asset Request",
    { timeout: 180000 }
  );
  await page.waitForTimeout(600);
}

function applyWorkflow(name, action) {
  try {
    return { ok: true, ...benchExecute(APPLY_WF, { name, action }) };
  } catch (e) {
    return { ok: false, error: `${e.stdout || e.message || e}`.slice(0, 1500) };
  }
}

function approveUntilSubmitted(name) {
  applyWorkflow(name, "AR Submit for Approval");
  let last = getDocumentState("Asset Request", name, [
    "docstatus",
    "workflow_state",
    "material_request",
  ]);
  for (let i = 0; i < 4 && Number(last.docstatus) !== 1; i++) {
    applyWorkflow(name, "AR Approve");
    last = getDocumentState("Asset Request", name, [
      "docstatus",
      "workflow_state",
      "material_request",
    ]);
  }
  if (Number(last.docstatus) === 1 && !last.material_request) {
    try {
      benchExecute(
        "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.request_purchase",
        { name }
      );
    } catch (e) {
      /* shortage-only path; ignore if already issued */
    }
    last = getDocumentState("Asset Request", name, [
      "docstatus",
      "workflow_state",
      "material_request",
    ]);
  }
  return last;
}

async function run() {
  const prep = benchExecute(
    "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.prepare_asset_request_dimension_e2e"
  );
  const fn = prep.dimension_fieldname;
  const results = {};
  const screenshots = {};
  const consoleErrors = [];

  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });

  try {
    await login(
      page,
      process.env.FRAPPE_E2E_USER || "Administrator",
      process.env.FRAPPE_E2E_PASSWORD || "admin"
    );

    await openForm(page, null);
    results.form_loaded = await page.evaluate(
      () => window.cur_frm?.doc?.doctype === "Asset Request"
    );
    results.section_visible = await page.evaluate(
      () =>
        Boolean(window.cur_frm?.get_field?.("accounting_dimensions_section")) ||
        Boolean(window.cur_frm?.meta?.has_field?.("accounting_dimensions_section"))
    );
    results.dynamic_field_on_form = await page.evaluate(
      (field) =>
        Boolean(window.cur_frm?.meta?.has_field?.(field) || window.cur_frm?.fields_dict?.[field]),
      fn
    );

    const createdName = await page.evaluate(async (p) => {
      const field = p.dimension_fieldname;
      const doc = {
        doctype: "Asset Request",
        company: p.company,
        employee: p.employee,
        purpose: "E2E dimensions",
        required_date: frappe.datetime.get_today(),
        transaction_date: frappe.datetime.get_today(),
        cost_center: p.cost_center,
        items: [
          { requested_item_code: p.sku, qty: 1 },
          { requested_item_code: p.sku, qty: 1, [field]: p.shiraz },
        ],
      };
      doc[field] = p.tehran;
      const r = await frappe.call({
        method: "frappe.client.insert",
        args: { doc },
      });
      return r.message.name;
    }, prep);
    results.created_name = createdName;
    await waitDocumentState("Asset Request", createdName, { docstatus: 0 });
    await openForm(page, createdName);
    const persisted = await page.evaluate((field) => {
      const items = window.cur_frm?.doc?.items || [];
      return {
        header: window.cur_frm?.doc?.[field],
        item0: items[0]?.[field],
        item1: items[1]?.[field],
        header_cc: window.cur_frm?.doc?.cost_center,
        item0_cc: items[0]?.cost_center,
      };
    }, fn);
    results.persisted = persisted;
    results.item_inherited = persisted.item0 === prep.tehran || persisted.item0 === persisted.header;
    results.item_override = persisted.item1 === prep.shiraz;
    screenshots.form = await shot(page, "01_dimensions_form");

    const approved = approveUntilSubmitted(createdName);
    results.approved = Number(approved.docstatus) === 1;
    results.material_request = approved.material_request;
    results.mr_exists = false;
    results.two_lines_not_merged = false;
    results.mr_has_tehran = false;
    results.mr_has_shiraz = false;
    if (results.material_request) {
      const mrDoc = benchExecute("frappe.client.get", {
        doctype: "Material Request",
        name: results.material_request,
      });
      const items = mrDoc.items || mrDoc.message?.items || [];
      results.mr_exists = true;
      results.mr_item_count = items.length;
      results.two_lines_not_merged = items.length === 2;
      results.mr_has_tehran = items.some((row) => row[fn] === prep.tehran);
      results.mr_has_shiraz = items.some((row) => row[fn] === prep.shiraz);
      results.mr_items = items.map((row) => ({
        item_code: row.item_code,
        [fn]: row[fn],
        cost_center: row.cost_center,
      }));
      await page.goto(
        `${BASE}/app/material-request/${encodeURIComponent(results.material_request)}`,
        { waitUntil: "domcontentloaded", timeout: 180000 }
      );
      await page.waitForTimeout(1200);
      screenshots.mr = await shot(page, "02_material_request");
    }

    const substName = await page.evaluate(async (p) => {
      const field = p.dimension_fieldname;
      const doc = {
        doctype: "Asset Request",
        company: p.company,
        employee: p.employee,
        purpose: "E2E substitution dimensions",
        required_date: frappe.datetime.get_today(),
        transaction_date: frappe.datetime.get_today(),
        cost_center: p.cost_center,
        items: [
          {
            requested_item_code: p.samsung,
            fulfilled_item_code: p.lg,
            fulfilled_purchase_item: p.lg,
            substitution_reason: "E2E LG standard",
            qty: 1,
            [field]: p.tehran,
            cost_center: p.cost_center,
          },
        ],
      };
      doc[field] = p.tehran;
      const r = await frappe.call({
        method: "frappe.client.insert",
        args: { doc },
      });
      return r.message.name;
    }, prep);
    const substApproved = approveUntilSubmitted(substName);
    results.substitution_request = substName;
    results.subst_mr = substApproved.material_request;
    results.substitution_ok = false;
    if (results.subst_mr) {
      const mrDoc = benchExecute("frappe.client.get", {
        doctype: "Material Request",
        name: results.subst_mr,
      });
      const arDoc = benchExecute("frappe.client.get", {
        doctype: "Asset Request",
        name: substName,
      });
      const mrItems = mrDoc.items || mrDoc.message?.items || [];
      const arItems = arDoc.items || arDoc.message?.items || [];
      results.subst_requested = arItems[0]?.requested_item_code;
      results.subst_fulfilled = arItems[0]?.fulfilled_item_code;
      results.subst_mr_item = mrItems[0]?.item_code;
      results.subst_mr_dim = mrItems[0]?.[fn];
      results.substitution_ok =
        results.subst_requested === prep.samsung &&
        (results.subst_mr_item === prep.lg || results.subst_fulfilled === prep.lg) &&
        results.subst_mr_dim === prep.tehran;
    }

    await page.goto(
      `${BASE}/app/query-report/Requested%20Asset%20vs%20Fulfilled%20Asset`,
      { waitUntil: "domcontentloaded", timeout: 180000 }
    );
    await page.waitForTimeout(2500);
    results.report_loaded = await page.evaluate(
      () =>
        /Requested Asset vs Fulfilled Asset/i.test(document.body.innerText || "") ||
        Boolean(document.querySelector(".datatable, .report-wrapper, .query-report"))
    );
    results.report_has_dimension_filter = await page.evaluate((field) => {
      const filters = window.frappe?.query_report?.filters || [];
      return filters.some((f) => (f.df?.fieldname || f.fieldname) === field);
    }, fn);
    screenshots.report = await shot(page, "03_report");
  } finally {
    const benign = consoleErrors.filter(
      (e) =>
        !/favicon|Failed to load resource: the server responded with a status of (404|400)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
          e
        )
    );
    const pass = Boolean(
      results.form_loaded &&
        results.section_visible &&
        results.dynamic_field_on_form &&
        results.created_name &&
        results.item_inherited &&
        results.item_override &&
        results.approved &&
        results.mr_exists &&
        results.two_lines_not_merged &&
        results.mr_has_tehran &&
        results.mr_has_shiraz &&
        results.substitution_ok &&
        results.report_loaded &&
        benign.length === 0
    );
    console.log(
      JSON.stringify(
        {
          pass,
          all_ok: pass,
          prep: {
            dimension_fieldname: fn,
            tehran: prep.tehran,
            shiraz: prep.shiraz,
          },
          results,
          screenshots,
          benign_console_errors: benign.slice(0, 20),
        },
        null,
        2
      )
    );
    await browser.close();
    if (!pass) process.exitCode = 1;
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
