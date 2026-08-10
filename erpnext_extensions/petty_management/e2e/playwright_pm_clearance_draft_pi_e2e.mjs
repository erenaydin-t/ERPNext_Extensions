/**
 * v4.1.5 Draft PI Finance gate — Playwright E2E.
 * Prep leaves Clearance at Pending Finance Review with Draft PI.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_draft_pi_e2e");
const TRACE = path.join(__dirname, "traces", "pm_clearance_draft_pi_e2e.zip");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8001";
const BENCH =
  process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function benchExecute(method, kwargs = null) {
  let cmd = `cd ${BENCH} && bench --site development.localhost execute "${method}"`;
  if (kwargs) {
    cmd += ` --kwargs '${JSON.stringify(kwargs)}'`;
  }
  const out = execSync(cmd, { encoding: "utf8" });
  return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
}

function errText(e) {
  if (e == null) return "unknown";
  if (typeof e === "string") return e;
  return String(e?.message || e?._server_messages || e?.exc || e);
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

async function waitForm(page, doctype) {
  await page.waitForFunction(
    (dt) => window.cur_frm?.doc?.doctype === dt && !window.cur_frm.is_loading,
    doctype,
    { timeout: 180000 }
  );
}

async function openDoc(page, doctype, name) {
  const route = doctype.toLowerCase().replace(/ /g, "-");
  await page.goto(`${BASE}/app/${route}/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
    timeout: 120000,
  });
  await waitForm(page, doctype);
}

async function softReload(page, doctype, name) {
  await openDoc(page, doctype, name);
}

/**
 * Apply workflow without calling reload_doc inside evaluate (avoids
 * "Execution context was destroyed" when Desk navigates).
 */
async function applyWorkflow(page, action) {
  return page.evaluate(async (act) => {
    const toMsg = (e) => {
      if (e == null) return "unknown";
      if (typeof e === "string") return e;
      try {
        if (e._server_messages) {
          const parsed = JSON.parse(e._server_messages);
          const msgs = (Array.isArray(parsed) ? parsed : [parsed]).map((m) => {
            try {
              const o = typeof m === "string" ? JSON.parse(m) : m;
              return o.message || String(m);
            } catch (_err) {
              return String(m);
            }
          });
          if (msgs.length) return msgs.join("\n");
        }
      } catch (_err) {
        /* ignore */
      }
      return String(e?.message || e?.exc || e);
    };
    try {
      await frappe.call({
        method: "frappe.model.workflow.apply_workflow",
        args: { doc: window.cur_frm.doc, action: act },
        freeze: false,
      });
      return {
        ok: true,
        status: window.cur_frm.doc.status,
        ws: window.cur_frm.doc.workflow_state,
      };
    } catch (e) {
      return { ok: false, message: toMsg(e) };
    }
  }, action);
}

async function docState(page) {
  return page.evaluate(() => ({
    status: window.cur_frm?.doc?.status || "",
    ws: window.cur_frm?.doc?.workflow_state || "",
    journal_entry: window.cur_frm?.doc?.journal_entry || "",
  }));
}

