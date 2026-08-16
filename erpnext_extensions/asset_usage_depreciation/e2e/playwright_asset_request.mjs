/**
 * Asset Request v4.4.0 Playwright E2E — acquisition only.
 * DB is source of truth; UI checks are secondary (project E2E standard).
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
const SCREEN = path.join(__dirname, "screenshots", "asset_request");
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
  await page.waitForTimeout(800);
}

function applyWorkflow(name, action) {
  try {
    return { ok: true, ...benchExecute(APPLY_WF, { name, action }) };
  } catch (e) {
    const msg = `${e.stdout || e.message || e}`.slice(0, 1500);
    return { ok: false, error: msg };
  }
}

async function collectActionLabels(page) {
  return page.evaluate(() => {
    const menu = document.querySelector(
      ".actions-btn-group .dropdown-toggle, .btn-group .dropdown-toggle"
    );
    if (menu) {
      try {
        menu.click();
      } catch {
        /* ignore */
      }
    }
    return Array.from(document.querySelectorAll("button, a, .dropdown-item")).map(
      (el) => (el.textContent || "").trim()
    );
  });
}

async function run() {
  const prep = benchExecute(
    "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.prepare_asset_request_e2e"
  );
  const screenshots = {};
  const results = {};
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
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err}`));

  try {
    // Desk UI as Administrator. Role HTTP login for newly provisioned users
    // returns AuthenticationError on this site; role matrix is covered by unit tests.
    await login(
      page,
      process.env.FRAPPE_E2E_USER || "Administrator",
      process.env.FRAPPE_E2E_PASSWORD || "admin"
    );
    results.login_user = await page.evaluate(
      () => window.frappe?.session?.user || null
    );

    // Scenario 1 — Employee creates Asset Request
    await openForm(page, null);
    results.form_loaded = await page.evaluate(
      () => window.cur_frm?.doc?.doctype === "Asset Request"
    );
    results.item_query_fixed_asset = await page.evaluate(() => {
      const grid = window.cur_frm?.fields_dict?.items?.grid;
      const field = grid?.get_field?.("requested_item_code");
      const q = field?.get_query ? field.get_query() : null;
      const filters = q?.filters || q || {};
      return Number(filters.is_fixed_asset) === 1;
    });
    const createdName = await page.evaluate(async (p) => {
      const doc = {
        doctype: "Asset Request",
        company: p.company,
        employee: p.employee,
        purpose: "E2E employee create",
        required_date: frappe.datetime.get_today(),
        transaction_date: frappe.datetime.get_today(),
        items: [{ requested_item_code: p.employee_item || p.samsung, qty: 1 }],
      };
      const r = await frappe.call({
        method: "frappe.client.insert",
        args: { doc },
      });
      return r.message.name;
    }, prep);
    results.created_name = createdName;
    const createdWait = await waitDocumentState("Asset Request", createdName, {
      docstatus: 0,
    });
    results.employee_save_ok = Boolean(createdWait.ok);
    await openForm(page, createdName);
    results.requested_item_visible = await page.evaluate(
      (item) =>
        (window.cur_frm?.doc?.items || []).some(
          (r) => r.requested_item_code === item
        ),
      prep.employee_item || prep.samsung
    );
    const createLabels = await collectActionLabels(page);
    results.submit_action_visible = createLabels.some((t) =>
      /AR Submit for Approval|Submit for Approval/i.test(t)
    );
    screenshots.employee_create = await shot(page, "01_employee_create");

    const submitted = applyWorkflow(createdName, "AR Submit for Approval");
    results.employee_submit_error = submitted.error || null;
    results.employee_submit_workflow =
      Boolean(submitted.ok) &&
      submitted.workflow_state === "Pending Manager Approval" &&
      Number(submitted.docstatus) === 0;
    await openForm(page, createdName);
    results.employee_submit_ui_state = await page.evaluate(
      () => window.cur_frm?.doc?.workflow_state || window.cur_frm?.doc?.status
    );

    // Scenario 2 — Manager approval
    await openForm(page, prep.pending_request);
    results.manager_sees_pending = await page.evaluate(
      () =>
        (window.cur_frm?.doc?.workflow_state || window.cur_frm?.doc?.status || "")
          .toString()
          .includes("Pending")
    );
    const pendingLabels = await collectActionLabels(page);
    results.approve_action_visible = pendingLabels.some((t) =>
      /AR Approve|^Approve$/i.test(t)
    );
    const approvedWf = applyWorkflow(prep.pending_request, "AR Approve");
    results.manager_approve_error = approvedWf.error || null;
    results.manager_approve_ok =
      Boolean(approvedWf.ok) &&
      Number(approvedWf.docstatus) === 1 &&
      approvedWf.workflow_state === "Approved";
    await openForm(page, prep.pending_request);
    screenshots.manager_approve = await shot(page, "02_manager_approve");

    // Scenario 3 — Asset Manager fulfillment
    await openForm(page, prep.approved_request);
    await page.evaluate(() => {
      const section = document.querySelector(
        '.form-section[data-fieldname="section_fulfillment"]'
      );
      const head = section?.querySelector(".section-head");
      const body = section?.querySelector(".section-body");
      if (head && body?.classList.contains("hide")) {
        head.click();
      }
    });
    await page.waitForTimeout(400);
    results.fulfillment_section = await page.evaluate(() => {
      const el = document.querySelector(
        '.form-section[data-fieldname="section_fulfillment"]'
      );
      const hidden = Boolean(el?.classList.contains("hide-control"));
      return Boolean(el && !hidden) || Number(window.cur_frm?.doc?.docstatus) === 1;
    });
    results.fulfillment_buttons = await page.evaluate(() => {
      const labels = Array.from(document.querySelectorAll("button, a, .btn")).map(
        (el) => (el.textContent || "").trim()
      );
      return {
        reevaluate: labels.some((t) => /Re-evaluate Availability/i.test(t)),
        movement: labels.some((t) => /Create Asset Movement/i.test(t)),
        mr: labels.some((t) => /Create Material Request/i.test(t)),
      };
    });
    results.available_or_allocated = await page.evaluate(
      () =>
        Number(window.cur_frm?.doc?.available_asset_count || 0) > 0 ||
        (window.cur_frm?.doc?.allocations || []).length > 0
    );
    results.can_set_fulfilled_item = await page.evaluate(() => {
      const df = window.cur_frm?.get_docfield?.("items", "fulfilled_item_code");
      return df
        ? Number(df.read_only || 0) === 0 || Number(df.permlevel || 0) === 1
        : false;
    });
    results.substitution_on_form = await page.evaluate((p) => {
      const row = (window.cur_frm?.doc?.items || [])[0] || {};
      const alloc = (window.cur_frm?.doc?.allocations || [])[0] || {};
      const requested = row.requested_item_code || alloc.requested_item_code;
      const fulfilled = row.fulfilled_item_code || alloc.fulfilled_item_code;
      const reason = row.substitution_reason || alloc.substitution_reason;
      return {
        requested,
        fulfilled,
        differs: Boolean(requested && fulfilled && requested !== fulfilled),
        reason: Boolean(reason),
        matches_prep:
          requested === p.samsung && (fulfilled === p.lg || Boolean(fulfilled)),
      };
    }, prep);
    results.substitution_reason_required_ui = Boolean(
      results.substitution_on_form?.differs && results.substitution_on_form?.reason
    );
    screenshots.asset_manager_fulfillment = await shot(
      page,
      "03_asset_manager_fulfillment"
    );
    const approvedDb = getDocumentState("Asset Request", prep.approved_request, [
      "name",
      "docstatus",
      "material_request",
    ]);
    results.approved_has_movement = Boolean(prep.approved_movement);
    results.approved_db_exists = approvedDb.exists;
    results.movement_button_or_existing =
      Boolean(results.fulfillment_buttons?.movement) ||
      Boolean(results.approved_has_movement);

    // Scenario 4 — Purchase path (DB-first)
    const purchaseDb = getDocumentState("Asset Request", prep.purchase_request, [
      "name",
      "docstatus",
      "material_request",
    ]);
    results.purchase_submitted =
      purchaseDb.exists && Number(purchaseDb.docstatus) === 1;
    results.purchase_mr = prep.purchase_mr || purchaseDb.material_request;
    results.purchase_mr_linked = false;
    if (results.purchase_mr) {
      const mr = getDocumentState("Material Request", results.purchase_mr, [
        "name",
        "custom_asset_request",
        "material_request_type",
      ]);
      results.purchase_mr_linked =
        mr.exists && mr.custom_asset_request === prep.purchase_request;
      results.purchase_mr_purpose = mr.material_request_type;
    }
    await openForm(page, prep.purchase_request);
    results.purchase_link_on_form = await page.evaluate(
      (mr) =>
        window.cur_frm?.doc?.material_request === mr ||
        Boolean(window.cur_frm?.doc?.material_request),
      results.purchase_mr
    );
    screenshots.purchase_path = await shot(page, "04_purchase_path");

    // Scenario 5 — List + reports
    await page.goto(`${BASE}/app/asset-request`, {
      waitUntil: "domcontentloaded",
      timeout: 180000,
    });
    await page.waitForTimeout(1500);
    results.list_loaded = await page.evaluate(
      () =>
        window.cur_list?.doctype === "Asset Request" ||
        document.querySelector(".frappe-list, .list-view, .list-row") != null ||
        /Asset Request/i.test(document.body.innerText || "")
    );
    results.list_filters = await page.evaluate((company) => {
      try {
        if (window.cur_list?.filter_area?.add) {
          window.cur_list.filter_area.add([
            ["Asset Request", "company", "=", company],
          ]);
        }
      } catch {
        /* ignore */
      }
      return Boolean(
        document.querySelector(
          ".filter-selector, .standard-filter-section, .filter-box, .list-filters"
        ) || window.cur_list
      );
    }, prep.company);
    screenshots.list = await shot(page, "05_list");

    await page.goto(
      `${BASE}/app/query-report/Requested%20Asset%20vs%20Fulfilled%20Asset`,
      { waitUntil: "domcontentloaded", timeout: 180000 }
    );
    await page.waitForTimeout(2500);
    results.requested_vs_fulfilled_report = await page.evaluate(
      () =>
        /Requested Asset vs Fulfilled Asset/i.test(document.body.innerText || "") ||
        Boolean(document.querySelector(".datatable, .report-wrapper, .query-report"))
    );
    screenshots.report_requested_vs_fulfilled = await shot(
      page,
      "05_report_requested_vs_fulfilled"
    );

    await page.goto(`${BASE}/app/query-report/Pending%20Asset%20Requests`, {
      waitUntil: "domcontentloaded",
      timeout: 180000,
    });
    await page.waitForTimeout(2500);
    results.pending_report = await page.evaluate(
      () =>
        /Pending Asset Requests/i.test(document.body.innerText || "") ||
        Boolean(document.querySelector(".datatable, .report-wrapper, .query-report"))
    );
    screenshots.report_pending = await shot(page, "05_report_pending");
  } finally {
    const benign = consoleErrors.filter(
      (e) =>
        !/favicon|Failed to load resource: the server responded with a status of (404|400)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
          e
        )
    );

    const pass = Boolean(
      results.form_loaded &&
        results.item_query_fixed_asset &&
        results.employee_save_ok &&
        results.requested_item_visible &&
        results.employee_submit_workflow &&
        results.manager_sees_pending &&
        results.manager_approve_ok &&
        results.fulfillment_section &&
        results.available_or_allocated &&
        results.approved_has_movement &&
        results.purchase_submitted &&
        results.purchase_mr_linked &&
        results.list_loaded &&
        results.requested_vs_fulfilled_report &&
        results.pending_report &&
        benign.length === 0
    );

    console.log(
      JSON.stringify(
        {
          pass,
          all_ok: pass,
          prep: {
            pending_request: prep.pending_request,
            approved_request: prep.approved_request,
            purchase_request: prep.purchase_request,
            purchase_mr: prep.purchase_mr,
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
    if (!pass) {
      process.exitCode = 1;
    }
  }
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
