/**
 * Facility receipt & repayment JE preview E2E (Tests A–E).
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "receipt_split");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

function bench(method) {
  return benchExecute(method);
}

async function login(page) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill(
    "#login_email",
    process.env.FRAPPE_E2E_USER || "Administrator"
  );
  await page.fill(
    "#login_password",
    process.env.FRAPPE_E2E_PASSWORD || "admin"
  );
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

function rowsMatch(previewRows, jeAccounts) {
  if (previewRows.length !== jeAccounts.length) return false;
  for (let i = 0; i < previewRows.length; i++) {
    const p = previewRows[i];
    const j = jeAccounts[i];
    if (p.account !== j.account) return false;
    if (Number(p.debit || 0) !== Number(j.debit_in_account_currency || 0))
      return false;
    if (Number(p.credit || 0) !== Number(j.credit_in_account_currency || 0))
      return false;
  }
  return true;
}

async function run() {
  const receiptPrep = bench(
    "erpnext_extensions.facility_management.e2e.facility_receipt_split_prep.prepare_receipt_split_browser_facility"
  );
  const repayPrep = bench(
    "erpnext_extensions.facility_management.e2e.facility_je_preview_prep.prepare_repayment_preview_draft"
  );
  const failPrep = bench(
    "erpnext_extensions.facility_management.e2e.facility_je_preview_prep.prepare_facility_missing_bank_account"
  );

  const results = [];
  const evidence = { screenshots: {}, receipt: {}, repayment: {} };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  try {
    await login(page);

    // Test A — receipt preview
    await page.goto(
      `${BASE}/desk/facility/${encodeURIComponent(receiptPrep.facility)}`,
      {
        waitUntil: "domcontentloaded",
      }
    );
    await page.waitForFunction(
      () =>
        window.cur_frm?.doc?.doctype === "Facility" &&
        !window.cur_frm.is_loading,
      { timeout: 180000 }
    );
    const receiptPreviewUi = await page.evaluate(async () => {
      const r = await frappe.call({
        method:
          "erpnext_extensions.facility_management.doctype.facility.facility.preview_receipt_journal_entry",
        args: { name: cur_frm.doc.name },
      });
      erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog(
        r.message,
        "Receipt Journal Entry Preview"
      );
      return {
        ...r.message,
        receipt_journal_entry: cur_frm.doc.receipt_journal_entry,
      };
    });
    await page.waitForSelector(".modal-dialog:visible", { timeout: 30000 });
    evidence.screenshots.receipt_preview = await shot(
      page,
      "preview_receipt_4_rows"
    );
    const labels = (receiptPreviewUi.rows || []).map((r) => r.row_label);
    results.push({
      test: "A_receipt_preview",
      ok:
        receiptPreviewUi.balanced &&
        receiptPreviewUi.rows?.length === 4 &&
        labels.includes("Bank") &&
        labels.includes("Deferred Loan Interest") &&
        labels.includes("Loan Payable — Principal") &&
        labels.includes("Loan Payable — Profit") &&
        !receiptPreviewUi.receipt_journal_entry,
      receiptPreviewUi,
    });

    // Test B — create receipt after preview
    const createReceipt = await page.evaluate(async () => {
      const before = await frappe.db.get_value(
        "Facility",
        cur_frm.doc.name,
        "receipt_journal_entry"
      );
      const r = await frappe.call({
        method:
          "erpnext_extensions.facility_management.doctype.facility.facility.create_receipt_journal_entry",
        args: { name: cur_frm.doc.name },
      });
      const je = r.message?.journal_entry;
      const jeDoc = await frappe.db.get_doc("Journal Entry", je);
      return {
        je,
        beforeReceiptJe: before?.message?.receipt_journal_entry,
        accounts: jeDoc.accounts,
      };
    });
    evidence.receipt.create = createReceipt;
    results.push({
      test: "B_receipt_submit_matches_preview",
      ok:
        rowsMatch(receiptPreviewUi.rows, createReceipt.accounts) &&
        createReceipt.accounts.length === 4,
      createReceipt,
    });

    await page.goto(
      `${BASE}/desk/journal-entry/${encodeURIComponent(createReceipt.je)}`,
      { waitUntil: "domcontentloaded" }
    );
    await page.waitForFunction(
      () =>
        window.cur_frm?.doc?.doctype === "Journal Entry" &&
        !window.cur_frm.is_loading,
      {
        timeout: 180000,
      }
    );
    evidence.screenshots.submitted_je = await shot(page, "submitted_je_4_rows");

    // Test C — repayment preview
    await page.goto(
      `${BASE}/desk/facility-repayment/${encodeURIComponent(
        repayPrep.repayment
      )}`,
      { waitUntil: "domcontentloaded" }
    );
    await page.waitForFunction(
      () =>
        window.cur_frm?.doc?.doctype === "Facility Repayment" &&
        !window.cur_frm.is_loading,
      { timeout: 180000 }
    );
    const repayPreviewUi = await page.evaluate(async () => {
      const r = await frappe.call({
        method:
          "erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
        args: { doc: cur_frm.doc },
      });
      erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog(
        r.message,
        "Repayment Journal Entry Preview"
      );
      return r.message;
    });
    await page.waitForSelector(".modal-dialog:visible", { timeout: 30000 });
    evidence.screenshots.repayment_preview = await shot(
      page,
      "C_repayment_preview_dialog"
    );
    results.push({
      test: "C_repayment_preview",
      ok:
        repayPreviewUi.balanced &&
        repayPreviewUi.rows?.length === 6 &&
        repayPreviewUi.total_debit === 1140 &&
        repayPreviewUi.total_credit === 1140,
      repayPreviewUi,
    });

    // Test D — submit repayment after preview
    const submitRepay = await page.evaluate(async (previewRows) => {
      const r = await frappe.call({
        method: "frappe.client.submit",
        args: { doc: cur_frm.doc },
      });
      const doc = r.message || {};
      const jeDoc = await frappe.db.get_doc("Journal Entry", doc.journal_entry);
      return {
        repayment: doc.name,
        je: doc.journal_entry,
        accounts: jeDoc.accounts,
        previewRows,
      };
    }, repayPreviewUi.rows);
    evidence.repayment.submit = submitRepay;
    results.push({
      test: "D_repayment_submit_matches_preview",
      ok: rowsMatch(repayPreviewUi.rows, submitRepay.accounts),
      submitRepay,
    });

    // Test E — missing account validation
    const failResult = await page.evaluate(async (facName) => {
      try {
        await frappe.call({
          method:
            "erpnext_extensions.facility_management.doctype.facility.facility.preview_receipt_journal_entry",
          args: { name: facName },
        });
        return { ok: false, error: null };
      } catch (e) {
        return { ok: true, error: String(e.message || e) };
      }
    }, failPrep.facility);
    results.push({
      test: "E_missing_account_preview_error",
      ok: failResult.ok && !!failResult.error,
      failResult,
    });
  } finally {
    await browser.close();
  }

  const all_ok = results.every((r) => r.ok);
  console.log(JSON.stringify({ all_ok, results, evidence }, null, 2));
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
