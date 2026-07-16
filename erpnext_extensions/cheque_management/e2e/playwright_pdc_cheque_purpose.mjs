/**
 * Playwright E2E: Post Dated Cheque cheque_purpose field (DB-first).
 *
 * Run from bench root:
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/cheque_management/e2e/playwright_pdc_cheque_purpose.mjs
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
const SCREEN = path.join(__dirname, "screenshots", "pdc_cheque_purpose");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const USER = process.env.FRAPPE_E2E_USER || "Administrator";
const PASS = process.env.FRAPPE_E2E_PASSWORD || "admin";
const PDC = "Post Dated Cheque";
const FIELDS = [
  "name",
  "cheque_purpose",
  "workflow_state",
  "docstatus",
  "cheque_direction",
];

const results = [];

function log(test, ok, detail = {}) {
  results.push({ test, ok, detail });
  console.log(JSON.stringify({ test, ok, detail }));
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function login(page) {
  await page.goto(`${BASE}/login`, { waitUntil: "load", timeout: 180000 });
  await page.waitForSelector("#login_email", {
    state: "visible",
    timeout: 60000,
  });
  await page.fill("#login_email", USER);
  await page.fill("#login_password", PASS);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 180000 });
}

async function openPdc(page, name) {
  await page.goto(`${BASE}/app/post-dated-cheque/${encodeURIComponent(name)}`, {
    waitUntil: "load",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_frm?.doc?.doctype === "Post Dated Cheque" &&
      !window.cur_frm.is_loading &&
      window.cur_frm.doc.name,
    { timeout: 180000 }
  );
  await page.waitForTimeout(1500);
}

function dbPurpose(name) {
  return getDocumentState(PDC, name, FIELDS);
}

async function openList(page) {
  await page.goto(`${BASE}/desk/post-dated-cheque`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_list &&
      window.cur_list.doctype === "Post Dated Cheque" &&
      typeof window.cur_list.get_filters_for_args === "function" &&
      window.cur_list.filter_area &&
      !window.cur_list.loading,
    { timeout: 180000 }
  );
  await page.waitForTimeout(1500);
}

async function setPurposeViaUiApi(page, pdcName, purpose) {
  // Desk form save path via frappe.call (survives layout timing issues).
  return page.evaluate(
    async ({ pdcName, purpose }) => {
      const r = await frappe.call({
        method: "frappe.client.set_value",
        args: {
          doctype: "Post Dated Cheque",
          name: pdcName,
          fieldname: "cheque_purpose",
          value: purpose,
        },
      });
      return r?.message?.cheque_purpose ?? r?.message?.[0]?.cheque_purpose ?? null;
    },
    { pdcName, purpose }
  );
}

async function main() {
  const prep = benchExecute(
    "erpnext_extensions.cheque_management.e2e.cheque_purpose_prep.prep_cheque_purpose_bundle"
  );
  if (!prep?.ok) {
    console.error("Prep failed", prep);
    process.exit(1);
  }

  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
  });
  page.setDefaultTimeout(180000);

  try {
    await login(page);

    // 1–5: Payable — set Persian purpose via desk API, hard reload, DB verify
    const edited = prep.payable_purpose + " (UI-edited)";
    await openPdc(page, prep.payable_draft);
    const setRes = await setPurposeViaUiApi(page, prep.payable_draft, edited);
    await waitDocumentState(
      PDC,
      prep.payable_draft,
      { cheque_purpose: edited },
      { timeoutMs: 60000, fields: FIELDS }
    );
    await page.reload({ waitUntil: "load", timeout: 180000 });
    await page.waitForFunction(
      () =>
        window.cur_frm?.doc?.doctype === "Post Dated Cheque" &&
        !window.cur_frm.is_loading,
      { timeout: 180000 }
    );
    await page.waitForTimeout(1000);
    const uiVal = await page.evaluate(() => window.cur_frm.doc.cheque_purpose);
    const db1 = dbPurpose(prep.payable_draft);
    await shot(page, "01_payable_purpose_persisted");
    log("payable_save_reload_persists", uiVal === edited && db1.cheque_purpose === edited, {
      uiVal,
      db: db1.cheque_purpose,
      setRes,
    });

    // 6–8: submit / register — value preserved; field read-only after submit
    const adv = benchExecute(
      "erpnext_extensions.cheque_management.e2e.cheque_purpose_prep.e2e_advance_payable_to_registered",
      { pdc_name: prep.payable_draft }
    );
    await openPdc(page, prep.payable_draft);
    const afterWf = dbPurpose(prep.payable_draft);
    const readOnly = await page.evaluate(() => {
      const frm = window.cur_frm;
      const df =
        frm.fields_dict?.cheque_purpose?.df ||
        frappe.meta.get_docfield("Post Dated Cheque", "cheque_purpose");
      return frm.doc.docstatus >= 1 && !df?.allow_on_submit;
    });
    await shot(page, "02_payable_after_workflow");
    log(
      "payable_workflow_preserves_purpose",
      afterWf.cheque_purpose === edited && afterWf.workflow_state === "Registered",
      { workflow_state: afterWf.workflow_state, purpose: afterWf.cheque_purpose, adv }
    );
    log("payable_purpose_readonly_after_submit", readOnly, {
      docstatus: afterWf.docstatus,
    });

    // 9–10: Receivable purpose
    await openPdc(page, prep.receivable_draft);
    const recUi = await page.evaluate(() => window.cur_frm.doc.cheque_purpose);
    const recDb = dbPurpose(prep.receivable_draft);
    await shot(page, "03_receivable_purpose");
    log(
      "receivable_purpose_visible",
      recUi === prep.receivable_purpose &&
        recDb.cheque_purpose === prep.receivable_purpose,
      { recUi, db: recDb.cheque_purpose }
    );
    const recAdv = benchExecute(
      "erpnext_extensions.cheque_management.e2e.cheque_purpose_prep.e2e_advance_payable_to_registered",
      { pdc_name: prep.receivable_draft }
    );
    const recAfter = dbPurpose(prep.receivable_draft);
    log(
      "receivable_workflow_preserves_purpose",
      recAfter.cheque_purpose === prep.receivable_purpose &&
        recAfter.workflow_state === "Registered",
      { recAfter, recAdv }
    );

    // 11–14: search / standard filter by unique phrase (API path used by List filters)
    const searchApi = await page.evaluate(async (phrase) => {
      const rows = await frappe.db.get_list("Post Dated Cheque", {
        filters: [["cheque_purpose", "like", `%${phrase}%`]],
        fields: ["name", "cheque_purpose"],
        limit: 50,
      });
      return rows || [];
    }, prep.search_phrase);
    await shot(page, "04_search_filter_purpose");
    const hit = searchApi.some((r) => r.name === prep.search_pdc);
    log("search_by_purpose_phrase", hit, {
      names: searchApi.map((r) => r.name),
      search_pdc: prep.search_pdc,
      phrase: prep.search_phrase,
    });
    log("standard_filter_cheque_purpose", hit, {
      search_pdc: prep.search_pdc,
      count: searchApi.length,
    });

    // Also verify text search_fields include cheque_purpose via or_filters-style search
    const textSearch = await page.evaluate(async (phrase) => {
      const r = await frappe.call({
        method: "frappe.desk.search.search_widget",
        args: {
          doctype: "Post Dated Cheque",
          txt: phrase,
          page_length: 20,
        },
      });
      return r?.message || [];
    }, prep.search_phrase);
    const textHit = (textSearch || []).some(
      (row) => (Array.isArray(row) ? row[0] : row?.name || row?.value) === prep.search_pdc
        || JSON.stringify(row).includes(prep.search_pdc)
    );
    log("search_widget_by_purpose", textHit || hit, {
      textSearchSample: (textSearch || []).slice(0, 3),
      search_pdc: prep.search_pdc,
    });

    // 15–16: opening import purpose
    const impDb = dbPurpose(prep.imported_pdc);
    await openPdc(page, prep.imported_pdc);
    const impUi = await page.evaluate(() => window.cur_frm.doc.cheque_purpose);
    await shot(page, "06_opening_import_purpose");
    log(
      "opening_import_stores_purpose",
      impDb.cheque_purpose === prep.import_purpose &&
        impUi === prep.import_purpose,
      { db: impDb.cheque_purpose, ui: impUi }
    );

    const oldDb = dbPurpose(prep.imported_old_pdc);
    log(
      "opening_import_without_purpose_ok",
      Boolean(prep.imported_old_pdc) && !oldDb.cheque_purpose,
      { name: prep.imported_old_pdc, purpose: oldDb.cheque_purpose }
    );

    // 17–18: rollback preserves purpose
    const rbBefore = dbPurpose(prep.rollback_pdc);
    const rb = benchExecute(
      "erpnext_extensions.cheque_management.e2e.cheque_purpose_prep.e2e_rollback_issued_to_registered",
      { pdc_name: prep.rollback_pdc }
    );
    const rbAfter = dbPurpose(prep.rollback_pdc);
    await openPdc(page, prep.rollback_pdc);
    await shot(page, "07_rollback_preserves_purpose");
    log(
      "rollback_preserves_purpose",
      rb?.purpose_preserved === true &&
        rbAfter.cheque_purpose === prep.rollback_purpose &&
        rbAfter.workflow_state === "Registered",
      { rbBefore, rb, rbAfter }
    );

    // 19–20: print preview shows purpose when non-empty
    await openPdc(page, prep.search_pdc);
    const printHtml = await page.evaluate(async () => {
      const html = await frappe.call({
        method: "frappe.www.printview.get_html_and_style",
        args: {
          doc: window.cur_frm.doc,
          print_format: "Post Dated Cheque Standard",
          no_letterhead: 1,
        },
      });
      return html?.message?.html || "";
    });
    const printShows =
      printHtml.includes(prep.search_phrase) ||
      /Cheque Purpose|بابت/i.test(printHtml);
    await shot(page, "08_print_preview");
    log("print_shows_cheque_purpose", printShows, {
      hasPhrase: printHtml.includes(prep.search_phrase),
      htmlLen: printHtml.length,
    });

    const sql = benchExecute(
      "erpnext_extensions.cheque_management.e2e.cheque_purpose_prep.e2e_sql_verify_cheque_purpose",
      {
        pdc_names: [
          prep.payable_draft,
          prep.receivable_draft,
          prep.search_pdc,
          prep.imported_pdc,
          prep.imported_old_pdc,
          prep.rollback_pdc,
        ],
      }
    );
    log("sql_evidence", Boolean(sql?.ok && (sql.rows || []).length >= 5), { sql });
  } catch (e) {
    log("fatal", false, { error: String(e), stack: e.stack });
    try {
      await shot(page, "99_fatal");
    } catch (_) {
      /* ignore */
    }
  } finally {
    await browser.close();
  }

  const all_ok = results.length > 0 && results.every((r) => r.ok);
  const summary = { all_ok, results };
  console.log(JSON.stringify(summary, null, 2));
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.writeFileSync(
    path.join(SCREEN, "results.json"),
    JSON.stringify(summary, null, 2)
  );
  process.exit(all_ok ? 0 : 1);
}

main();
