/**
 * Desk-route PDC list filter E2E (real browser).
 *
 *   bench build --app erpnext_extensions && bench --site development.localhost clear-cache
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/cheque_management/e2e/playwright_pdc_desk_list_filters.mjs
 *
 * UI-primary: desk list filter UX; optional SQL dump for debugging only.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN_DIR = path.join(__dirname, "screenshots", "desk");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const DESK_LIST = `${BASE}/desk/post-dated-cheque`;
const USER = process.env.FRAPPE_E2E_USER || "Administrator";
const PASS = process.env.FRAPPE_E2E_PASSWORD || "admin";
const BENCH =
  process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

const results = [];

function log(test, ok, detail = {}) {
  results.push({ test, ok, detail });
  console.log(JSON.stringify({ test, ok, detail }));
}

async function login(page) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill("#login_email", USER);
  await page.fill("#login_password", PASS);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitForPdcList(page) {
  await page.waitForFunction(
    () => {
      const lv = window.cur_list;
      return (
        lv &&
        lv.doctype === "Post Dated Cheque" &&
        typeof lv.get_filters_for_args === "function" &&
        lv.filter_area &&
        !lv.loading &&
        Array.isArray(lv.data)
      );
    },
    { timeout: 180000 }
  );
  await page.waitForTimeout(1200);
}

async function openFilterPopover(page) {
  await page.locator("button.filter-button").first().click();
  await page.waitForSelector(".filter-popover", {
    state: "visible",
    timeout: 30000,
  });
  await page.waitForTimeout(400);
}

async function popoverState(page) {
  return page.evaluate(() => {
    const pop = document.querySelector(".filter-popover");
    const emptyEl = pop?.querySelector(".empty-filters");
    const emptyVisible = !!(emptyEl && emptyEl.offsetParent !== null);
    const boxes = [...(pop?.querySelectorAll(".filter-box") || [])].filter(
      (b) => b.offsetParent !== null
    );
    const badNameEmpty = boxes.some((box) => {
      const inputs = [...box.querySelectorAll("input, select")];
      const fieldLabel = (box.innerText || "").toLowerCase();
      const hasName = fieldLabel.includes("name") || fieldLabel.includes("id");
      const condEquals = (box.innerText || "").toLowerCase().includes("equals");
      const valInput = inputs.find(
        (i) => i.type !== "hidden" && !i.classList.contains("condition")
      );
      const val = valInput?.value ?? "";
      return hasName && condEquals && val.trim() === "";
    });
    return {
      emptyVisible,
      emptyText: emptyEl?.textContent?.trim() || "",
      visibleBoxes: boxes.length,
      badNameEmpty,
      popoverText: pop?.innerText?.slice(0, 800) || "",
    };
  });
}

async function filterXActive(page) {
  return page.evaluate(() => {
    const fl = window.cur_list?.filter_area?.filter_list;
    const applied = (fl?.get_filters?.() || []).length;
    const btn = document.querySelector(".filter-button");
    return applied > 0 || btn?.classList.contains("btn-primary-light");
  });
}

async function dumpSources(page) {
  return page.evaluate(() =>
    window.erpnext_extensions?.cheque_management?.pdc_list_view?.dump_all_sources?.(
      window.cur_list
    )
  );
}

async function screenshot(page, name) {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });
  const file = path.join(SCREEN_DIR, `${name}.png`);
  await page.screenshot({ path: file, fullPage: true });
  return file;
}

async function run() {
  fs.mkdirSync(SCREEN_DIR, { recursive: true });

  execSync(
    `cd ${BENCH} && bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.seed`,
    { encoding: "utf8", stdio: ["pipe", "pipe", "inherit"] }
  );
  const dbDump = execSync(
    `cd ${BENCH} && bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.dump`,
    { encoding: "utf8" }
  );
  const dbRows = JSON.parse(dbDump.trim().split("\n").filter(Boolean).pop());
  log(
    "seed_db_dirty",
    dbRows.some(
      (r) =>
        r.user === USER &&
        (r.List?.filters || []).some((f) => f[1] === "name" && f[3] === "")
    ),
    {
      dbRows,
    }
  );

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 1400, height: 900 },
    locale: "en-US",
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  try {
    await login(page);
    await page.goto(DESK_LIST, {
      waitUntil: "domcontentloaded",
      timeout: 120000,
    });
    await page.waitForFunction(
      () => window.cur_list?.doctype === "Post Dated Cheque",
      {
        timeout: 180000,
      }
    );
    const shotBefore = await screenshot(page, "before_early_load");
    const earlyDump = await dumpSources(page);
    log("before_load_dump", true, { earlyDump, screenshot: shotBefore });

    await waitForPdcList(page);
    const afterDump = await dumpSources(page);
    const dataLen = await page.evaluate(() => window.cur_list.data.length);
    const rowsVisible =
      dataLen > 0 &&
      !(afterDump?.get_filters_for_args || []).some(
        (f) => f[1] === "name" && f[2] === "=" && (f[3] === "" || f[3] == null)
      );

    await openFilterPopover(page);
    const pop = await popoverState(page);
    const shotPopover = await screenshot(page, "after_load_popover_open");
    await page.locator("button.filter-button").first().click();

    log(
      "desk_after_load_clean",
      rowsVisible &&
        !(await filterXActive(page)) &&
        !pop.badNameEmpty &&
        pop.emptyVisible &&
        pop.emptyText.toLowerCase().includes("no filters selected") &&
        !(afterDump?.filter_list_rows || []).some((r) => r.invalid),
      {
        data_length: await page.evaluate(() => window.cur_list.data.length),
        afterDump,
        pop,
        screenshot: shotPopover,
      }
    );

    const shotAfter = await screenshot(page, "after_load_list");
    log("after_list_screenshot", true, { screenshot: shotAfter });
  } finally {
    await browser.close();
    execSync(
      `cd ${BENCH} && bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.restore_empty`,
      { stdio: "inherit" }
    );
  }

  const main = results.filter((r) => r.test !== "after_list_screenshot");
  const all_ok = main.every((r) => r.ok);
  console.log(JSON.stringify({ all_ok, results }, null, 2));
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
