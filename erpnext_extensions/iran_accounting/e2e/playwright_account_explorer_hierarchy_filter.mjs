#!/usr/bin/env node
/**
 * Account Explorer v4.6.3 — hierarchy filter respects presentation level (Playwright).
 *
 * 1) Account Group filter at Group level → exactly one row (code 77), no children
 * 2) Analyze keeps Group row; navigate reveals GL children
 * 3) Same filter at GL level → only GL codes, no SL children
 */
import { chromium } from "./playwright/node_modules/playwright/index.mjs";
import { execSync } from "child_process";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";
const SITE = process.env.FRAPPE_SITE || "restore-espad.localhost";
const BASE = process.env.AE_BASE_URL || "http://restore-espad.localhost:8000";
const USER = process.env.AE_USER || "Administrator";
const PASS = process.env.AE_PASS || "admin";
const OUT = path.resolve(__dirname, "screenshots/account-explorer-hierarchy-filter");
const PREP_METHOD =
  "erpnext_extensions.iran_accounting.e2e.account_explorer_hierarchy_filter_prep.prepare_hierarchy_filter_e2e";

const checks = [];
const passCheck = (name, detail = null) => checks.push({ name, ok: true, detail });
const failCheck = (name, err) =>
  checks.push({
    name,
    ok: false,
    err: err && err.stack ? String(err.stack) : err && err.message ? String(err.message) : JSON.stringify(err, Object.getOwnPropertyNames(err || {})),
  });

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
  const result = await page.evaluate(async (prep) => {
    const ae = window.cur_ae;
    const out = { steps: [] };
    const note = (s) => out.steps.push(s);
    try {
      // Set document_scope first so any control callbacks see company.
      ae.document_scope.company = prep.company;
      // Prefer explicit dates; FY name can fail validation under persian_calendar HTTP path.
      ae.document_scope.fiscal_year = null;
      ae.document_scope.from_date = prep.from_date;
      ae.document_scope.to_date = prep.to_date;
      ae.document_scope.hide_zero_rows = 0;
      note("scope_seeded");

      ae.company_field.$input && ae.company_field.$input.val(prep.company);
      ae.company_field.value = prep.company;
      ae.company_field.set_value(prep.company);
      note("company_control");

      note("fy_skipped");

      if (ae.from_date_field) {
        ae.from_date_field.value = prep.from_date;
        ae.from_date_field.set_value(prep.from_date);
      }
      if (ae.to_date_field) {
        ae.to_date_field.value = prep.to_date;
        ae.to_date_field.set_value(prep.to_date);
      }
      note("dates_control");

      // Re-assert after control side-effects.
      ae.document_scope.company = prep.company;
      ae.document_scope.fiscal_year = null;
      ae.document_scope.from_date = prep.from_date;
      ae.document_scope.to_date = prep.to_date;
      ae.document_scope.hide_zero_rows = 0;
      ae.analysis_context.page = 1;
      note("scope_reassert");

      out.company = ae.document_scope.company;
      out.from_date = ae.document_scope.from_date;
      out.to_date = ae.document_scope.to_date;

      await ae.refresh_summary();
      note("refreshed");
      out.row_count = (ae.rows || []).length;
      return out;
    } catch (e) {
      let msg = "";
      try {
        msg = e && e.message ? e.message : typeof e === "string" ? e : JSON.stringify(e);
      } catch (_) {
        msg = String(e);
      }
      return { error: msg, steps: out.steps, company: ae?.document_scope?.company };
    }
  }, prep);
  if (result.error) {
    throw new Error(`setScope evaluate error: ${result.error} detail=${JSON.stringify(result)}`);
  }
  await waitSummaryIdle(page);
  if (!result.company) {
    throw new Error(`setScope company empty; result=${JSON.stringify(result)}`);
  }
  return result;
}

async function readState(page) {
  return page.evaluate(() => {
    const ae = window.cur_ae;
    const rows = ae.rows || [];
    return {
      view_axis: ae.analysis_context?.view_axis,
      level_sequence: ae.analysis_context?.level_sequence,
      account_scope: ae.analysis_context?.account_scope || {},
      rows: rows.map((r) => ({
        display_code: r.display_code,
        display_title: r.display_title,
        selected_account: r.selected_account,
        level_sequence: r.level_sequence,
        period_debit: r.period_debit,
      })),
      totals: ae.totals || {},
      codes: rows.map((r) => r.display_code),
    };
  });
}

