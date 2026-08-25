/**
 * v4.6.7 — Payment Entry Desk cancel must not require cancelling PM Request.
 *
 * Root cause fix: append "PM Request" to frm.ignore_doctypes_on_cancel_all.
 * Assert: no Cancel-All dialog, PE cancelled, Request stays submitted, funding recalculated.
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
const SCREEN = path.join(__dirname, "screenshots", "pm_pe_desk_cancel");
const TRACE = path.join(__dirname, "traces", "pm_pe_desk_cancel.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

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
  );
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function waitPeForm(page, peName) {
  await page.waitForFunction(
    (name) =>
      window.cur_frm?.doc?.doctype === "Payment Entry" &&
      window.cur_frm.doc.name === name &&
      !window.cur_frm.is_loading,
    peName,
    { timeout: 180000 }
  );
}

async function clickCancel(page) {
  try {
    await page
      .getByRole("button", { name: /^Cancel$/i })
      .first()
      .click({ timeout: 15000 });
  } catch {
    await page
      .getByRole("button", { name: /^(Menu|Actions|More)$/i })
      .first()
      .click();
    const dropdown = page.locator(".dropdown-menu:visible").first();
    await dropdown.waitFor({ timeout: 60000 });
    await dropdown.getByText(/^Cancel$/i).first().click();
  }
}

async function confirmSimpleCancel(page) {
  // Normal _cancel confirm ("Yes") — not Cancel All Documents.
  const modal = page.locator(".modal-dialog:visible").first();
  await modal.waitFor({ timeout: 60000 });
  const title = ((await modal.locator(".modal-title").textContent()) || "").trim();
  if (/cancel all/i.test(title)) {
    throw new Error(`Unexpected Cancel All dialog: ${title}`);
  }
  const body = ((await modal.innerText()) || "").trim();
  if (/PM Request/i.test(body) && /do not have permissions/i.test(body)) {
    throw new Error(`Cancel dialog still requires PM Request: ${body.slice(0, 500)}`);
  }
  const primary = modal.locator("button.btn-primary").first();
  await primary.click();
}

async function main() {
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.mkdirSync(path.dirname(TRACE), { recursive: true });

  const prep = benchExecute(
    "erpnext_extensions.petty_management.e2e.pm_pe_desk_cancel_prep.prepare_single_submitted_pe_for_desk_cancel"
  );
  const peName = prep.payment_entry;
  const reqName = prep.pm_request;
  const wsBefore = prep.workflow_state;

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
    // Host:port can fall through to default_site; pin the E2E site explicitly.
    extraHTTPHeaders: { "X-Frappe-Site-Name": SITE },
  });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  const results = [];
  const evidence = { screenshots: {}, prep, site: SITE };

  try {
    await login(
      page,
      process.env.FRAPPE_E2E_USER || "Administrator",
      process.env.FRAPPE_E2E_PASSWORD || "admin"
    );

    await page.goto(
      `${BASE}/desk/payment-entry/${encodeURIComponent(peName)}`,
      { waitUntil: "domcontentloaded", timeout: 120000 }
    );
    await waitPeForm(page, peName);
    evidence.screenshots.open = await shot(page, "01_pe_submitted");

    const ignoreList = await page.evaluate(() => {
      const list = window.cur_frm?.ignore_doctypes_on_cancel_all || [];
      return Array.isArray(list) ? list.slice() : [];
    });
    results.push({
      test: "desk_ignore_includes_pm_request",
      pass: ignoreList.includes("PM Request"),
      evidence: { ignoreList },
    });
    results.push({
      test: "desk_ignore_keeps_erpnext_doctypes",
      pass:
        ignoreList.includes("Sales Invoice") &&
        ignoreList.includes("Purchase Invoice") &&
        ignoreList.includes("Journal Entry"),
      evidence: { ignoreList },
    });

    await clickCancel(page);

    // Race: Cancel All would appear quickly if ignore failed.
    const cancelAllAppeared = await page
      .locator(".modal-dialog:visible .modal-title")
      .filter({ hasText: /Cancel All/i })
      .first()
      .isVisible()
      .catch(() => false);

    results.push({
      test: "no_cancel_all_dialog",
      pass: !cancelAllAppeared,
      evidence: { cancelAllAppeared },
    });

    await confirmSimpleCancel(page);
    evidence.screenshots.after_confirm = await shot(page, "02_after_confirm");

    await waitDocstatus("Payment Entry", peName, 2, { timeoutMs: 180000 });
    const peDb = getDocumentState("Payment Entry", peName, ["docstatus"]);
    results.push({
      test: "pe_cancelled",
      pass: peDb.exists && peDb.docstatus === 2,
      db: peDb,
    });

    const reqDb = getDocumentState("PM Request", reqName, [
      "docstatus",
      "workflow_state",
      "payment_status",
      "status",
      "payment_entry",
      "total_paid_amount",
    ]);
    results.push({
      test: "pm_request_still_submitted",
      pass: reqDb.exists && reqDb.docstatus === 1,
      db: reqDb,
    });
    results.push({
      test: "workflow_unchanged",
      pass: reqDb.workflow_state === wsBefore,
      db: { before: wsBefore, after: reqDb.workflow_state },
    });
    results.push({
      test: "payment_status_recalculated",
      pass:
        reqDb.payment_status === "Not Paid" &&
        Number(reqDb.total_paid_amount || 0) === 0 &&
        !reqDb.payment_entry,
      db: reqDb,
    });
    results.push({
      test: "business_status_waiting_for_payment",
      pass: ["Waiting for Payment", "Not Paid"].includes(reqDb.status),
      db: { status: reqDb.status },
    });

    evidence.screenshots.final = await shot(page, "03_final");

    const failed = results.filter((r) => !r.pass);
    const summary = {
      ok: failed.length === 0,
      pe: peName,
      pm_request: reqName,
      results,
      evidence,
    };
    console.log(JSON.stringify(summary, null, 2));
    if (failed.length) {
      throw new Error(
        `Failed: ${failed.map((f) => f.test).join(", ")}\n${JSON.stringify(failed, null, 2)}`
      );
    }
  } catch (err) {
    try {
      evidence.screenshots.failure = await shot(page, "99_failure");
    } catch {
      /* ignore */
    }
    console.error(
      JSON.stringify(
        {
          ok: false,
          error: String(err && err.message ? err.message : err),
          results,
          evidence,
        },
        null,
        2
      )
    );
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
