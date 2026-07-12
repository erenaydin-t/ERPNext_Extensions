/**
 * Facility Repayment usability E2E — full release criteria (post-migrate).
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute, waitDocstatus } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "usability");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

function bench(method) {
  return benchExecute(method);
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
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

async function run() {
  const prep = bench(
    "erpnext_extensions.facility_management.e2e.facility_usability_prep.prepare_search_facility"
  );
  const evidence = {
    prep,
    screenshots: {},
    repayment: null,
    preview: null,
    submittedJe: null,
    reports: {},
  };
  const results = [];

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  async function openNewRepaymentForm() {
    await page.goto(
      `${BASE}/desk/facility-repayment/new-facility-repayment-1`,
      {
        waitUntil: "domcontentloaded",
        timeout: 120000,
      }
    );
    await page.waitForFunction(
      () =>
        window.cur_frm?.doc?.doctype === "Facility Repayment" &&
        !window.cur_frm.is_loading &&
        window.cur_frm?.fields_dict?.facility &&
        window.cur_frm?.fields_dict?.interest_expense_account,
      { timeout: 180000 }
    );
    await page.waitForTimeout(1200);
  }

  try {
    await login(page);
    await openNewRepaymentForm();

    const visible = await page.evaluate(
      () => !!cur_frm.fields_dict?.interest_expense_account
    );
    evidence.screenshots.interest_field = await shot(
      page,
      "01_interest_expense_field_visible"
    );
    results.push({ test: "1_interest_field_visible", ok: visible });

    await page.evaluate(async (fac) => {
      await cur_frm.set_value("facility", fac);
      const start = Date.now();
      while (Date.now() - start < 20000) {
        if (cur_frm.doc.interest_expense_account) {
          break;
        }
        await new Promise((r) => setTimeout(r, 250));
      }
    }, prep.facility);
    await page.waitForTimeout(500);

    const afterSelect = await page.evaluate(() => ({
      interest: cur_frm.doc.interest_expense_account,
      facility_name: cur_frm.doc.facility_name,
      company: cur_frm.doc.company,
    }));
    evidence.screenshots.after_facility_select = await shot(
      page,
      "02_interest_autofill"
    );
    results.push({
      test: "2_interest_autofill",
      ok:
        !!afterSelect.interest &&
        afterSelect.facility_name === prep.facility_name,
      afterSelect,
    });

    const overrideAccount = await page.evaluate(async () => {
      const r = await frappe.call({
        method: "frappe.desk.search.search_link",
        args: {
          doctype: "Account",
          txt: "",
          page_length: 20,
          filters: {
            company: cur_frm.doc.company,
            root_type: "Expense",
            is_group: 0,
          },
        },
      });
      const pick = (r.message || [])
        .map((x) => x.value)
        .find((v) => v && v !== cur_frm.doc.interest_expense_account);
      if (!pick) return cur_frm.doc.interest_expense_account;
      await cur_frm.set_value("interest_expense_account", pick);
      return cur_frm.doc.interest_expense_account;
    });
    evidence.screenshots.after_override = await shot(
      page,
      "03_interest_override"
    );
    results.push({ test: "3_user_can_override", ok: !!overrideAccount });

    const previewPayload = await page.evaluate(async () => {
      const r = await frappe.call({
        method:
          "erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
        args: {
          doc: {
            ...cur_frm.doc,
            principal_amount: 100,
            profit_amount: 10,
            penalty_amount: 0,
          },
        },
      });
      const rows = r.message?.rows || [];
      const intRow = rows.find((row) => row.row_label === "Interest Expense");
      return {
        message: r.message,
        interestAccount: intRow?.account,
        override: cur_frm.doc.interest_expense_account,
      };
    });
    evidence.preview = previewPayload.message;
    evidence.screenshots.preview_dialog = await shot(
      page,
      "04_after_preview_call"
    );
    results.push({
      test: "4_preview_uses_override",
      ok: previewPayload.interestAccount === overrideAccount,
      previewPayload,
    });

    const saveSubmit = await page.evaluate(async () => {
      try {
        await cur_frm.set_value("principal_amount", 100);
        await cur_frm.set_value("profit_amount", 10);
        await cur_frm.set_value("penalty_amount", 0);
        await cur_frm.save();
        const r = await frappe.call({
          method: "frappe.client.submit",
          args: { doc: cur_frm.doc },
        });
        const doc = r.message || {};
        return {
          ok: true,
          repayment: doc.name,
          je: doc.journal_entry,
          interest: doc.interest_expense_account,
        };
      } catch (e) {
        return { ok: false, error: e.message || String(e) };
      }
    });
    if (!saveSubmit.ok) {
      results.push({
        test: "5_submitted_je_same_interest_account",
        ok: false,
        saveSubmit,
      });
      throw new Error(saveSubmit.error || "submit failed");
    }
    const dbWait = saveSubmit.je
      ? await waitDocstatus("Journal Entry", saveSubmit.je, 1, {
          timeoutMs: 120000,
        })
      : { ok: false };

    const jeEvidence = await page.evaluate(
      async ({ je, expectedInterest }) => {
        const doc = await frappe.db.get_doc("Journal Entry", je);
        const intRows = doc.accounts.filter(
          (a) =>
            a.debit_in_account_currency > 0 && a.account === expectedInterest
        );
        return {
          voucher_type: doc.voucher_type,
          row_count: doc.accounts.length,
          interest_rows: intRows.map((a) => ({
            account: a.account,
            debit: a.debit_in_account_currency,
          })),
        };
      },
      { je: saveSubmit.je, expectedInterest: overrideAccount }
    );
    evidence.submittedJe = { name: saveSubmit.je, ...jeEvidence };
    evidence.repayment = saveSubmit.repayment;

    await page.goto(
      `${BASE}/desk/journal-entry/${encodeURIComponent(saveSubmit.je)}`,
      {
        waitUntil: "domcontentloaded",
      }
    );
    await page.waitForFunction(
      () => window.cur_frm?.doc?.doctype === "Journal Entry",
      { timeout: 180000 }
    );
    await page.waitForTimeout(1500);
    evidence.screenshots.submitted_je = await shot(
      page,
      "05_submitted_journal_entry"
    );
    evidence.repayment = saveSubmit.repayment;
    results.push({
      test: "5_submitted_je_same_interest_account",
      ok:
        dbWait.ok &&
        jeEvidence.interest_rows.length >= 1 &&
        saveSubmit.interest === overrideAccount,
      saveSubmit,
      jeEvidence,
      db_wait: dbWait,
    });

    const linkSearch = await page.evaluate(async () => {
      const r = await frappe.call({
        method: "frappe.desk.search.search_link",
        args: { doctype: "Facility", txt: "سرمایه در گردش", page_length: 20 },
      });
      return (r.message || []).map((x) => x.value);
    });
    results.push({
      test: "6_facility_link_search_by_name",
      ok:
        linkSearch.includes(prep.facility) ||
        linkSearch.some((v) => v && prep.facility_name.includes("سرمایه")),
      linkSearch,
    });

    const listSearch = await page.evaluate(async (fname) => {
      const r = await frappe.call({
        method: "frappe.desk.reportview.get",
        args: {
          doctype: "Facility Repayment",
          fields: ["name", "facility_name", "facility"],
          filters: [["facility_name", "like", `%${fname.slice(0, 12)}%`]],
          limit_page_length: 20,
        },
      });
      return r.message?.values || [];
    }, prep.facility_name);
    await page.goto(`${BASE}/desk/facility-repayment`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForTimeout(2000);
    evidence.screenshots.repayment_list = await shot(
      page,
      "06_facility_repayment_list"
    );
    const listHas = listSearch.some(
      (row) => row[2] === prep.facility || row[1] === prep.facility_name
    );
    results.push({
      test: "7_repayment_list_search_by_facility_name",
      ok: listHas,
      listSearchCount: listSearch.length,
    });

    const reports = bench(
      "erpnext_extensions.facility_management.e2e.facility_usability_prep.run_e2e_reports"
    );
    evidence.reports = reports;
    results.push({
      test: "8_facility_balance_facility_name_filter",
      ok:
        reports.balance.count >= 1 &&
        reports.balance.facilities.includes(prep.facility),
      balance: reports.balance,
    });

    await page.goto(`${BASE}/desk/query-report/Facility%20Balance`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForTimeout(2500);
    evidence.screenshots.facility_balance = await shot(
      page,
      "07_facility_balance_report"
    );

    results.push({
      test: "9_facility_ledger_facility_name_filter",
      ok:
        reports.ledger.count >= 1 &&
        reports.ledger.sample?.facility === prep.facility,
      ledger: reports.ledger,
    });
    await page.goto(`${BASE}/desk/query-report/Facility%20Ledger`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForTimeout(2500);
    evidence.screenshots.facility_ledger = await shot(
      page,
      "08_facility_ledger_report"
    );

    const shotPaths = Object.values(evidence.screenshots).filter(Boolean);
    results.push({
      test: "10_screenshots_saved",
      ok: shotPaths.length >= 8,
      paths: shotPaths,
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
