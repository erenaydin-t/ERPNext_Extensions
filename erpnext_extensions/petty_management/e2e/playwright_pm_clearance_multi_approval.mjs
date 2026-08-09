/**
 * v4.0.2 PM Clearance multi-level approval E2E.
 * Holder submit → Manager → Finance → Settle Petty Cash visible.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_multi_approval");
const TRACE = path.join(__dirname, "traces", "pm_clearance_multi_approval.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";

function bench(method, kwargs = null) {
  return benchExecute(method, kwargs);
}

async function loginAs(browser, email, password, evidence) {
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") evidence.console_errors.push(msg.text());
  });
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  // Support classic and email-input variants
  const emailSel = (await page.locator("#login_email").count())
    ? "#login_email"
    : 'input[type="email"], input[name="email"], #login_email';
  const passSel = (await page.locator("#login_password").count())
    ? "#login_password"
    : 'input[type="password"], #login_password';
  await page.locator(emailSel).first().fill(email, { timeout: 60000 });
  await page.locator(passSel).first().fill(password, { timeout: 60000 });
  await page.locator('button[type="submit"]').first().click();
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
  return { context, page };
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openDoc(page, route, name) {
  await page.goto(`${BASE}/app/${route}/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (n) => window.cur_frm?.doc?.name === n && !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function applyWorkflowAction(page, action) {
  const applied = await page.evaluate(async (act) => {
    try {
      const r = await frappe.call({
        method: "frappe.model.workflow.apply_workflow",
        args: { doc: cur_frm.doc, action: act },
      });
      if (cur_frm?.reload_doc) {
        await cur_frm.reload_doc();
      }
      return {
        ok: true,
        workflow_state: cur_frm?.doc?.workflow_state,
        status: cur_frm?.doc?.status,
        message: r.message,
      };
    } catch (e) {
      return {
        ok: false,
        error: String(e?.message || e?._server_messages || e || "unknown"),
      };
    }
  }, action);
  if (!applied?.ok) {
    throw new Error(`apply_workflow(${action}) failed: ${applied?.error || JSON.stringify(applied)}`);
  }
  return applied;
}

async function hasSettleButton(page) {
  await page.evaluate(() => {
    window.cur_frm?.trigger?.("refresh");
  });
  await page.waitForTimeout(2500);
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
      /Settle Petty Cash/i.test((el.textContent || "").trim())
    )
  );
}

async function run() {
  const prep = bench(
    "erpnext_extensions.petty_management.e2e.pm_multi_approval_prep.prepare_pm_clearance_multi_approval"
  );
  if (!prep?.pm_clearance) {
    throw new Error(`prep missing pm_clearance: ${JSON.stringify(prep)}`);
  }
  const evidence = { prep, screenshots: {}, console_errors: [] };
  const browser = await chromium.launch({ headless: true });
  let context = null;
  let page = null;

  try {
    const clearanceName = prep.pm_clearance;
    evidence.clearance = clearanceName;

    ({ context, page } = await loginAs(browser, prep.holder.email, prep.holder.password, evidence));
    await context.tracing.start({ screenshots: true, snapshots: true });
    await openDoc(page, "pm-clearance", clearanceName);
    evidence.screenshots.draft = await shot(page, "01_draft");
    await applyWorkflowAction(page, "PM Submit Finance Review");
    await openDoc(page, "pm-clearance", clearanceName);
    await context.close();

    ({ context, page } = await loginAs(browser, prep.manager.email, prep.manager.password, evidence));
    await openDoc(page, "pm-clearance", clearanceName);
    evidence.screenshots.manager = await shot(page, "02_manager");
    await applyWorkflowAction(page, "PM Manager Approve");
    await context.close();

    ({ context, page } = await loginAs(browser, prep.finance.email, prep.finance.password, evidence));
    await openDoc(page, "pm-clearance", clearanceName);
    evidence.screenshots.finance = await shot(page, "03_finance");
    await applyWorkflowAction(page, "PM Finance Approve");
    await openDoc(page, "pm-clearance", clearanceName);
    const status = await page.evaluate(() => window.cur_frm?.doc?.status);
    const settleVisible = await hasSettleButton(page);
    evidence.status = status;
    evidence.settle_visible = settleVisible;
    evidence.screenshots.approved = await shot(page, "04_approved_settle");

    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    evidence.trace = TRACE;

    const ok = status === "Approved" && settleVisible === true;
    console.log(JSON.stringify({ ok, evidence }, null, 2));
    await context.close();
    await browser.close();
    process.exit(ok ? 0 : 1);
  } catch (err) {
    evidence.error = String(err);
    try {
      if (page) evidence.screenshots.failure = await shot(page, "99_failure");
      if (context) {
        fs.mkdirSync(path.dirname(TRACE), { recursive: true });
        await context.tracing.stop({ path: TRACE }).catch(() => null);
        evidence.trace = TRACE;
        await context.close().catch(() => null);
      }
    } catch (_e) {
      /* ignore */
    }
    console.log(JSON.stringify({ ok: false, evidence }, null, 2));
    await browser.close();
    process.exit(1);
  }
}

run();