async function applyGroupFilterAtLevel(page, prep, levelSequence) {
  await page.evaluate(
    async ({ prep, levelSequence }) => {
      const ae = window.cur_ae;
      ae.switch_axis("account_level", levelSequence);
      ae.analysis_context.view_axis = "account_level";
      ae.analysis_context.level_sequence = levelSequence;
      ae.analysis_context.account_scope = {
        mode: "account",
        selected_account: prep.group_account,
        virtual_row_key: null,
        is_virtual_group: 0,
        level_sequence: levelSequence,
        tree_root_account: prep.group_account,
      };
      ae.analysis_context.page = 1;
      ae.document_scope.hide_zero_rows = 0;
      await ae.refresh_summary();
    },
    { prep, levelSequence }
  );
  await waitSummaryIdle(page);
}

async function main() {
  let prep;
  try {
    prep = benchExecute(PREP_METHOD);
    passCheck("prep", {
      group: prep.group_account,
      gl_codes: prep.gl_codes,
    });
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
    await page.goto(`${BASE}/app/account-explorer`, {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    await page.waitForSelector(".ae-shell, .ae-toolbar, .account-explorer-page", {
      timeout: 90000,
    });
    await resolveAe(page);
    await setScope(page, prep);
    passCheck("login_and_scope");

    await applyGroupFilterAtLevel(page, prep, 1);
    let state = await readState(page);
    await shot(page, "01-group-filter-group-level");
    if (state.codes.length !== 1 || state.codes[0] !== prep.group_code) {
      throw new Error(
        `Group filter@Group expected one row [${prep.group_code}], got ${JSON.stringify(state.codes)}`
      );
    }
    for (const child of prep.gl_codes) {
      if (state.codes.includes(child)) {
        throw new Error(`Child code ${child} incorrectly shown at Group level`);
      }
    }
    passCheck("group_filter_one_row", { codes: state.codes, totals: state.totals });

    await page.evaluate(async () => {
      const ae = window.cur_ae;
      const row = (ae.rows || [])[0];
      if (!row) throw new Error("no row for Analyze");
      ae.analyze_row_as_filter(row);
    });
    await waitSummaryIdle(page);
    const afterAnalyze = await readState(page);
    await shot(page, "02-after-analyze");
    if (afterAnalyze.codes.length !== 1 || afterAnalyze.codes[0] !== prep.group_code) {
      throw new Error(
        `After Analyze expected one Group row, got ${JSON.stringify(afterAnalyze.codes)} level=${afterAnalyze.level_sequence}`
      );
    }
    passCheck("analyze_keeps_group_row", {
      codes: afterAnalyze.codes,
      level: afterAnalyze.level_sequence,
    });

    await page.evaluate(async () => {
      const ae = window.cur_ae;
      const row = (ae.rows || [])[0];
      if (!row) throw new Error("no row for navigate");
      ae.drill_row(row, "navigate");
    });
    await waitSummaryIdle(page);
    const afterNavigate = await readState(page);
    await shot(page, "03-after-navigate");
    const navCodes = afterNavigate.codes.filter((c) => !String(c).startsWith("__"));
    if (!prep.gl_codes.every((c) => navCodes.includes(c))) {
      throw new Error(
        `After navigate expected GL children ${prep.gl_codes}, got ${JSON.stringify(navCodes)}`
      );
    }
    if (navCodes.includes(prep.group_code)) {
      throw new Error("Group code still present after navigate to GL");
    }
    passCheck("navigate_reveals_gl_children", {
      codes: navCodes,
      level: afterNavigate.level_sequence,
    });

    await applyGroupFilterAtLevel(page, prep, 2);
    state = await readState(page);
    await shot(page, "04-group-filter-gl-level");
    const glCodes = state.codes.filter((c) => !String(c).startsWith("__"));
    const missing = prep.gl_codes.filter((c) => !glCodes.includes(c));
    // Page may truncate; require that every visible code is a GL code and at least one expected child appears.
    if (!glCodes.length) {
      throw new Error("GL level returned no rows");
    }
    if (!prep.gl_codes.some((c) => glCodes.includes(c))) {
      throw new Error(`GL level missing expected children ${prep.gl_codes.slice(0,5)} got ${glCodes}`);
    }
    if (missing.length === prep.gl_codes.length) {
      throw new Error(`GL level expected some of ${prep.gl_codes}, got ${glCodes}`);
    }
    // GL presentation must not include Group code or 6+ digit SL-looking codes.
    if (state.codes.includes(prep.group_code)) {
      throw new Error("Group code present at GL presentation");
    }
    for (const code of state.codes.filter((c) => !String(c).startsWith("__"))) {
      if (String(code).length !== 4) {
        throw new Error(`Non-GL code ${code} at GL presentation`);
      }
    }
    passCheck("gl_level_only_gl_rows", { codes: glCodes });
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
