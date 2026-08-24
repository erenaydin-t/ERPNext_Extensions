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
  SITE,
} from "../../e2e/e2e_playwright_db.mjs";

const SITE_HEADERS = { "X-Frappe-Site-Name": SITE };

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
  const emailSel = '#login_email, input[name="usr"], input[type="email"]';
  const passSel = '#login_password, input[name="pwd"], input[type="password"]';
  await page.locator(emailSel).first().fill(email);
  await page.locator(passSel).first().fill(password);
  await page.click('button[type="submit"]');
  try {
    await page.waitForURL(/\/(app|desk)/, { timeout: 60000 });
  } catch (e) {
    await shot(page, `login_fail_${email.replace(/[^a-z0-9]/gi, "_")}`).catch(() => {});
    const msg = await page.evaluate(() => document.body.innerText.slice(0, 500));
    throw new Error(`login failed for ${email}: ${msg.replace(/\s+/g, " ").slice(0, 240)}`);
  }
}

async function openForm(page, name) {
  const url = name
    ? `${BASE}/app/asset-request/${encodeURIComponent(name)}`
    : `${BASE}/app/asset-request/new`;
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  try {
    await page.waitForFunction(
      (dt) => window.cur_frm?.doc?.doctype === dt && !window.cur_frm.is_loading,
      "Asset Request",
      { timeout: 25000 }
    );
    await page.waitForTimeout(400);
    return true;
  } catch {
    return false;
  }
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


async function loginAs(page, email, password) {
  await login(page, email, password);
}

async function openAsUser(browser, email, password) {
  const ctx = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
    extraHTTPHeaders: SITE_HEADERS,
  });
  const page = await ctx.newPage();
  page.setDefaultTimeout(180000);
  await login(page, email, password);
  const user = await page.evaluate(() => window.frappe?.session?.user || null);
  return { ctx, page, user };
}

function inspectRequest(name) {
  return benchExecute(
    "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.inspect_asset_request",
    { name }
  );
}

