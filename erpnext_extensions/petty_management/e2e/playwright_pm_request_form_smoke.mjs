/**
 * PM Request UI smoke — intro dedupe, View PE, sections expanded, collapsible.
 * UI-primary; prep document existence checked via shared benchExecute.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  benchExecute,
  getDocumentState,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_form_smoke");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

function bench(method) {
  return benchExecute(method);
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

async function openPmRequest(page, name) {
  await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_frm?.doc?.doctype === "PM Request" &&
      !window.cur_frm.is_loading,
    { timeout: 180000 }
  );
  await page.waitForTimeout(1500);
}

async function countFormMessagesContaining(page, text) {
  return page.evaluate((needle) => {
    const blocks = document.querySelectorAll(
      ".form-message-container .form-message, .form-message"
    );
    let count = 0;
    blocks.forEach((el) => {
      const t = (el.textContent || "").replace(/\s+/g, " ").trim();
      if (t.includes(needle)) {
        count += 1;
      }
    });
    return count;
  }, text);
}

async function sectionExpandedOnLoad(page, fieldname) {
  return page.evaluate((fn) => {
    const section = document.querySelector(
      `.form-section[data-fieldname="${fn}"]`
    );
    if (!section || section.classList.contains("hide-control")) {
      return null;
    }
    const body = section.querySelector(".section-body");
    return body && !body.classList.contains("hide");
  }, fieldname);
}

async function viewPaymentEntriesActionVisible(page, pmRequest) {
  await page.evaluate(() => {
    window.cur_frm?.trigger("setup_pm_request_toolbar");
  });
  await page.waitForTimeout(2500);
  const canView = await page.evaluate(async (req) => {
    const r = await frappe.call({
      method:
        "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_action_flags",
      args: { pm_request: req },
    });
    return Boolean(r.message?.can_view_payment_entries);
  }, pmRequest);
  if (!canView) {
    return false;
  }
  const inDom = await page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button")).some((el) =>
      /View Payment Entries/i.test((el.textContent || "").trim())
    )
  );
  if (!inDom) {
    return false;
  }
  const actionsBtn = page
    .locator(".actions-btn-group .btn")
    .filter({ hasText: /^Actions$/i })
    .first();
  if (await actionsBtn.count()) {
    await actionsBtn.click();
    const visible =
      (await page
        .locator(".actions-btn-group .dropdown-menu a.dropdown-item")
        .filter({ hasText: /View Payment Entries/i })
        .count()) > 0;
    await page.keyboard.press("Escape");
    return visible;
  }
  return inDom;
}

function sectionState(page, sectionFieldname) {
  return page.evaluate((fn) => {
    const section = document.querySelector(
      `.form-section[data-fieldname="${fn}"]`
    );
    if (!section || section.classList.contains("hide-control")) {
      return { exists: false };
    }
    const head = section.querySelector(".section-head");
    const body = section.querySelector(".section-body");
    return {
      exists: true,
      collapsible: head?.classList.contains("collapsible"),
      hasCaret: !!head?.querySelector(".collapse-indicator"),
      collapsed: body?.classList.contains("hide"),
    };
  }, sectionFieldname);
}

async function toggleSectionCollapse(page, sectionFieldname) {
  await page
    .locator(
      `.form-section[data-fieldname="${sectionFieldname}"] .section-head.collapsible`
    )
    .click();
}

async function testSectionToggle(page, sectionFieldname, innerFieldname) {
  const state = await sectionState(page, sectionFieldname);
  if (!state.exists) {
    return { section: sectionFieldname, skipped: true };
  }
  if (!state.collapsible) {
    return {
      section: sectionFieldname,
      pass: false,
      reason: "not collapsible",
    };
  }
  await toggleSectionCollapse(page, sectionFieldname);
  await page.waitForFunction(
    (fn) =>
      document
        .querySelector(`.form-section[data-fieldname="${fn}"] .section-body`)
        ?.classList.contains("hide"),
    sectionFieldname,
    { timeout: 15000 }
  );
  await toggleSectionCollapse(page, sectionFieldname);
  await page.waitForFunction(
    ({ sectionFn, fieldFn }) => {
      const body = document.querySelector(
        `.form-section[data-fieldname="${sectionFn}"] .section-body`
      );
      return (
        body &&
        !body.classList.contains("hide") &&
        !!document.querySelector(`[data-fieldname="${fieldFn}"]`)
      );
    },
    { sectionFn: sectionFieldname, fieldFn: innerFieldname },
    { timeout: 15000 }
  );
  return { section: sectionFieldname, pass: true };
}

async function run() {
  const funded = bench(
    "erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_partial_funded_for_close_ui"
  );
  const draft = bench(
    "erpnext_extensions.petty_management.e2e.pm_request_ui_prep.get_draft_pm_request"
  );

  const consoleErrors = [];
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(`pageerror: ${err}`));

  await login(
    page,
    process.env.FRAPPE_E2E_USER || "Administrator",
    process.env.FRAPPE_E2E_PASSWORD || "admin"
  );

  const results = {};

  await openPmRequest(page, draft.pm_request);
  results.draft_intro_count = await countFormMessagesContaining(
    page,
    "Submit the PM Request first"
  );
  results.draft_intro_ok = results.draft_intro_count === 1;

  await openPmRequest(page, funded.pm_request);
  results.funded_intro_reject_count = await countFormMessagesContaining(
    page,
    "Reject is not allowed while submitted Payment Entries exist"
  );
  results.funded_intro_reject_ok = results.funded_intro_reject_count === 1;

  results.sections_expanded_on_load = {
    request: await sectionExpandedOnLoad(page, "section_main"),
    amounts: await sectionExpandedOnLoad(page, "section_amounts"),
    payment_entries: await sectionExpandedOnLoad(
      page,
      "section_payment_entries"
    ),
    details: await sectionExpandedOnLoad(page, "section_details"),
  };
  results.pe_table_visible_default = await page.evaluate(() => {
    const table = document.querySelector("#pm-request-pe-list table");
    if (!table) {
      return false;
    }
    return table.offsetParent !== null;
  });

  results.view_pe_before_close = await viewPaymentEntriesActionVisible(
    page,
    funded.pm_request
  ).catch(() => false);

  const sectionTests = [];
  sectionTests.push(
    await testSectionToggle(
      page,
      "section_payment_entries",
      "payment_entries_html"
    )
  );
  results.section_toggle_payment_entries = sectionTests[0];

  fs.mkdirSync(SCREEN, { recursive: true });
  const screenshot = path.join(SCREEN, "ui_uat_after.png");
  await page.screenshot({ path: screenshot, fullPage: true });

  const benign = consoleErrors.filter(
    (e) =>
      !/favicon|Failed to load resource: the server responded with a status of (404|400)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
        e
      )
  );

  const fundedDb = getDocumentState("PM Request", funded.pm_request, [
    "name",
    "docstatus",
  ]);
  const draftDb = getDocumentState("PM Request", draft.pm_request, [
    "name",
    "docstatus",
  ]);
  results.db_prep_documents_exist = fundedDb.exists && draftDb.exists;

  const pass =
    results.db_prep_documents_exist &&
    results.draft_intro_ok &&
    results.funded_intro_reject_ok &&
    results.view_pe_before_close &&
    results.pe_table_visible_default &&
    results.sections_expanded_on_load.request &&
    results.sections_expanded_on_load.amounts &&
    results.sections_expanded_on_load.payment_entries &&
    results.sections_expanded_on_load.details &&
    (sectionTests[0].skipped || sectionTests[0].pass) &&
    benign.length === 0;

  console.log(
    JSON.stringify(
      {
        pass,
        funded: funded.pm_request,
        draft: draft.pm_request,
        results,
        screenshot,
      },
      null,
      2
    )
  );
  await browser.close();
  process.exit(pass ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
