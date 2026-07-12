/**
 * Debug tool: capture every search_link request/response for PM Clearance PI/PO link fields.
 *
 * Outputs JSON with:
 * - all /api/method/frappe.desk.search.search_link requests (post body + response json)
 * - console errors
 * - screenshots around the grid row editor
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_link_debug");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH =
  process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function bench(expr) {
  const out = execSync(
    `cd ${BENCH} && bench --site development.localhost execute "${expr}"`,
    {
      encoding: "utf8",
    }
  );
  return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
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

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function run() {
  const prep = bench(
    "__import__('erpnext_extensions.petty_management.e2e.pm_clearance_settlement_e2e_prep', fromlist=['prepare']).prepare()"
  );

  const requests = [];
  const consoleErrors = [];
  const consoleAll = [];

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1700, height: 1000 },
  });
  context.setDefaultTimeout(180000);
  context.setDefaultNavigationTimeout(180000);

  const page = await context.newPage();

  page.on("console", (msg) => {
    const line = `[${msg.type()}] ${msg.text()}`;
    consoleAll.push(line);
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(String(err)));

  page.on("request", async (req) => {
    if (!/\/api\/method\/frappe\.desk\.search\.search_link/.test(req.url()))
      return;
    const post = req.postData() || "";
    requests.push({
      phase: "request",
      url: req.url(),
      method: req.method(),
      post,
    });
  });
  page.on("response", async (res) => {
    if (!/\/api\/method\/frappe\.desk\.search\.search_link/.test(res.url()))
      return;
    let bodyText = "";
    try {
      bodyText = await res.text();
    } catch (_e) {}
    requests.push({
      phase: "response",
      url: res.url(),
      status: res.status(),
      bodyText,
    });
  });

  await login(
    page,
    process.env.FRAPPE_E2E_USER || "Administrator",
    process.env.FRAPPE_E2E_PASSWORD || "admin"
  );
  await page.evaluate(() => {
    try {
      localStorage.setItem("pm_clearance_link_debug", "1");
      window.PM_CLEARANCE_LINK_DEBUG = 1;
    } catch (_e) {}
  });

  await page.goto(`${BASE}/app/pm-clearance/new`, {
    waitUntil: "domcontentloaded",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_frm?.doc?.doctype === "PM Clearance" &&
      !window.cur_frm.is_loading,
    {
      timeout: 180000,
    }
  );

  // Set header values via cur_frm to avoid link-click issues
  await page.evaluate(async (p) => {
    await window.cur_frm.set_value("company", p.company);
    await window.cur_frm.set_value("employee", p.employee);
  }, prep);
  await page.waitForTimeout(1500);

  // Add a settlement line row (PI) and open row editor
  await page
    .locator('[data-fieldname="details"] .grid-add-row')
    .first()
    .click();
  await page.waitForTimeout(800);
  await shot(page, "01_after_add_row");

  // Click the Purchase Invoice cell input in the last grid row and type supplier name.
  const piCellInput = page
    .locator('[data-fieldname="details"] .grid-row')
    .last()
    .locator('.frappe-control[data-fieldname="purchase_invoice"] input');
  await piCellInput.click({ timeout: 60000, force: true });
  await page.waitForTimeout(300);
  // Playwright fill() can blur briefly; Desk link control drops search_link results when unfocused.
  await piCellInput.pressSequentially(prep.supplier_name, { delay: 40 });
  await page.waitForTimeout(2500);

  const uiState = await page.evaluate(() => {
    const grid = document.querySelector('[data-fieldname="details"]');
    const inputs = Array.from(
      document.querySelectorAll(
        '[data-fieldname="details"] input[data-fieldname="purchase_invoice"]'
      )
    );
    const awes = Array.from(document.querySelectorAll(".awesomplete"));
    const lists = awes.map((w) => {
      const ul = w.querySelector("ul");
      const liCount = ul ? ul.querySelectorAll("li").length : 0;
      const style = ul ? window.getComputedStyle(ul) : null;
      return {
        id: w.className,
        liCount,
        ulDisplay: style ? style.display : null,
        ulVisibility: style ? style.visibility : null,
        ulHidden: ul ? ul.hidden : null,
        rect: ul ? ul.getBoundingClientRect() : null,
      };
    });
    const focused = document.activeElement;
    let linkDebug = null;
    try {
      const grid = window.cur_frm?.fields_dict?.details?.grid;
      const grow = grid?.grid_rows?.[grid.grid_rows.length - 1];
      const field =
        grow?.on_grid_fields_dict?.purchase_invoice ||
        grow?.grid_form?.fields_dict?.purchase_invoice;
      if (field) {
        linkDebug = {
          inputFocused: field.$input?.is?.(":focus"),
          cacheKeys: field.$input?.cache?.["Purchase Invoice"]
            ? Object.keys(field.$input.cache["Purchase Invoice"])
            : [],
          awesompleteListLen: field.awesomplete?.list?.length ?? null,
          ulChildCount: field.awesomplete?.ul?.children?.length ?? null,
        };
      }
    } catch (e) {
      linkDebug = { error: String(e) };
    }
    return {
      editableGridMeta:
        window.cur_frm?.fields_dict?.details?.grid?.meta?.editable_grid,
      gridRowOpenCount: document.querySelectorAll(".grid-row-open").length,
      modalVisible: !!document.querySelector(".modal-dialog.show, .modal.in"),
      piInputCount: inputs.length,
      inputs: inputs.map((inp) => ({
        value: inp.value,
        ariaExpanded: inp.getAttribute("aria-expanded"),
        visible: !!(inp.offsetParent || inp.getClientRects().length),
        rect: inp.getBoundingClientRect(),
      })),
      awesompleteWrappers: lists,
      focusedTag: focused ? focused.tagName : null,
      focusedFieldname: focused?.getAttribute?.("data-fieldname") || null,
      linkDebug,
    };
  });

  await shot(page, "02_after_type_supplier_name");

  const selected = await page.evaluate(() => {
    const grid = window.cur_frm?.fields_dict?.details?.grid;
    const grow = grid?.grid_rows?.[grid.grid_rows.length - 1];
    const field = grow?.on_grid_fields_dict?.purchase_invoice;
    const ul = field?.awesomplete?.ul;
    if (!ul) return { ok: false, reason: "no ul" };
    const opt =
      ul.querySelector('[role="option"]') ||
      ul.querySelector("li") ||
      ul.firstElementChild;
    if (!opt)
      return { ok: false, reason: "no option", childCount: ul.children.length };
    opt.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
    opt.click();
    return {
      ok: true,
      valueAfter: field.get_value?.() || field.$input?.val?.(),
      childCount: ul.children.length,
      ulSameAsVisible: !!document
        .querySelector(".awesomplete_list_5 ul")
        ?.isSameNode(ul),
    };
  });
  await page.waitForTimeout(1500);
  await shot(page, "03_after_select_pi");

  console.log(
    JSON.stringify(
      {
        prep,
        selected,
        consoleErrors,
        consoleAll: consoleAll.filter((l) =>
          /PM Clearance|search_link|awesomplete/i.test(l)
        ),
        requests,
        uiState,
        screenshots: [
          path.join(SCREEN, "01_after_add_row.png"),
          path.join(SCREEN, "02_after_type_supplier_name.png"),
          path.join(SCREEN, "03_after_select_pi.png"),
        ],
      },
      null,
      2
    )
  );
  await browser.close();
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