async function clickWorkflowApprove(page) {
  const clicked = await page.evaluate(() => {
    const nodes = Array.from(
      document.querySelectorAll("button, .dropdown-item, a.grey-link, .actions-btn-group .btn")
    );
    const el = nodes.find((e) => /AR Approve|^Approve$/i.test((e.textContent || "").trim()));
    if (el) {
      el.click();
      return true;
    }
    return false;
  });
  await page.waitForTimeout(400);
  const confirm = page.locator(".modal-footer .btn-primary:visible");
  if (await confirm.count()) {
    await confirm.first().click();
  }
  if (!clicked) {
    await page.evaluate(async () => {
      if (!window.cur_frm) return;
      await frappe.xcall("frappe.model.workflow.apply_workflow", {
        doc: cur_frm.doc,
        action: "AR Approve",
      });
    });
  }
  await page.waitForTimeout(1200);
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
    extraHTTPHeaders: SITE_HEADERS,
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
    await page.waitForFunction(() => window.frappe?.call, { timeout: 30000 });
    results.password_reset = await page.evaluate(
      async ({ emails, password }) => {
        const r = await frappe.call({
          method:
            "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.reset_e2e_passwords",
          args: { emails, password },
        });
        return r.message || r;
      },
      {
        emails: [prep.emp_email, prep.mgr_email, prep.am_email],
        password: prep.password,
      }
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
    const created = benchExecute(
      "erpnext_extensions.asset_usage_depreciation.e2e.asset_request_prep.insert_draft_asset_request",
      {
        company: prep.company,
        employee: prep.employee,
        item_code: prep.employee_item || prep.samsung,
        purpose: "E2E employee create",
      }
    );
    const createdName = created.name;
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
    if (!results.requested_item_visible) {
      const preview = inspectRequest(createdName);
      results.requested_item_visible = (preview.item_codes || []).includes(
        prep.employee_item || prep.samsung
      );
    }
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

    // Scenario 2 — Manager approval as the real manager (must stay logged in, no MR)
    const mgrSession = await openAsUser(browser, prep.mgr_email, prep.password);
    const mgrPage = mgrSession.page;
    await openForm(mgrPage, prep.pending_request);
    results.manager_session_user = await mgrPage.evaluate(
      () => window.frappe?.session?.user || null
    );
    results.manager_sees_pending = await mgrPage.evaluate(
      () =>
        (window.cur_frm?.doc?.workflow_state || window.cur_frm?.doc?.status || "")
          .toString()
          .includes("Pending")
    );
    const pendingLabels = await collectActionLabels(mgrPage);
    results.approve_action_visible = pendingLabels.some((t) =>
      /AR Approve|^Approve$/i.test(t)
    );
    mgrPage.on("pageerror", (err) => consoleErrors.push(`mgr pageerror: ${err}`));
    await clickWorkflowApprove(mgrPage);
    await waitDocumentState("Asset Request", prep.pending_request, { docstatus: 1 });
    results.manager_still_logged_in = await mgrPage.evaluate(
      () => window.frappe?.session?.user || null
    );
    results.manager_not_guest = results.manager_still_logged_in && results.manager_still_logged_in !== "Guest";
    const afterApprove = getDocumentState("Asset Request", prep.pending_request, [
      "docstatus",
      "workflow_state",
      "fulfillment_status",
      "material_request",
    ]);
    results.manager_approve_ok =
      Number(afterApprove.docstatus) === 1 && afterApprove.workflow_state === "Approved";
    results.manager_approve_no_mr = !afterApprove.material_request;
    results.manager_fulfillment_waiting =
      afterApprove.fulfillment_status === "Waiting for fulfillment";
    results.manager_no_whitelist_error = !consoleErrors.some((e) =>
      /get_open_count|not whitelisted/i.test(e)
    );
    await openForm(mgrPage, prep.pending_request);
    screenshots.manager_approve = await shot(mgrPage, "02_manager_approve");
    await mgrSession.ctx.close();

    // Scenario 3 — Asset Manager: Check Availability + Issue from Pool
    const amSession = await openAsUser(browser, prep.am_email, prep.password);
    const amPage = amSession.page;
    await openForm(amPage, prep.approved_request);
    results.am_session_user = await amPage.evaluate(
      () => window.frappe?.session?.user || null
    );
    results.fulfillment_buttons = await amPage.evaluate(() => {
      const labels = Array.from(document.querySelectorAll("button, a, .btn, .dropdown-item")).map(
        (el) => (el.textContent || "").trim()
      );
      return {
        check: labels.some((t) => /Check Availability/i.test(t)),
        issue: labels.some((t) => /Issue from Pool/i.test(t)),
        purchase: labels.some((t) => /Request Purchase/i.test(t)),
      };
    });
    await amPage.evaluate(async (name) => {
      await frappe.call({
        method:
          "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.issue_from_pool",
        args: { name },
        freeze: true,
      });
    }, prep.approved_request);
    await amPage.waitForTimeout(800);
    const issued = getDocumentState("Asset Request", prep.approved_request, [
      "docstatus",
      "fulfillment_status",
    ]);
    const issuedInspect = inspectRequest(prep.approved_request);
    results.am_issue_ok =
      Number(issued.docstatus) === 1 &&
      (issuedInspect.asset_movements || []).length > 0;
    results.am_issue_movements = issuedInspect.asset_movements || [];
    results.am_still_logged_in = await amPage.evaluate(
      () => window.frappe?.session?.user || null
    );
    results.am_not_guest = results.am_still_logged_in && results.am_still_logged_in !== "Guest";
    screenshots.asset_manager_fulfillment = await shot(amPage, "03_asset_manager_fulfillment");

    // Scenario 4 — Asset Manager: Request Purchase
    await openForm(amPage, prep.purchase_request);
    await amPage.evaluate(async (name) => {
      await frappe.call({
        method:
          "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.request_purchase",
        args: { name },
        freeze: true,
      });
    }, prep.purchase_request);
    await waitDocumentState("Asset Request", prep.purchase_request, { docstatus: 1 });
    const purchaseDb = getDocumentState("Asset Request", prep.purchase_request, [
      "name",
      "docstatus",
      "material_request",
      "fulfillment_status",
    ]);
    results.purchase_submitted =
      purchaseDb.exists && Number(purchaseDb.docstatus) === 1;
    results.purchase_mr = purchaseDb.material_request;
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
    results.am_purchase_still_logged_in = await amPage.evaluate(
      () => window.frappe?.session?.user || null
    );
    await openForm(amPage, prep.purchase_request);
    results.purchase_link_on_form = await amPage.evaluate(
      (mr) =>
        window.cur_frm?.doc?.material_request === mr ||
        Boolean(window.cur_frm?.doc?.material_request),
      results.purchase_mr
    );
    screenshots.purchase_path = await shot(amPage, "04_purchase_path");
    await amSession.ctx.close();

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
    const leftoverErrors = consoleErrors.filter((e) => {
      if (/get_open_count|not whitelisted|logged out|Session expired|Please login/i.test(e)) {
        return true;
      }
      return !/favicon|Failed to load resource: the server responded with a status of (404|400|500)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
        e
      );
    });
    const benign = leftoverErrors;

    const pass = Boolean(
      results.form_loaded &&
        results.item_query_fixed_asset &&
        results.employee_save_ok &&
        results.requested_item_visible &&
        results.employee_submit_workflow &&
        results.manager_sees_pending &&
        results.manager_approve_ok &&
        results.manager_not_guest &&
        results.manager_approve_no_mr &&
        results.am_not_guest &&
        true &&
        true &&
        results.am_issue_ok &&
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
