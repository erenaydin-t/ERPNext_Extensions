/**
 * Playwright E2E: Return from Bank workflow action + returned_from_bank_date + Cheque Purpose visibility.
 *
 * Run from bench root (requires Playwright install under /tmp/e2e-npm):
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/cheque_management/e2e/playwright_pdc_return_from_bank.mjs
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  benchExecute,
  waitDocumentState,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pdc_return_from_bank");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const USER = process.env.FRAPPE_E2E_USER || "Administrator";
const PASS = process.env.FRAPPE_E2E_PASSWORD || "admin";
const PDC = "Post Dated Cheque";
const FIELDS = [
  "workflow_state",
  "cheque_status",
  "is_at_bank",
  "returned_from_bank_date",
  "sent_to_bank_date",
  "bank_account",
  "cheque_purpose",
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
      window.cur_frm.doc.name &&
      Object.keys(window.cur_frm.fields_dict || {}).length > 0,
    { timeout: 180000 }
  );
  await page.waitForTimeout(800);
}

async function collectWorkflowActionLabels(page) {
  await page.evaluate(() => {
    const btn = Array.from(
      document.querySelectorAll(
        ".actions-btn-group .btn, .page-actions .btn, button"
      )
    ).find((b) => (b.textContent || "").trim() === "Actions");
    if (btn) btn.click();
  });
  await page.waitForTimeout(400);
  return page.evaluate(() => {
    const labels = new Set();
    for (const el of document.querySelectorAll(
      ".actions-btn-group .dropdown-menu a, .actions-btn-group .btn, a.grey-link, .workflow-button, .page-actions .btn"
    )) {
      const t = (el.textContent || "").trim();
      if (t) labels.add(t);
    }
    return Array.from(labels);
  });
}

async function main() {
  const prep = await benchExecute(
    "erpnext_extensions.cheque_management.e2e.return_from_bank_prep.prep_return_from_bank_bundle"
  );
  const pdcName = prep.pdc_name;
  const browser = await chromium.launch({
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--lang=en-US"],
  });
  // en-US avoids desk AltShortcutGroup RangeError that aborts form layout build.
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  try {
    await login(page);
    await openPdc(page, pdcName);

    const fieldProbe = await page.evaluate(() => {
      const frm = window.cur_frm;
      const purposeCtrl = frm?.fields_dict?.cheque_purpose;
      const returnCtrl = frm?.fields_dict?.returned_from_bank_date;
      const purposeDf =
        purposeCtrl?.df ||
        frappe.meta.get_docfield("Post Dated Cheque", "cheque_purpose");
      return {
        purpose_in_fields_dict: !!purposeCtrl,
        purpose_permlevel: Number(purposeDf?.permlevel || 0),
        purpose_hidden: Number(purposeDf?.hidden || 0),
        purpose_wrapper_visible: purposeCtrl?.$wrapper
          ? purposeCtrl.$wrapper.is(":visible")
          : false,
        purpose_value: frm?.doc?.cheque_purpose || null,
        returned_in_fields_dict: !!returnCtrl,
        returned_wrapper_visible: returnCtrl?.$wrapper
          ? returnCtrl.$wrapper.is(":visible")
          : false,
        workflow_state: frm?.doc?.workflow_state || null,
        fields_dict_count: Object.keys(frm?.fields_dict || {}).length,
      };
    });
    // Expand Cheque Details if collapsed so purpose control can become visible
    await page.evaluate(() => {
      const section = window.cur_frm?.fields_dict?.section_break_cheque;
      if (section?.collapse && section.is_collapsed?.()) {
        section.collapse(false);
      }
    });
    await page.waitForTimeout(300);
    const purposeVisible = await page.evaluate(() => {
      const ctrl = window.cur_frm?.fields_dict?.cheque_purpose;
      if (!ctrl?.$wrapper) return false;
      return ctrl.$wrapper.is(":visible");
    });

    log(
      "cheque_purpose_visible",
      fieldProbe.purpose_in_fields_dict &&
        fieldProbe.purpose_permlevel === 0 &&
        fieldProbe.purpose_hidden === 0 &&
        (purposeVisible || !!fieldProbe.purpose_value),
      { ...fieldProbe, purposeVisible }
    );
    log(
      "returned_from_bank_date_on_form",
      fieldProbe.returned_in_fields_dict,
      fieldProbe
    );
    await shot(page, "01_stb_form");

    const actions = await collectWorkflowActionLabels(page);
    const hasReturn = actions.some((a) => a.includes("Return from Bank"));
    const transitions = await page.evaluate(async () => {
      const rows = await frappe.xcall("frappe.model.workflow.get_transitions", {
        doc: window.cur_frm.doc,
      });
      return (rows || []).map((r) => r.action);
    });
    log("return_from_bank_action_visible", hasReturn || transitions.includes("Return from Bank"), {
      actions: actions.slice(0, 40),
      transitions,
    });

    // Enter return date on form (allow_on_submit)
    await page.evaluate((today) => {
      window.cur_frm.set_value("returned_from_bank_date", today);
    }, prep.today);
    await page.waitForTimeout(400);
    await page.evaluate(async () => {
      if (window.cur_frm.is_dirty()) {
        await window.cur_frm.save();
      }
    });
    const dateWait = await waitDocumentState(
      PDC,
      pdcName,
      { returned_from_bank_date: prep.today },
      { timeoutMs: 60000, fields: FIELDS }
    );
    log("returned_from_bank_date_saved", dateWait.ok, dateWait.state || dateWait);
    await openPdc(page, pdcName);

    // Click workflow action when visible; otherwise apply_workflow (same server path)
    const clicked = await page.evaluate(() => {
      const btn = Array.from(
        document.querySelectorAll(
          ".actions-btn-group .btn, .page-actions .btn, button"
        )
      ).find((b) => (b.textContent || "").trim() === "Actions");
      if (btn) btn.click();
      const links = Array.from(
        document.querySelectorAll(
          ".actions-btn-group .dropdown-menu a, a.grey-link, .btn"
        )
      );
      const el = links.find((a) =>
        (a.textContent || "").includes("Return from Bank")
      );
      if (el) {
        el.click();
        return true;
      }
      return false;
    });
    if (!clicked) {
      await page.evaluate(async () => {
        await frappe.xcall("frappe.model.workflow.apply_workflow", {
          doc: window.cur_frm.doc,
          action: "Return from Bank",
        });
      });
    }
    await page.waitForTimeout(1500);
    try {
      await page.evaluate(async () => {
        if (window.cur_frm) await window.cur_frm.reload_doc();
      });
    } catch {
      await openPdc(page, pdcName);
    }

    const stWait = await waitDocumentState(
      PDC,
      pdcName,
      { workflow_state: "Registered" },
      { timeoutMs: 60000, fields: FIELDS }
    );
    const st = stWait.state || {};
    log("workflow_registered_after_return", stWait.ok, st);
    log("is_at_bank_cleared", Number(st.is_at_bank || 0) === 0, st);
    log(
      "cheque_status_in_hand",
      (st.cheque_status || "") === "In Hand" ||
        String(st.cheque_status || "")
          .toLowerCase()
          .includes("hand"),
      st
    );
    await shot(page, "02_after_return");

    const cycle = await benchExecute(
      "erpnext_extensions.cheque_management.e2e.return_from_bank_prep.e2e_resend_and_return_cycle",
      { pdc_name: pdcName }
    );
    log(
      "resend_return_cycle",
      !!cycle?.ok &&
        Number(cycle?.send_jes || 0) >= 2 &&
        Number(cycle?.return_jes || 0) >= 2,
      cycle
    );
  } finally {
    await browser.close();
  }

  const failed = results.filter((r) => !r.ok);
  console.log(
    JSON.stringify({
      summary: {
        pass: results.length - failed.length,
        fail: failed.length,
        failed,
      },
    })
  );
  process.exit(failed.length ? 1 : 0);
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
