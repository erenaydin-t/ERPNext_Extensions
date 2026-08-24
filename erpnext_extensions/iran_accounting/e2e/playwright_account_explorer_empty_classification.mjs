#!/usr/bin/env node
/**
 * Account Explorer v4.6.2 — empty classification exclusion (Playwright scenarios 1–6).
 */
import { chromium } from "./playwright/node_modules/playwright/index.mjs";
import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";
const SITE = process.env.FRAPPE_SITE || "development.localhost";
const BASE = process.env.AE_BASE_URL || "http://development.localhost:8000";
const USER = process.env.AE_USER || "Administrator";
const PASS = process.env.AE_PASS || "admin";
const OUT = path.resolve(__dirname, "screenshots/account-explorer-empty-classification");
const PREP_METHOD =
  "erpnext_extensions.iran_accounting.e2e.account_explorer_empty_classification_prep.prepare_empty_classification_e2e";

const checks = [];
const passCheck = (name, detail = null) => checks.push({ name, ok: true, detail });
const failCheck = (name, err) => checks.push({ name, ok: false, err: String(err) });

function benchExecute(method, kwargs = null) {
  let cmd = `cd ${BENCH} && bench --site ${SITE} execute ${method}`;
  if (kwargs != null) {
    cmd += ` --kwargs '${JSON.stringify(kwargs).replace(/'/g, `'\\''`)}'`;
  }
  const out = execSync(cmd, { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 });
  const lines = out.trim().split("\n").filter(Boolean);
  const last = lines[lines.length - 1];
  try {
    return JSON.parse(last);
  } catch {
    throw new Error(`bench execute ${method} did not return JSON. Last: ${last}\n${out.slice(-1500)}`);
  }
}

function benchRunModule(module) {
  const cmd = `cd ${BENCH} && bench --site ${SITE} run-tests --module ${module} 2>&1`;
  try {
    const out = execSync(cmd, { encoding: "utf8", maxBuffer: 50 * 1024 * 1024 });
    const failed = /FAILED|ERROR/i.test(out) && !/0 failed/i.test(out);
    return { ok: !failed && /OK|passed/i.test(out), out };
  } catch (e) {
    return { ok: false, out: String(e.stdout || e.message || e) };
  }
}

async function login(page) {
  await page.goto(`${BASE}/login?redirect-to=%2Fapp`);
  await page.fill("#login_email", USER);
  await page.fill("#login_password", PASS);
  await page.click(".btn-login");
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function shot(page, name) {
  fs.mkdirSync(OUT, { recursive: true });
  await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

async function resolveAe(page) {
  await page.waitForFunction(() => {
    const entry = frappe?.pages?.["account-explorer"];
    const ae = entry?.account_explorer || entry?.wrapper?.account_explorer;
    return !!(ae && ae.company_field && document.querySelector(".ae-shell, .ae-toolbar"));
  }, null, { timeout: 90000 });
  await page.evaluate(() => {
    const entry = frappe.pages["account-explorer"];
    const inst = entry?.account_explorer || entry?.wrapper?.account_explorer;
    if (!inst) throw new Error("Account Explorer controller not attached");
    window.cur_ae = inst;
  });
}

async function waitSummaryIdle(page, { timeout = 180000 } = {}) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    const ready = await page.evaluate(() => {
      const ae = window.cur_ae;
      if (!ae) return false;
      const loading = !!ae.store?.get?.("loading")?.summary;
      const bannerHidden =
        ae.$summary_loading?.hasClass?.("visually-hidden") ||
        ae.$summary_loading?.hasClass?.("is-hidden") ||
        !ae.$summary_loading?.is?.(":visible");
      const gridLoading = ae.$grid?.hasClass?.("ae-grid-wrap--loading");
      return !loading && bannerHidden && !gridLoading;
    });
    if (ready) return;
    await page.waitForTimeout(250);
  }
  throw new Error("summary did not become idle");
}

async function setScope(page, prep) {
  await page.evaluate(async (prep) => {
    const ae = window.cur_ae;
    ae.company_field.set_value(prep.company);
    ae.document_scope.company = prep.company;
    ae.fy_field.set_value(prep.fiscal_year);
    ae.document_scope.fiscal_year = prep.fiscal_year;
    if (typeof ae.sync_dates_from_fy === "function") {
      ae.sync_dates_from_fy();
    }
    await new Promise((r) => setTimeout(r, 400));
    ae.document_scope.from_date = prep.from_date;
    ae.document_scope.to_date = prep.to_date;
    if (ae.from_date_field) ae.from_date_field.set_value(prep.from_date);
    if (ae.to_date_field) ae.to_date_field.set_value(prep.to_date);
    ae.document_scope.hide_zero_rows = 0;
  }, prep);
  const apply = page.locator("button.ae-btn-apply, button:has-text('Apply')").first();
  if (await apply.count()) {
    await apply.click();
  } else {
    await page.evaluate(async () => {
      await window.cur_ae.refresh_summary();
    });
  }
  await waitSummaryIdle(page);
}

async function switchAxis(page, axis, dimensionType = null) {
  await page.evaluate(
    async ({ axis, dimensionType }) => {
      const ae = window.cur_ae;
      ae.switch_axis(axis, dimensionType);
      await ae.refresh_summary();
    },
    { axis, dimensionType }
  );
  await waitSummaryIdle(page);
}

async function readState(page) {
  return page.evaluate(() => {
    const ae = window.cur_ae;
    const rows = ae.rows || [];
    const tabs = Array.from(document.querySelectorAll(".ae-nav-tab")).map((el) =>
      (el.textContent || "").trim()
    );
    const bodyText = document.querySelector(".ae-grid-wrap")?.innerText || "";
    return {
      tabs,
      axis: ae.analysis_context?.view_axis,
      rows: rows.map((r) => ({
        row_key: r.row_key,
        party: r.party,
        dimension_value: r.dimension_value,
        display_code: r.display_code,
        display_title: r.display_title,
        is_virtual_group: r.is_virtual_group,
        period_debit: r.period_debit,
        period_credit: r.period_credit,
      })),
      totals: ae.totals || {},
      pagination: ae.pagination || {},
      bodyText,
      loadingHidden:
        ae.$summary_loading?.hasClass?.("visually-hidden") ||
        ae.$summary_loading?.hasClass?.("is-hidden") ||
        !ae.$summary_loading?.is?.(":visible"),
    };
  });
}

function assertNoEmptyLabels(state, label) {
  const badRe = /(Unspecified|Unassigned|Unmapped|__UNSPECIFIED__|__UNMAPPED__)/i;
  if (badRe.test(state.bodyText)) {
    throw new Error(`${label}: empty-classification label still visible`);
  }
  for (const row of state.rows) {
    if (row.is_virtual_group) {
      throw new Error(`${label}: virtual empty row ${row.row_key}`);
    }
    if (badRe.test(String(row.display_code || "")) || badRe.test(String(row.display_title || ""))) {
      throw new Error(`${label}: empty marker on ${row.row_key}`);
    }
  }
}

function assertTotalsMatchVisible(state, label) {
  const sumDebit = state.rows.reduce((a, r) => a + Number(r.period_debit || 0), 0);
  const sumCredit = state.rows.reduce((a, r) => a + Number(r.period_credit || 0), 0);
  const tDebit = Number(state.totals.period_debit || 0);
  const tCredit = Number(state.totals.period_credit || 0);
  const totalRows = Number(state.pagination.total_rows || state.rows.length);
  if (totalRows <= state.rows.length) {
    if (Math.abs(sumDebit - tDebit) > 0.005 || Math.abs(sumCredit - tCredit) > 0.005) {
      throw new Error(
        `${label}: totals!=rows debit ${tDebit}/${sumDebit} credit ${tCredit}/${sumCredit}`
      );
    }
  }
}

async function main() {
  let prep;
  try {
    prep = benchExecute(PREP_METHOD, { company: "_Test Company" });
    passCheck("prep", prep);
  } catch (e) {
    failCheck("prep", e);
    console.log(JSON.stringify({ checks }, null, 2));
    process.exit(1);
  }

  const browser = await chromium.launch({ headless: true });
  const page = await (await browser.newContext({ locale: "en-US" })).newPage();
  page.setDefaultTimeout(180000);

  try {
    await login(page);
    passCheck("login");

    await page.goto(`${BASE}/app/account-explorer`, {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    await page.waitForSelector(".ae-shell, .account-explorer-page", { timeout: 90000 });
    await resolveAe(page);
    await setScope(page, prep);
    let state = await readState(page);
    await shot(page, "01-page-load");
    if (state.tabs.some((t) => /unified parties/i.test(t))) {
      throw new Error("Unified Parties tab still present");
    }
    if (!state.loadingHidden) {
      throw new Error("Loading indicator still visible");
    }
    passCheck("scenario1_page_load_no_unified_tab");

    await switchAxis(page, "party");
    state = await readState(page);
    await shot(page, "02-party-axis");
    assertNoEmptyLabels(state, "party");
    assertTotalsMatchVisible(state, "party");
    passCheck("scenario2_party", {
      rows: state.rows.length,
      hasCustomer: state.rows.some((r) => r.party === prep.customer),
    });

    await switchAxis(page, "dimension", "cost_center");
    state = await readState(page);
    await shot(page, "03-dimension-axis");
    assertNoEmptyLabels(state, "dimension");
    assertTotalsMatchVisible(state, "dimension");
    passCheck("scenario3_dimension");

    await page.evaluate(async (account) => {
      const ae = window.cur_ae;
      ae.document_scope.accounting = ae.document_scope.accounting || {};
      ae.document_scope.accounting.account = account;
      ae.switch_axis("party");
      await ae.refresh_summary();
    }, prep.account);
    await waitSummaryIdle(page);
    state = await readState(page);
    await shot(page, "04-account-filter");
    assertNoEmptyLabels(state, "account-filter");
    assertTotalsMatchVisible(state, "account-filter");
    passCheck("scenario4_account_filter");

    const before = await readState(page);
    await page.evaluate(async () => {
      await window.cur_ae.refresh_summary();
    });
    await waitSummaryIdle(page);
    const after = await readState(page);
    await shot(page, "05-refresh");
    assertNoEmptyLabels(after, "refresh");
    if (
      Math.abs(Number(before.totals.period_debit || 0) - Number(after.totals.period_debit || 0)) > 0.005
    ) {
      throw new Error("Totals changed incorrectly after refresh");
    }
    passCheck("scenario5_refresh_stable");

    const modules = [
      "erpnext_extensions.iran_accounting.tests.test_empty_classification_exclusion",
      "erpnext_extensions.iran_accounting.tests.test_empty_classification_presentation",
      "erpnext_extensions.iran_accounting.tests.test_opening_policy_golden_fixtures",
      "erpnext_extensions.iran_accounting.tests.test_opening_policy_axis_matrix",
      "erpnext_extensions.iran_accounting.tests.test_account_explorer_analytical_filter_parity",
      "erpnext_extensions.iran_accounting.tests.test_account_explorer_voucher_parity",
      "erpnext_extensions.iran_accounting.tests.test_opening_policy_pcv_acb_integration",
      "erpnext_extensions.iran_accounting.tests.test_opening_policy_production_integration",
    ];
    for (const mod of modules) {
      const result = benchRunModule(mod);
      if (!result.ok) {
        failCheck(`scenario6_${mod.split(".").pop()}`, result.out.slice(-2500));
      } else {
        passCheck(`scenario6_${mod.split(".").pop()}`);
      }
    }
  } catch (e) {
    failCheck("runtime", e);
    try {
      await shot(page, "99-error");
    } catch (_) {}
  } finally {
    await browser.close();
  }

  fs.mkdirSync(OUT, { recursive: true });
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify({ checks, prep }, null, 2));
  const failed = checks.filter((c) => !c.ok);
  console.log(JSON.stringify({ ok: failed.length === 0, failed: failed.length, checks }, null, 2));
  process.exit(failed.length ? 1 : 0);
}

main();