async function main() {
  fs.mkdirSync(SCREEN, { recursive: true });
  fs.mkdirSync(path.dirname(TRACE), { recursive: true });

  const prep = benchExecute(
    "erpnext_extensions.petty_management.e2e.pm_clearance_draft_pi_prep.prepare"
  );
  const consoleErrors = [];
  const networkFailures = [];
  const screenshots = {};

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext();
  await context.tracing.start({ screenshots: true, snapshots: true });
  const page = await context.newPage();
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("response", (res) => {
    if (res.status() >= 400) networkFailures.push(`${res.status()} ${res.url()}`);
  });

  try {
    await login(page, prep.users.finance.email, prep.users.finance.password);
    await openDoc(page, "PM Clearance", prep.pm_clearance);
    screenshots.finance_open = await shot(page, "01_finance_pending_draft");

    const warningVisible = await page.evaluate(() => {
      const headline = document.querySelector(
        ".form-headline, .form-message, .msgprint, .alert"
      );
      const txt = (
        (headline?.innerText || "") +
        "\n" +
        (document.body?.innerText || "")
      ).toLowerCase();
      return (
        txt.includes("not submitted") ||
        (txt.includes("draft") && txt.includes("purchase"))
      );
    });

    const blockProbe = await applyWorkflow(page, "PM Finance Approve");
    // Dismiss any error dialog without relying on navigation.
    await page.keyboard.press("Escape").catch(() => null);
    await softReload(page, "PM Clearance", prep.pm_clearance);
    const afterBlock = await docState(page);
    screenshots.finance_blocked = await shot(page, "02_finance_blocked");

    let openTodos;
    try {
      openTodos = benchExecute(
        "erpnext_extensions.petty_management.e2e.pm_clearance_draft_pi_prep.count_open_finance_todos",
        { pm_clearance: prep.pm_clearance }
      );
    } catch (e) {
      openTodos = { open_count: -1, error: errText(e) };
    }

    const submitted = benchExecute(
      "erpnext_extensions.petty_management.e2e.pm_clearance_draft_pi_prep.submit_prepared_pi",
      { purchase_invoice: prep.draft_pi }
    );

    await softReload(page, "PM Clearance", prep.pm_clearance);
    // Wait briefly for readiness banner callback.
    await page.waitForTimeout(1500);

    const warningGone = await page.evaluate(() => {
      const headline = document.querySelector(
        ".form-headline .alert, .form-headline, .form-message"
      );
      const txt = (headline?.innerText || "").toLowerCase();
      if (!txt.trim()) return true;
      return !(
        txt.includes("not submitted") ||
        (txt.includes("draft") && txt.includes("purchase"))
      );
    });

    const approveProbe = await applyWorkflow(page, "PM Finance Approve");
    await softReload(page, "PM Clearance", prep.pm_clearance);
    const afterApprove = await docState(page);
    screenshots.finance_approved = await shot(page, "03_finance_approved");

    const settleProbe = await page.evaluate(async () => {
      const toMsg = (e) => {
        if (e == null) return "unknown";
        if (typeof e === "string") return e;
        return String(e?.message || e?._server_messages || e?.exc || e);
      };
      try {
        const out = await frappe.call({
          method:
            "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.settle_petty_cash",
          args: { pm_clearance: window.cur_frm.doc.name },
          freeze: false,
        });
        const msg = out?.message || {};
        return {
          ok: true,
          journal_entry: msg.journal_entry || window.cur_frm.doc.journal_entry || "",
          status: window.cur_frm.doc.status,
        };
      } catch (e) {
        return { ok: false, message: toMsg(e) };
      }
    });
    await softReload(page, "PM Clearance", prep.pm_clearance);
    const afterSettle = await docState(page);
    if (!settleProbe.journal_entry && afterSettle.journal_entry) {
      settleProbe.journal_entry = afterSettle.journal_entry;
      settleProbe.status = afterSettle.status;
      settleProbe.ok = true;
    }
    screenshots.settled = await shot(page, "04_settled");

    let jeRefsPi = false;
    if (settleProbe.journal_entry) {
      try {
        const jeCheck = benchExecute(
          "erpnext_extensions.petty_management.e2e.pm_clearance_draft_pi_prep.je_references_pi",
          {
            journal_entry: settleProbe.journal_entry,
            purchase_invoice: prep.draft_pi,
          }
        );
        jeRefsPi = !!jeCheck.ok;
      } catch (_e) {
        jeRefsPi = false;
      }
    }

    // Fallback: extract PI from console ValidationError if call catch lost message.
    let blockMsg = String(blockProbe.message || "");
    if (!blockMsg.includes(prep.draft_pi)) {
      const hit = consoleErrors.find((t) => String(t).includes(prep.draft_pi));
      if (hit) blockMsg = String(hit);
    }

    const result = {
      ok:
        !blockProbe.ok &&
        blockMsg.includes(prep.draft_pi) &&
        String(afterBlock.status || "").includes("Pending") &&
        (openTodos?.open_count || 0) >= 1 &&
        !!approveProbe.ok &&
        String(afterApprove.status || "").toLowerCase().includes("approv") &&
        !!settleProbe.ok &&
        !!settleProbe.journal_entry &&
        jeRefsPi,
      prep: {
        clearance: prep.pm_clearance,
        draft_pi: prep.draft_pi,
        workflow_state_title: prep.workflow_state_title,
      },
      warning_visible_before_submit: warningVisible,
      warning_gone_after_submit: warningGone,
      finance_blocked: { ...blockProbe, message: blockMsg },
      state_after_block: afterBlock,
      open_todos_after_block: openTodos,
      pi_submitted: submitted,
      finance_approved: { ...approveProbe, after: afterApprove },
      settled: settleProbe,
      je_references_pi: jeRefsPi,
      screenshots,
      console_errors: consoleErrors.slice(0, 40),
      network_failures: networkFailures.slice(0, 40),
      trace: TRACE,
    };
    console.log(JSON.stringify(result, null, 2));
    if (!result.ok) process.exitCode = 1;
  } catch (e) {
    console.log(
      JSON.stringify(
        {
          ok: false,
          error: errText(e),
          screenshots,
          console_errors: consoleErrors.slice(0, 40),
          network_failures: networkFailures.slice(0, 40),
        },
        null,
        2
      )
    );
    process.exitCode = 1;
  } finally {
    await context.tracing.stop({ path: TRACE }).catch(() => null);
    await browser.close().catch(() => null);
  }
}

main();
