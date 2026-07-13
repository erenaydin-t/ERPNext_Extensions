/**
 * Cheque Leaf void workflow E2E — DB-first status checks via e2e_playwright_db.mjs.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";
import {
  benchExecute,
  getDocumentState,
  waitDocumentState,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "cheque_leaf_void");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH =
  process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";
const LEAF = "Cheque Leaf";

function bench(method) {
  return benchExecute(method);
}

function benchVoidReject(leafName, reason) {
  const args = JSON.stringify([leafName, reason]);
  const cmd = `cd ${BENCH} && bench --site development.localhost execute "erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.void_cheque_leaf" --args '${args}'`;
  try {
    execSync(cmd, { encoding: "utf8", stdio: "pipe" });
    return { rejected: false, text: "" };
  } catch (e) {
    const text = `${e.stdout || ""}\n${e.stderr || ""}\n${e.message || ""}`;
    return { rejected: true, text };
  }
}

async function login(page) {
  await page.goto(`${BASE}/login`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await page.fill(
    "#login_email",
    process.env.FRAPPE_E2E_USER || "Administrator"
  );
  await page.fill(
    "#login_password",
    process.env.FRAPPE_E2E_PASSWORD || "admin"
  );
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function openLeaf(page, leafName) {
  await page.goto(`${BASE}/desk/cheque-leaf/${encodeURIComponent(leafName)}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(
    () =>
      window.cur_frm?.doc?.doctype === "Cheque Leaf" &&
      !window.cur_frm.is_loading,
    { timeout: 180000 }
  );
}

const FIND_VOID_BTN = `() => Array.from(document.querySelectorAll(".custom-actions .btn, .page-actions .btn")).find((b) => {
	const t = (b.textContent || "").trim();
	return t === "Void Cheque Leaf" || t.startsWith("Void Cheque Leaf");
})`;

async function run() {
  const prep = bench(
    "erpnext_extensions.cheque_management.e2e.cheque_leaf_void_prep.prepare_cheque_leaf_void_e2e"
  );
  const results = [];
  const evidence = { screenshots: {}, prep };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);

  try {
    await login(page);

    // Test A — Available: button, dialog title, void, button gone
    await openLeaf(page, prep.available_leaf);
    const testA = await page.evaluate(async (findVoidBtnSrc) => {
      const findVoidButton = eval(findVoidBtnSrc);
      const btn = findVoidButton();
      if (!btn) {
        return { ok: false, step: "button_missing" };
      }
      const label = (btn.textContent || "").trim();
      if (label.includes("مخدوش") || label !== "Void Cheque Leaf") {
        return { ok: false, step: "bad_button_label", label };
      }
      btn.click();
      await new Promise((r) => setTimeout(r, 600));
      const dialog =
        document.querySelector(".modal.show .modal-dialog") ||
        Array.from(document.querySelectorAll(".modal-dialog")).find((el) =>
          el.closest(".modal")?.classList.contains("show")
        );
      if (!dialog) {
        return { ok: false, step: "no_dialog" };
      }
      const title = (
        dialog.querySelector(".modal-title")?.textContent || ""
      ).trim();
      if (title.includes("مخدوش") || title !== "Void Cheque Leaf") {
        return { ok: false, step: "bad_dialog_title", title };
      }
      const ta = dialog.querySelector('textarea[data-fieldname="void_reason"]');
      if (ta) {
        ta.value = "E2E void — damaged leaf";
        ta.dispatchEvent(new Event("input", { bubbles: true }));
      }
      dialog.querySelector(".btn-modal-primary")?.click();
      await new Promise((r) => setTimeout(r, 3000));
      await cur_frm.reload_doc();
      await cur_frm.refresh();
      const afterBtn = findVoidButton();
      return {
        ok: cur_frm.doc.status === "Void" && !afterBtn,
        status: cur_frm.doc.status,
        button_after: !!afterBtn,
        label,
        title,
      };
    }, FIND_VOID_BTN);
    const voidedLeaf = prep.available_leaf;
    evidence.screenshots.A = await shot(page, "A_available_void");
    const dbAfterVoid = await waitDocumentState(
      LEAF,
      voidedLeaf,
      { status: "Void" },
      { fields: ["name", "status", "docstatus"] }
    );
    const testAOk =
      testA.ok && dbAfterVoid.ok && dbAfterVoid.state?.status === "Void";
    results.push({
      test: "A_void_available_leaf",
      ok: testAOk,
      testA,
      db_after: dbAfterVoid.state,
      wait: dbAfterVoid,
    });

    // Test B — reload Void leaf: no button, server rejects
    await openLeaf(page, voidedLeaf);
    const testBUi = await page.evaluate(async (findVoidBtnSrc) => {
      const findVoidButton = eval(findVoidBtnSrc);
      return { btn: !!findVoidButton() };
    }, FIND_VOID_BTN);
    const testBServer = benchVoidReject(voidedLeaf, "repeat");
    const testB = {
      ok:
        !testBUi.btn &&
        testBServer.rejected &&
        testBServer.text.toLowerCase().includes("already void") &&
        getDocumentState(LEAF, voidedLeaf, ["name", "status"]).status ===
          "Void",
      btn: testBUi.btn,
      serverOk: testBServer.rejected,
      serverText: testBServer.text.slice(0, 500),
    };
    evidence.screenshots.B = await shot(page, "B_void_no_button");
    results.push({ test: "B_void_leaf_no_repeat", ok: testB.ok, testB });

    // Test C — Reserved
    await openLeaf(page, prep.reserved_leaf);
    const testCUi = await page.evaluate(async (findVoidBtnSrc) => {
      const findVoidButton = eval(findVoidBtnSrc);
      return { btn: !!findVoidButton() };
    }, FIND_VOID_BTN);
    const testCServer = benchVoidReject(prep.reserved_leaf, "x");
    const expectMsg = "Only available cheque leaves can be voided";
    const testC = {
      ok:
        !testCUi.btn &&
        testCServer.rejected &&
        testCServer.text.includes(expectMsg),
      btn: testCUi.btn,
      serverOk: testCServer.rejected,
      serverText: testCServer.text.slice(0, 500),
    };
    evidence.screenshots.C = await shot(page, "C_reserved_no_void");
    results.push({ test: "C_reserved_no_void", ok: testC.ok, testC });

    // Test D — Used
    await openLeaf(page, prep.used_leaf);
    const testDUi = await page.evaluate(async (findVoidBtnSrc) => {
      const findVoidButton = eval(findVoidBtnSrc);
      return { btn: !!findVoidButton() };
    }, FIND_VOID_BTN);
    const testDServer = benchVoidReject(prep.used_leaf, "x");
    const testD = {
      ok:
        !testDUi.btn &&
        testDServer.rejected &&
        testDServer.text.includes(expectMsg),
      btn: testDUi.btn,
      serverOk: testDServer.rejected,
      serverText: testDServer.text.slice(0, 500),
    };
    evidence.screenshots.D = await shot(page, "D_used_no_void");
    results.push({ test: "D_used_no_void", ok: testD.ok, testD });
  } finally {
    await browser.close();
  }

  const all_ok = results.every((r) => r.ok);
  console.log(JSON.stringify({ all_ok, results, evidence }, null, 2));
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
