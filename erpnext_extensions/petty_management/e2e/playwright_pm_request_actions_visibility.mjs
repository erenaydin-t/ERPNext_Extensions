/**
 * PM Request Actions visibility — View Payment Entries survives workflow menu refresh.
 *
 * Evidence: screenshots + Playwright trace under petty_management/e2e/.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_request_actions_visibility");
const TRACE = path.join(__dirname, "traces", "pm_request_actions_visibility.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";

function bench(method, kwargs = null) {
  return benchExecute(method, kwargs);
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

async function waitPmRequestForm(page, name) {
  await page.waitForFunction(
    (expected) =>
      window.cur_frm?.doc?.doctype === "PM Request" &&
      window.cur_frm?.doc?.name === expected &&
      !window.cur_frm.is_loading,
    name,
    { timeout: 180000 }
  );
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openPmRequest(page, pmRequest) {
  await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(pmRequest)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitPmRequestForm(page, pmRequest);
  // Ensure toolbar flags applied (custom buttons outside workflow Actions menu).
  await page.evaluate(async () => {
    if (window.cur_frm?.trigger) {
      await window.cur_frm.trigger("setup_pm_request_toolbar");
    }
  });
  await page
    .getByRole("button", { name: /View Payment Entries|Create Payment Entry|Close PM Request/i })
    .first()
    .waitFor({ state: "visible", timeout: 90000 })
    .catch(() => null);
}

async function collectActionLabels(page) {
  return page.evaluate(() => {
    const roots = [
      document.querySelector(".page-head") || document,
      document.querySelector(".form-dashboard") || document,
    ];
    const seen = new Set();
    const labels = [];
    roots.forEach((root) => {
      root.querySelectorAll("a, button, .btn").forEach((el) => {
        const t = (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim();
        if (!t || seen.has(t)) {
          return;
        }
        seen.add(t);
        labels.push(t);
      });
    });
    return labels;
  });
}

async function assertVisibility(page, { expectView }) {
  // Custom buttons live outside workflow Actions menu (clear_actions_menu-safe).
  if (expectView) {
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
          /View Payment Entries/i.test((el.textContent || "").trim())
        ),
      { timeout: 90000 }
    );
  }

  const labels = await collectActionLabels(page);
  const blob = labels.join("\n");

  const hasView = /View Payment Entries/i.test(blob);
  const hasCreate = /Create Payment Entry/i.test(blob);

  // Actions dropdown items explicitly for Reject/Create.
  const menuItems = await page.evaluate(() => {
    return Array.from(
      document.querySelectorAll(
        ".actions-btn-group .dropdown-menu a.dropdown-item"
      )
    ).map((a) => (a.innerText || "").trim());
  });

  const menuHasCreate = menuItems.some((t) => /Create Payment Entry/i.test(t));
  const menuHasReject = menuItems.some((t) => /PM Reject/i.test(t));
  const menuHasView = menuItems.some((t) => /View Payment Entries/i.test(t));
  // Reject may appear only in the Actions dropdown (workflow).
  const hasReject =
    menuHasReject ||
    labels.some((t) => /^PM Reject$/i.test(t) || t === "PM Reject");

  if (expectView && !hasView) {
    throw new Error(
      `Expected View Payment Entries visible. labels=${JSON.stringify(labels)} menu=${JSON.stringify(menuItems)}`
    );
  }
  if (hasCreate || menuHasCreate) {
    throw new Error(
      `Create Payment Entry must not appear on fully funded request. labels=${JSON.stringify(labels)}`
    );
  }
  if (hasReject) {
    throw new Error(
      `PM Reject must not appear when submitted PE exists. labels=${JSON.stringify(labels)} menu=${JSON.stringify(menuItems)}`
    );
  }

  return {
    hasView,
    hasCreate: hasCreate || menuHasCreate,
    hasReject,
    menuHasView,
    labels,
    menuItems,
  };
}

async function run() {
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.mkdirSync(path.dirname(TRACE), { recursive: true });

  const prep = bench(
    "erpnext_extensions.petty_management.e2e.pm_request_actions_visibility_prep.prepare_fully_funded_actions_visibility"
  );

  if (!prep?.flags?.can_view_payment_entries) {
    throw new Error(`Prep flags unexpected: ${JSON.stringify(prep.flags)}`);
  }
  if (prep.flags.can_create_payment_entry || prep.flags.can_reject) {
    throw new Error(`Prep must be view-only: ${JSON.stringify(prep.flags)}`);
  }
  if (Number(prep.remaining_to_pay) > 0) {
    throw new Error(`remaining_to_pay must be 0, got ${prep.remaining_to_pay}`);
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();

  const evidence = {
    prep,
    screenshots: {},
    before: null,
    after: null,
    trace: TRACE,
  };

  try {
    await login(page, prep.user.email, prep.user.password);
    await openPmRequest(page, prep.pm_request);

    evidence.before = await assertVisibility(page, { expectView: true });
    evidence.screenshots.before_reload = await shot(
      page,
      "01_before_reload_view_payment_entries"
    );

    await page.reload({ waitUntil: "domcontentloaded" });
    await waitPmRequestForm(page, prep.pm_request);
    await page.evaluate(async () => {
      if (window.cur_frm?.trigger) {
        await window.cur_frm.trigger("setup_pm_request_toolbar");
      }
    });
    // Stable wait: button must be present in DOM (custom button, not Actions menu).
    await page.waitForFunction(
      () =>
        Array.from(document.querySelectorAll("a, button, .btn")).some((el) =>
          /View Payment Entries/i.test((el.textContent || "").trim())
        ),
      { timeout: 90000 }
    );

    evidence.after = await assertVisibility(page, { expectView: true });
    evidence.screenshots.after_reload = await shot(
      page,
      "02_after_reload_view_payment_entries"
    );

    await context.tracing.stop({ path: TRACE });
    await browser.close();

    console.log(
      JSON.stringify(
        {
          ok: true,
          pm_request: prep.pm_request,
          before: evidence.before,
          after: evidence.after,
          screenshots: evidence.screenshots,
          trace: TRACE,
        },
        null,
        2
      )
    );
  } catch (err) {
    try {
      evidence.screenshots.failure = await shot(page, "99_failure");
      await context.tracing.stop({ path: TRACE });
    } catch (_) {
      /* ignore */
    }
    await browser.close();
    console.error(err);
    console.error(JSON.stringify({ ok: false, evidence, error: String(err) }, null, 2));
    process.exit(1);
  }
}

run();
