/**
 * v4.6.8 — PM Request cancel / delete Desk eligibility E2E.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  benchExecute,
  getDocumentState,
  waitDocstatus,
  SITE,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_cancel_delete");
const TRACE = path.join(__dirname, "traces", "pm_request_cancel_delete.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://127.0.0.1:8001";

async function login(page, email, password) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill("#login_email", email);
  await page.fill("#login_password", password);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
  await page.waitForFunction(
    (expected) => window.frappe?.boot?.sitename === expected,
    SITE,
    { timeout: 60000 }
  ).catch(() => {});
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openPmRequest(page, name) {
  await page.goto(`${BASE}/desk/pm-request/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.waitForFunction(
    (n) =>
      window.cur_frm?.doc?.doctype === "PM Request" &&
      window.cur_frm.doc.name === n &&
      !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function clickCancel(page) {
  try {
    await page.getByRole("button", { name: /^Cancel$/i }).first().click({ timeout: 15000 });
  } catch {
    await page.getByRole("button", { name: /^(Menu|Actions|More)$/i }).first().click();
    await page.locator(".dropdown-menu:visible").getByText(/^Cancel$/i).first().click();
  }
}

async function clickDelete(page) {
  try {
    await page.getByRole("button", { name: /^Delete$/i }).first().click({ timeout: 15000 });
  } catch {
    await page.getByRole("button", { name: /^(Menu|Actions|More)$/i }).first().click();
    await page.locator(".dropdown-menu:visible").getByText(/^Delete$/i).first().click();
  }
}

async function confirmPrimary(page) {
  const modal = page.locator(".modal-dialog:visible").first();
  await modal.waitFor({ timeout: 60000 });
  await modal.locator("button.btn-primary").first().click();
}

async function main() {
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.mkdirSync(path.dirname(TRACE), { recursive: true });

  const results = [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
    extraHTTPHeaders: { "X-Frappe-Site-Name": SITE },
  });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();

  try {
    await login(
      page,
      process.env.FRAPPE_E2E_USER || "Administrator",
      process.env.FRAPPE_E2E_PASSWORD || "admin"
    );

    // 1) Eligible cancel
    const unfunded = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_unfunded_for_cancel"
    );
    await openPmRequest(page, unfunded.pm_request);
    await shot(page, "01_unfunded_before_cancel");
    await clickCancel(page);
    await confirmPrimary(page);
    await waitDocstatus("PM Request", unfunded.pm_request, 2, { timeoutMs: 180000 });
    const afterCancel = getDocumentState("PM Request", unfunded.pm_request, [
      "docstatus",
      "status",
      "workflow_state",
    ]);
    results.push({
      test: "cancel_eligible_unfunded",
      pass:
        afterCancel.docstatus === 2 &&
        afterCancel.status === "Cancelled" &&
        afterCancel.workflow_state === unfunded.workflow_state,
      db: afterCancel,
    });

    // 2) Blocked cancel (funded)
    const funded = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_funded_for_cancel_block"
    );
    await openPmRequest(page, funded.pm_request);
    await clickCancel(page);
    await confirmPrimary(page).catch(() => {});
    await page.waitForTimeout(3000);
    const stillSub = getDocumentState("PM Request", funded.pm_request, ["docstatus"]);
    results.push({
      test: "cancel_blocked_funded",
      pass: stillSub.docstatus === 1,
      db: stillSub,
    });
    await shot(page, "02_funded_cancel_blocked");

    // 3) After PE cancel → Request cancel OK
    const afterPe = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_after_pe_cancel_for_request_cancel"
    );
    await openPmRequest(page, afterPe.pm_request);
    await clickCancel(page);
    await confirmPrimary(page);
    await waitDocstatus("PM Request", afterPe.pm_request, 2, { timeoutMs: 180000 });
    results.push({
      test: "cancel_after_pe_cancel",
      pass: getDocumentState("PM Request", afterPe.pm_request, ["docstatus"]).docstatus === 2,
    });

    // 4) Delete clean cancelled
    const cleanDel = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_cancelled_clean_for_delete"
    );
    await openPmRequest(page, cleanDel.pm_request);
    await clickDelete(page);
    await confirmPrimary(page);
    await page.waitForTimeout(4000);
    const gone = getDocumentState("PM Request", cleanDel.pm_request, ["name"]);
    results.push({
      test: "delete_clean_cancelled",
      pass: !gone.exists,
      db: gone,
    });

    // 5) Delete blocked — PE history
    const peHist = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_cancelled_with_pe_history_for_delete_block"
    );
    await openPmRequest(page, peHist.pm_request);
    await clickDelete(page);
    await confirmPrimary(page).catch(() => {});
    await page.waitForTimeout(3000);
    const stillThere = getDocumentState("PM Request", peHist.pm_request, ["docstatus"]);
    results.push({
      test: "delete_blocked_pe_history",
      pass: stillThere.exists && stillThere.docstatus === 2,
      db: stillThere,
    });

    // 6) Draft delete clean
    const draft = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_clean_draft_for_delete"
    );
    await openPmRequest(page, draft.pm_request);
    await clickDelete(page);
    await confirmPrimary(page);
    await page.waitForTimeout(4000);
    const draftGone = getDocumentState("PM Request", draft.pm_request, ["name"]);
    results.push({
      test: "delete_clean_draft",
      pass: !draftGone.exists,
      db: draftGone,
    });

    // 7) Multi-payment partial funding — cancel blocked
    const multi = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_multi_pe_partial_for_cancel_block"
    );
    await openPmRequest(page, multi.pm_request);
    await clickCancel(page);
    await confirmPrimary(page).catch(() => {});
    await page.waitForTimeout(3000);
    const multiStill = getDocumentState("PM Request", multi.pm_request, ["docstatus"]);
    results.push({
      test: "cancel_blocked_multi_pe_partial",
      pass: multiStill.docstatus === 1 && Number(multi.total_paid_amount) > 0,
      db: multiStill,
    });

    // 8) Delete blocked — Clearance history
    const clrHist = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_request_cancel_delete_prep.prepare_cancelled_with_clearance_history_for_delete_block"
    );
    await openPmRequest(page, clrHist.pm_request);
    await clickDelete(page);
    await confirmPrimary(page).catch(() => {});
    await page.waitForTimeout(3000);
    const clrStill = getDocumentState("PM Request", clrHist.pm_request, ["docstatus"]);
    results.push({
      test: "delete_blocked_clearance_history",
      pass: clrStill.exists && clrStill.docstatus === 2,
      db: clrStill,
    });

    await shot(page, "99_final");
    const failed = results.filter((r) => !r.pass);
    console.log(JSON.stringify({ ok: failed.length === 0, results }, null, 2));
    if (failed.length) {
      process.exitCode = 1;
    }
  } catch (err) {
    try {
      await shot(page, "99_failure");
    } catch {
      /* ignore */
    }
    console.error(JSON.stringify({ ok: false, error: String(err && err.message ? err.message : err), results }, null, 2));
    process.exitCode = 1;
  } finally {
    try {
      await context.tracing.stop({ path: TRACE });
    } catch {
      /* ignore */
    }
    await browser.close();
  }
}

main();
