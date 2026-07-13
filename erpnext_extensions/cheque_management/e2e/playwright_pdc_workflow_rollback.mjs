/**
 * Post Dated Cheque workflow rollback E2E (Playwright).
 *
 * DB-first assertions via shared e2e_playwright_db.mjs.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
  benchExecute,
  getDocumentState,
  waitDocumentState,
  buildFailureDebug,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pdc_workflow_rollback");
const BASE =
  process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const PDC = "Post Dated Cheque";
const PDC_FIELDS = ["name", "workflow_state", "cheque_status", "docstatus"];

function pdcStateFromDb(pdcName) {
  return getDocumentState(PDC, pdcName, PDC_FIELDS);
}

async function waitPdcWorkflowState(pdcName, expectedState, timeoutMs = 90000) {
  return waitDocumentState(
    PDC,
    pdcName,
    { workflow_state: expectedState },
    { timeoutMs, fields: PDC_FIELDS }
  );
}

function sqlVerify(pdcName) {
  return benchExecute(
    "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_sql_verify_pdc",
    { pdc_name: pdcName }
  );
}

async function shot(page, name) {
  fs.mkdirSync(SCREEN, { recursive: true });
  const p = path.join(SCREEN, `${name}.png`);
  await page.screenshot({ path: p, fullPage: true });
  return p;
}

async function login(page, user, pass) {
  await page.goto(`${BASE}/login`, { waitUntil: "load", timeout: 180000 });
  await page.waitForSelector("#login_email", {
    state: "visible",
    timeout: 60000,
  });
  await page.fill("#login_email", user);
  await page.fill("#login_password", pass);
  await page.click('button[type="submit"]');
  await page.waitForURL(/\/(app|desk)/, { timeout: 180000 });
}

async function openPdc(page, name) {
  await page.goto(`${BASE}/app/post-dated-cheque/${encodeURIComponent(name)}`, {
    waitUntil: "load",
    timeout: 180000,
  });
  await page.waitForFunction(
    () =>
      window.cur_frm?.doc?.doctype === "Post Dated Cheque" &&
      !window.cur_frm.is_loading,
    { timeout: 180000 }
  );
  await page.waitForTimeout(1500);
}

async function collectWorkflowActionLabels(page) {
  return page.evaluate(() => {
    const selectors = [
      ".actions-btn-group .btn",
      ".workflow-actions .btn",
      ".standard-actions .btn",
      ".page-actions .btn",
    ];
    const labels = new Set();
    for (const sel of selectors) {
      for (const btn of document.querySelectorAll(sel)) {
        const t = (btn.textContent || "").trim();
        if (t) labels.add(t);
      }
    }
    return Array.from(labels);
  });
}

function hasCancelWorkflowAction(actions) {
  return (actions || []).some(
    (a) => a === "Cancel Cheque" || a === "Cancel Issued Payable"
  );
}

async function standardFrappeCancelButtonVisible(page) {
  return page.evaluate(() => {
    const isCancel = (text) => {
      const t = (text || "").trim();
      return (
        t === "Cancel" || (typeof __ !== "undefined" && t === __("Cancel"))
      );
    };
    for (const btn of document.querySelectorAll(
      ".page-actions .btn-secondary, .page-actions .btn.btn-secondary"
    )) {
      if (isCancel(btn.textContent)) {
        return true;
      }
    }
    const $sec = window.cur_frm?.page?.btn_secondary;
    if ($sec?.length && isCancel($sec.text())) {
      return true;
    }
    return false;
  });
}

const FIND_ROLLBACK_BTN = `() => Array.from(document.querySelectorAll(".custom-actions .btn, .page-actions .btn")).find((b) => (b.textContent || "").trim() === "Rollback Workflow State")`;

async function waitForRollbackButton(page, timeoutMs = 90000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const has = await page.evaluate(
      (findBtnSrc) => !!eval(findBtnSrc)(),
      FIND_ROLLBACK_BTN
    );
    if (has) {
      return true;
    }
    await page.waitForTimeout(500);
  }
  return false;
}

async function openRollbackDialog(page) {
  if (!(await waitForRollbackButton(page))) {
    return { ok: false, step: "no_button" };
  }
  return page.evaluate(async (findBtnSrc) => {
    const findBtn = eval(findBtnSrc);
    const btn = findBtn();
    if (!btn) return { ok: false, step: "no_button" };
    btn.click();
    await new Promise((r) => setTimeout(r, 700));
    const dialog =
      document.querySelector(".modal.show .modal-dialog") ||
      Array.from(document.querySelectorAll(".modal-dialog")).find((el) =>
        el.closest(".modal")?.classList.contains("show")
      );
    if (!dialog) return { ok: false, step: "no_dialog" };
    const title = (
      dialog.querySelector(".modal-title")?.textContent || ""
    ).trim();
    if (title !== "Rollback Workflow State")
      return { ok: false, step: "bad_title", title };
    return { ok: true };
  }, FIND_ROLLBACK_BTN);
}

async function rollbackViaUi(
  page,
  pdcName,
  targetState,
  reason,
  { confirm = true } = {}
) {
  if (!(await waitForRollbackButton(page))) {
    return { ok: false, step: "no_button", pdc_name: pdcName };
  }
  const stateBeforeDb = pdcStateFromDb(pdcName);
  const out = await page.evaluate(
    async ({ findBtnSrc, targetState, reason, confirm }) => {
      const findBtn = eval(findBtnSrc);
      const btn = findBtn();
      if (!btn) return { ok: false, step: "no_button" };
      btn.click();
      const waitDialog = async () => {
        for (let i = 0; i < 80; i++) {
          if (window.cur_dialog?.display) {
            return window.cur_dialog;
          }
          await new Promise((r) => setTimeout(r, 100));
        }
        return null;
      };
      const d = await waitDialog();
      if (!d) return { ok: false, step: "no_dialog" };
      const workflowBefore = window.cur_frm?.doc?.workflow_state;
      await d.set_value("target_state", targetState);
      await new Promise((r) => setTimeout(r, 1200));
      const preview = (
        d.fields_dict.preview_html?.$wrapper?.html() || ""
      ).trim();
      await d.set_value("rollback_reason", reason);
      if (!confirm) {
        d.hide();
        return {
          ok: true,
          preview,
          confirmed: false,
          workflow_before: workflowBefore,
          target_state: targetState,
        };
      }
      const targetFromDialog = d.get_value("target_state") || targetState;
      const reasonFromDialog = (
        d.get_value("rollback_reason") ||
        reason ||
        ""
      ).trim();
      if (!reasonFromDialog) {
        return {
          ok: false,
          step: "no_reason",
          workflow_before: workflowBefore,
        };
      }
      let apiResult;
      try {
        const res = await frappe.call({
          method:
            "erpnext_extensions.cheque_management.pdc_workflow_rollback.rollback_workflow_state",
          args: {
            pdc_name: window.cur_frm.doc.name,
            target_state: targetFromDialog,
            reason: reasonFromDialog,
          },
          freeze: true,
        });
        d.hide();
        const msg = res.message || {};
        const workflowAfterApiMessage =
          msg.workflow_state || msg.to_workflow_state || null;
        let workflowAfterReload = null;
        try {
          await cur_frm.reload_doc();
          workflowAfterReload = cur_frm.doc?.workflow_state ?? null;
        } catch (reloadErr) {
          workflowAfterReload = `reload_error:${
            reloadErr.message || reloadErr
          }`;
        }
        apiResult = {
          ok: workflowAfterApiMessage === targetFromDialog,
          step:
            workflowAfterApiMessage === targetFromDialog
              ? "api_ok"
              : "api_state_mismatch",
          api_response: msg,
          target_state: targetFromDialog,
          workflow_after_api_message: workflowAfterApiMessage,
          workflow_after_reload: workflowAfterReload,
        };
      } catch (err) {
        apiResult = {
          ok: false,
          step: "api_error",
          error: err?.message || String(err),
          target_state: targetFromDialog,
        };
      }
      return {
        ...apiResult,
        workflow_before: workflowBefore,
        preview,
        confirmed: true,
      };
    },
    { findBtnSrc: FIND_ROLLBACK_BTN, targetState, reason, confirm }
  );
  if (!out.confirmed) {
    return { ...out, pdc_name: pdcName, db_before: stateBeforeDb };
  }
  if (!out.ok) {
    return {
      ...out,
      pdc_name: pdcName,
      db_before: stateBeforeDb,
      db_after: pdcStateFromDb(pdcName),
    };
  }
  const dbImmediatelyAfterApi = pdcStateFromDb(pdcName);
  const waitResult = await waitPdcWorkflowState(pdcName, targetState);
  const dbAfter = waitResult.state;
  await openPdc(page, pdcName);
  const uiAfter = await page.evaluate(() => ({
    workflow_state: window.cur_frm?.doc?.workflow_state,
    docstatus: window.cur_frm?.doc?.docstatus,
  }));
  const ok = Boolean(
    out.ok &&
      waitResult.ok &&
      dbAfter?.workflow_state === targetState &&
      dbImmediatelyAfterApi?.workflow_state === targetState
  );
  return {
    ...out,
    pdc_name: pdcName,
    db_before: stateBeforeDb,
    db_immediately_after_api: dbImmediatelyAfterApi,
    db_after: dbAfter,
    wait: waitResult,
    ui_after: uiAfter,
    workflow_state: dbAfter?.workflow_state,
    ok,
    debug: ok
      ? null
      : buildFailureDebug({
          test: "rollbackViaUi",
          doctype: PDC,
          name: pdcName,
          expected: { workflow_state: targetState },
          dbBefore: stateBeforeDb,
          dbAfter,
          ui: uiAfter,
          serverResponse: out.api_response,
          waitMeta: waitResult,
        }),
  };
}

async function run() {
  const prep = benchExecute(
    "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.prepare_pdc_workflow_rollback_e2e"
  );
  const results = [];
  const evidence = { screenshots: {}, prep, sql: {} };

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    locale: "en-US",
    viewport: { width: 1600, height: 950 },
  });
  const page = await context.newPage();
  page.setDefaultTimeout(180000);
  const jsErrors = [];
  page.on("pageerror", (err) => jsErrors.push(String(err)));

  try {
    await login(page, "Administrator", "admin");

    // D: Issued payable — no Cancel Cheque / Cancel Issued Payable (before B mutates this PDC)
    await openPdc(page, prep.payable_issued);
    const dServerActions = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_list_workflow_actions",
      { pdc_name: prep.payable_issued }
    );
    const dUiActions = await collectWorkflowActionLabels(page);
    const dStdCancel = await standardFrappeCancelButtonVisible(page);
    const dRollback = await waitForRollbackButton(page, 20000);
    evidence.screenshots.D = await shot(
      page,
      "D_issued_workflow_without_cancel_actions"
    );
    results.push({
      test: "D_no_cancel_workflow_actions",
      ok:
        !hasCancelWorkflowAction(dServerActions) &&
        !hasCancelWorkflowAction(dUiActions) &&
        !dStdCancel &&
        dRollback,
      dServerActions,
      dUiActions,
      dStdCancel,
      dRollback,
    });

    const cancelBlock = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_attempt_direct_cancel",
      { pdc_name: prep.payable_cleared_preview }
    );
    results.push({
      test: "STD_server_direct_cancel_blocked",
      ok:
        cancelBlock.blocked &&
        (cancelBlock.message || "").includes("Rollback Workflow State") &&
        cancelBlock.before?.docstatus === cancelBlock.after?.docstatus &&
        cancelBlock.before?.workflow_state ===
          cancelBlock.after?.workflow_state,
      cancelBlock,
    });

    const clientCancel = await page.evaluate(async (pdcName) => {
      try {
        await frappe.call({
          method: "frappe.client.cancel",
          args: { doctype: "Post Dated Cheque", name: pdcName },
        });
        return { blocked: false };
      } catch (e) {
        return { blocked: true, msg: e.message || String(e) };
      }
    }, prep.payable_cleared_double);
    results.push({
      test: "STD_client_cancel_blocked",
      ok: clientCancel.blocked,
      clientCancel,
    });

    // A: Registered → Draft
    await openPdc(page, prep.payable_registered);
    const a1 = await waitForRollbackButton(page);
    const aDbBefore = pdcStateFromDb(prep.payable_registered);
    evidence.screenshots.A0 = await shot(page, "A_registered_button_visible");
    const a = await rollbackViaUi(
      page,
      prep.payable_registered,
      "Draft",
      "E2E rollback A"
    );
    evidence.screenshots.A1 = await shot(page, "A_registered_to_draft");
    evidence.sql.A = sqlVerify(prep.payable_registered);
    const aDebug = {
      test: "A_registered_to_draft",
      pdc_name: prep.payable_registered,
      target_state: "Draft",
      workflow_state_before_rollback: aDbBefore?.workflow_state,
      workflow_state_ui_before: a.workflow_before,
      rollback_api_response: a.api_response,
      workflow_state_after_api_message: a.workflow_after_api_message,
      workflow_state_after_frm_reload: a.workflow_after_reload,
      workflow_state_db_immediately_after_api:
        a.db_immediately_after_api?.workflow_state,
      workflow_state_db_after_wait: a.db_after?.workflow_state,
      workflow_state_ui_after_open: a.ui_after?.workflow_state,
      rollback_step: a.step,
      db_before: aDbBefore,
      db_after: a.db_after,
      wait: a.wait,
      rollback_out: a,
    };
    results.push({
      test: "A_registered_to_draft",
      ok:
        a1 &&
        a.ok &&
        aDbBefore?.workflow_state === "Registered" &&
        a.db_after?.workflow_state === "Draft" &&
        evidence.sql.A.clean,
      a: aDebug,
    });

    // B: Issued → Registered
    await openPdc(page, prep.payable_issued);
    evidence.screenshots.B0 = await shot(page, "B_issued_loaded");
    const b = await rollbackViaUi(
      page,
      prep.payable_issued,
      "Registered",
      "E2E rollback B"
    );
    evidence.screenshots.B1 = await shot(page, "B_issued_to_registered");
    evidence.sql.B = sqlVerify(prep.payable_issued);
    results.push({
      test: "B_issued_to_registered",
      ok:
        b.ok &&
        b.db_after?.workflow_state === "Registered" &&
        evidence.sql.B.clean,
      b,
    });

    // Opening import: at Registered baseline — no rollback button
    await openPdc(page, prep.opening_import_payable_registered);
    const oiBaselineBtn = await waitForRollbackButton(page, 12000);
    evidence.screenshots.OI_baseline_registered = await shot(
      page,
      "OI_opening_import_at_baseline_no_rollback"
    );

    // Opening import: Cleared → preview shows baseline notice → rollback to Issued
    await openPdc(page, prep.opening_import_payable_cleared);
    const oiPreview = await rollbackViaUi(
      page,
      prep.opening_import_payable_cleared,
      "Issued",
      "E2E OI rollback preview",
      { confirm: false }
    );
    evidence.screenshots.OI_baseline_notice = await shot(
      page,
      "OI_opening_import_rollback_preview_notice"
    );
    const oiRollback = await rollbackViaUi(
      page,
      prep.opening_import_payable_cleared,
      "Issued",
      "E2E OI rollback execute"
    );
    evidence.sql.OI = sqlVerify(prep.opening_import_payable_cleared);
    evidence.screenshots.OI_post_rollback = await shot(
      page,
      "OI_opening_import_rollback_cleared_to_issued"
    );
    results.push({
      test: "OI_opening_import_baseline_and_rollback",
      ok:
        !oiBaselineBtn &&
        oiPreview.ok &&
        (oiPreview.preview || "").toLowerCase().includes("import") &&
        oiRollback.ok &&
        oiRollback.db_after?.workflow_state === "Issued" &&
        evidence.sql.OI.clean,
      oiBaselineBtn,
      oiPreview,
      oiRollback,
    });

    // OI-PAY-ISSUED: import at Issued baseline → clear → rollback to Issued only
    const oiIssuedBaselineDb = pdcStateFromDb(
      prep.opening_import_payable_issued_baseline
    );
    const oiIssuedBaselineTargets = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_get_rollback_targets",
      { pdc_name: prep.opening_import_payable_issued_baseline }
    ).targets;
    await openPdc(page, prep.opening_import_payable_issued_baseline);
    const oiIssuedBaselineBtn = await waitForRollbackButton(page, 8000);
    evidence.screenshots.OI_PAY_ISSUED_baseline = await shot(
      page,
      "OI_PAY_ISSUED_at_baseline"
    );

    const oiIssuedClearedDbBefore = pdcStateFromDb(
      prep.opening_import_payable_issued
    );
    const oiIssuedTargets = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_get_rollback_targets",
      { pdc_name: prep.opening_import_payable_issued }
    ).targets;
    await openPdc(page, prep.opening_import_payable_issued);
    const oiIssuedRollback = await rollbackViaUi(
      page,
      prep.opening_import_payable_issued,
      "Issued",
      "E2E OI-PAY-ISSUED rollback"
    );
    const oiIssuedDbAfter = await waitPdcWorkflowState(
      prep.opening_import_payable_issued,
      "Issued"
    );
    const oiIssuedTargetsAfter = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_get_rollback_targets",
      { pdc_name: prep.opening_import_payable_issued }
    ).targets;
    evidence.sql.OI_PAY_ISSUED = sqlVerify(prep.opening_import_payable_issued);
    evidence.screenshots.OI_PAY_ISSUED_post = await shot(
      page,
      "OI_PAY_ISSUED_post_rollback"
    );
    results.push({
      test: "OI_PAY_ISSUED_baseline_clear_rollback",
      ok:
        oiIssuedBaselineDb.workflow_state === "Issued" &&
        (oiIssuedBaselineTargets || []).length === 0 &&
        !oiIssuedBaselineBtn &&
        oiIssuedClearedDbBefore.workflow_state === "Cleared" &&
        JSON.stringify(oiIssuedTargets || []) === JSON.stringify(["Issued"]) &&
        oiIssuedRollback.ok &&
        oiIssuedDbAfter.state?.workflow_state === "Issued" &&
        (oiIssuedTargetsAfter || []).length === 0 &&
        evidence.sql.OI_PAY_ISSUED.clean,
      oiIssuedBaselineDb,
      oiIssuedBaselineTargets,
      oiIssuedTargets,
      oiIssuedRollback,
      oiIssuedDbAfter,
      oiIssuedTargetsAfter,
    });

    // OI-PAY-CLEARED: import directly at Cleared — no rollback targets
    const oiClearedBaselineTargets = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_get_rollback_targets",
      { pdc_name: prep.opening_import_payable_cleared_baseline }
    ).targets;
    await openPdc(page, prep.opening_import_payable_cleared_baseline);
    const oiClearedBaselineBtn = await waitForRollbackButton(page, 8000);
    evidence.screenshots.OI_PAY_CLEARED = await shot(
      page,
      "OI_PAY_CLEARED_baseline"
    );
    results.push({
      test: "OI_PAY_CLEARED_no_rollback",
      ok:
        (oiClearedBaselineTargets || []).length === 0 &&
        !oiClearedBaselineBtn &&
        pdcStateFromDb(prep.opening_import_payable_cleared_baseline)
          .workflow_state === "Cleared",
      oiClearedBaselineTargets,
      oiClearedBaselineBtn,
    });

    await openPdc(page, prep.payable_returned);
    const e = await rollbackViaUi(
      page,
      prep.payable_returned,
      "Issued",
      "E2E rollback E"
    );
    evidence.screenshots.E = await shot(page, "E_returned_to_issued");
    results.push({
      test: "E_returned_to_issued",
      ok: e.ok && e.db_after?.workflow_state === "Issued",
      e,
    });

    // F: Cancelled is docstatus 2 — rollback is not offered (legacy fixture, not workflow Cancel).
    await openPdc(page, prep.payable_cancelled);
    const fDoc = await page.evaluate(() => ({
      workflow_state: window.cur_frm?.doc?.workflow_state,
      docstatus: window.cur_frm?.doc?.docstatus,
    }));
    const fHasBtn = await waitForRollbackButton(page, 15000);
    const fUiActions = await collectWorkflowActionLabels(page);
    const fStdCancel = await standardFrappeCancelButtonVisible(page);
    evidence.screenshots.F = await shot(page, "F_legacy_cancelled_pdc_open");
    results.push({
      test: "F_cancelled_terminal_no_rollback",
      ok:
        fDoc.workflow_state === "Cancelled" &&
        fDoc.docstatus === 2 &&
        !fHasBtn &&
        !hasCancelWorkflowAction(fUiActions) &&
        !fStdCancel &&
        jsErrors.length === 0,
      f: {
        ...fDoc,
        has_button: fHasBtn,
        ui_actions: fUiActions,
        js_errors: jsErrors,
        std_cancel: fStdCancel,
      },
    });

    await openPdc(page, prep.payable_cleared_double);
    const j1 = await rollbackViaUi(
      page,
      prep.payable_cleared_double,
      "Issued",
      "E2E rollback J1"
    );
    const j2 = await page.evaluate(async (pdcName) => {
      try {
        await frappe.call({
          method:
            "erpnext_extensions.cheque_management.pdc_workflow_rollback.rollback_workflow_state",
          args: {
            pdc_name: pdcName,
            target_state: "Issued",
            reason: "duplicate",
          },
        });
        return { rejected: false };
      } catch (err) {
        return { rejected: true, msg: err.message || String(err) };
      }
    }, prep.payable_cleared_double);
    evidence.screenshots.J = await shot(page, "J_double_rollback");
    results.push({
      test: "J_rollback_twice_second_rejected",
      ok: j1.ok && j1.db_after?.workflow_state === "Issued" && j2.rejected,
      j1,
      j2,
    });

    // H: Rollback preview (no confirm)
    await openPdc(page, prep.payable_cleared_preview);
    const h = await rollbackViaUi(
      page,
      prep.payable_cleared_preview,
      "Issued",
      "E2E preview H",
      {
        confirm: false,
      }
    );
    evidence.screenshots.H = await shot(page, "H_preview_dialog");
    results.push({
      test: "H_rollback_preview",
      ok:
        h.ok &&
        (h.preview || "").includes("Workflow") &&
        (h.preview || "").includes("Accounting"),
      h,
    });

    // C/D: Cleared → Issued → Registered → Draft
    await openPdc(page, prep.payable_cleared);
    evidence.screenshots.C0 = await shot(page, "C_cleared_loaded");
    const c1 = await rollbackViaUi(
      page,
      prep.payable_cleared,
      "Issued",
      "E2E rollback C1"
    );
    evidence.sql.C1 = sqlVerify(prep.payable_cleared);
    evidence.screenshots.C1 = await shot(page, "C_cleared_to_issued");
    const c2 = await rollbackViaUi(
      page,
      prep.payable_cleared,
      "Registered",
      "E2E rollback C2"
    );
    evidence.sql.C2 = sqlVerify(prep.payable_cleared);
    evidence.screenshots.C2 = await shot(page, "C_issued_to_registered");
    const c3 = await rollbackViaUi(
      page,
      prep.payable_cleared,
      "Draft",
      "E2E rollback C3"
    );
    evidence.sql.C3 = sqlVerify(prep.payable_cleared);
    evidence.screenshots.C3 = await shot(page, "C_registered_to_draft");
    await page.evaluate(() => {
      const sidebar = document.querySelector(".form-sidebar");
      const link = sidebar
        ? Array.from(
            sidebar.querySelectorAll(
              "a, button, .sidebar-item, .standard-sidebar-item"
            )
          ).find((el) => (el.textContent || "").trim().includes("Timeline"))
        : null;
      link?.click();
    });
    await page.waitForTimeout(1500);
    evidence.screenshots.T_timeline = await shot(
      page,
      "T_timeline_workflow_comments"
    );
    results.push({
      test: "C_D_cleared_to_draft_multistep",
      ok:
        c1.ok &&
        c2.ok &&
        c3.ok &&
        c1.db_after?.workflow_state === "Issued" &&
        c2.db_after?.workflow_state === "Registered" &&
        c3.db_after?.workflow_state === "Draft" &&
        evidence.sql.C1.clean &&
        evidence.sql.C2.clean &&
        evidence.sql.C3.clean,
      c1,
      c2,
      c3,
    });

    // K: forward workflow after rollback (Register Cheque)
    const kForward = benchExecute(
      "erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_forward_register_after_rollback",
      { pdc_name: prep.payable_cleared }
    );
    await openPdc(page, prep.payable_cleared);
    evidence.screenshots.K = await shot(
      page,
      "K_forward_registered_after_rollback"
    );
    results.push({
      test: "K_rollback_then_forward",
      ok: kForward.ok && kForward.workflow_state === "Registered",
      kForward,
    });

    await openPdc(page, prep.payable_cleared);
    const i = await page.evaluate(() => {
      const section = document.querySelector(
        '[data-fieldname="workflow_rollback_logs"]'
      );
      const rows = section?.querySelectorAll(".grid-row")?.length || 0;
      return { has: !!section, rows };
    });
    evidence.screenshots.I = await shot(page, "I_rollback_history");
    results.push({ test: "I_rollback_history", ok: i.has && i.rows >= 3, i });

    // G: Permission (fresh context — logout/login page is unreliable in one session)
    await context.close();
    const ctx2 = await browser.newContext({
      locale: "en-US",
      viewport: { width: 1600, height: 950 },
    });
    const pageG = await ctx2.newPage();
    pageG.setDefaultTimeout(180000);
    await login(
      pageG,
      prep.accounts_user,
      process.env.FRAPPE_E2E_PASSWORD || "admin"
    );
    if (pageG.url().includes("/login")) {
      throw new Error(`E2E denied user login failed for ${prep.accounts_user}`);
    }
    await pageG.goto(
      `${BASE}/app/post-dated-cheque/${encodeURIComponent(
        prep.receivable_cleared
      )}`,
      {
        waitUntil: "load",
        timeout: 180000,
      }
    );
    await pageG.waitForTimeout(4000);
    const gUi = await pageG.evaluate(
      (findBtnSrc) => ({ has: !!eval(findBtnSrc)() }),
      FIND_ROLLBACK_BTN
    );
    const gServer = await pageG.evaluate(async (pdcName) => {
      if (typeof frappe === "undefined") {
        return { rejected: true, msg: "no desk session" };
      }
      try {
        await frappe.call({
          method:
            "erpnext_extensions.cheque_management.pdc_workflow_rollback.rollback_workflow_state",
          args: {
            pdc_name: pdcName,
            target_state: "Issued",
            reason: "should fail",
          },
        });
        return { rejected: false };
      } catch (e) {
        return { rejected: true, msg: e.message || String(e) };
      }
    }, prep.receivable_cleared);
    evidence.screenshots.G = await shot(pageG, "G_non_privileged_no_button");
    await ctx2.close();
    results.push({
      test: "G_permission_no_button_and_server_reject",
      ok: !gUi.has && gServer.rejected,
      gUi,
      gServer,
    });
  } finally {
    await browser.close();
  }

  const all_ok = results.every((r) => r.ok);
  const sqlSummary = Object.fromEntries(
    Object.entries(evidence.sql).map(([k, v]) => [
      k,
      { clean: v?.clean, pdc_name: v?.pdc_name },
    ])
  );
  console.log(
    JSON.stringify(
      { all_ok, results, evidence: { ...evidence, sql: sqlSummary } },
      null,
      2
    )
  );
  process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
  console.error(e);
  process.exit(1);
});
