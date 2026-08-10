/**
 * v4.0.2 PM Request multi-level approval E2E (native Assignment Rule ToDos).
 * Holder → Manager → CEO → Finance → Finance Approved + Create Payment Entry.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_multi_approval");
const TRACE = path.join(__dirname, "traces", "pm_request_multi_approval.zip");
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

async function openDoc(page, doctypeRoute, name) {
  await page.goto(`${BASE}/app/${doctypeRoute}/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    (n) => window.cur_frm?.doc?.name === n && !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function applyWorkflowAction(page, actionLabel) {
  // Prefer Actions menu workflow item
  const actionsBtn = page
    .locator(".actions-btn-group .btn")
    .filter({ hasText: /^Actions$/i })
    .first();
  if (await actionsBtn.count()) {
    await actionsBtn.click({ timeout: 30000 });
    const item = page
      .locator(".actions-btn-group .dropdown-menu a.dropdown-item, .dropdown-menu li a")
      .filter({ hasText: new RegExp(actionLabel, "i") })
      .first();
    if (await item.count()) {
      await item.click({ timeout: 30000 });
      await page.waitForTimeout(2000);
      return { via: "actions-menu" };
    }
  }
  // Fallback: call apply_workflow from desk
  const applied = await page.evaluate(async (action) => {
    try {
      const r = await frappe.call({
        method: "frappe.model.workflow.apply_workflow",
        args: { doc: cur_frm.doc, action },
      });
      if (cur_frm?.reload_doc) {
        await cur_frm.reload_doc();
      }
      return {
        ok: true,
        workflow_state: r.message?.workflow_state || cur_frm?.doc?.workflow_state,
      };
    } catch (e) {
      return {
        ok: false,
        error: String(e?.message || e?._server_messages || e || "unknown"),
        server: e?._server_messages || null,
      };
    }
  }, actionLabel);
  if (!applied?.ok) {
    throw new Error(`apply_workflow failed: ${applied?.error || JSON.stringify(applied)}`);
  }
  return { via: "api", workflow_state: applied.workflow_state };
}

async function waitWorkflowTitle(page, title) {
  await page.waitForFunction(
    (expected) => {
      const ws = window.cur_frm?.doc?.workflow_state;
      if (!ws) return false;
      // title may equal link name on this site
      const el = document.querySelector(".form-workflow-states, .workflow-button, .indicator-pill");
      const text = (el?.textContent || "").replace(/\s+/g, " ");
      return ws === expected || text.includes(expected);
    },
    title,
    { timeout: 120000 }
  ).catch(async () => {
    const got = await page.evaluate(() => window.cur_frm?.doc?.workflow_state);
    if (got !== title) {
      throw new Error(`Expected workflow ${title}, got ${got}`);
    }
  });
}

async function hasCreatePe(page) {
  await page.evaluate(() => window.cur_frm?.trigger?.("setup_pm_request_toolbar"));
  await page.waitForTimeout(2500);
  return page.evaluate(() =>
    Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
      /Create Payment Entry/i.test((el.textContent || "").trim())
    )
  );
}

async function run() {
  const prep = bench(
    "erpnext_extensions.petty_management.e2e.pm_multi_approval_prep.prepare_pm_request_multi_approval"
  );
  const evidence = { prep, screenshots: {}, console_errors: [] };
  const browser = await chromium.launch({ headless: true });
  let context = null;
  let page = null;

  try {
    ({ context, page } = await loginAs(browser, prep.holder.email, prep.holder.password, evidence));
    await context.tracing.start({ screenshots: true, snapshots: true });
    await openDoc(page, "pm-request", prep.pm_request);
    evidence.screenshots.holder_open = await shot(page, "01_holder_open");
    await applyWorkflowAction(page, "PM Submit for Approval");
    await openDoc(page, "pm-request", prep.pm_request);
    await waitWorkflowTitle(page, "Pending Manager Approval");
    evidence.screenshots.after_submit = await shot(page, "02_after_submit");
    await context.close();

    ({ context, page } = await loginAs(browser, prep.manager.email, prep.manager.password, evidence));
    await openDoc(page, "pm-request", prep.pm_request);
    evidence.screenshots.manager = await shot(page, "03_manager");
    await applyWorkflowAction(page, "PM Manager Approve");
    await openDoc(page, "pm-request", prep.pm_request);
    await waitWorkflowTitle(page, "Pending CEO Approval");
    await context.close();

    ({ context, page } = await loginAs(browser, prep.ceo.email, prep.ceo.password, evidence));
    await openDoc(page, "pm-request", prep.pm_request);
    evidence.screenshots.ceo = await shot(page, "04_ceo");
    await applyWorkflowAction(page, "PM CEO Approve");
    await openDoc(page, "pm-request", prep.pm_request);
    await waitWorkflowTitle(page, "Pending Finance Approval");
    await context.close();

    ({ context, page } = await loginAs(browser, prep.finance.email, prep.finance.password, evidence));
    await openDoc(page, "pm-request", prep.pm_request);
    evidence.screenshots.finance = await shot(page, "05_finance");
    await applyWorkflowAction(page, "PM Finance Approve");
    await openDoc(page, "pm-request", prep.pm_request);
    await waitWorkflowTitle(page, "Finance Approved");
    const createVisible = await hasCreatePe(page);
    evidence.screenshots.waiting = await shot(page, "06_waiting_for_payment");
    evidence.create_payment_entry_visible = createVisible;

    fs.mkdirSync(path.dirname(TRACE), { recursive: true });
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    evidence.trace = TRACE;

    const ok = createVisible === true;
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
