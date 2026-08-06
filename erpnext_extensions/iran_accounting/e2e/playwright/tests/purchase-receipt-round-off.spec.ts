import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { captureStep } from "../src/utils/screenshots";
import { frappeCall } from "../src/utils/frappe-api";

const METHOD = "erpnext_extensions.iran_accounting.e2e_round_off_ui";

async function callMethod(page: import("@playwright/test").Page, method: string, args: Record<string, unknown> = {}) {
  return frappeCall(page, `${METHOD}.${method}`, args);
}

function attachMonitors(page: import("@playwright/test").Page) {
  const consoleErrors: { text: string }[] = [];
  const failedNet: { url: string; status: number }[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push({ text: msg.text() });
  });
  page.on("response", (res) => {
    if (res.status() >= 400) failedNet.push({ url: res.url(), status: res.status() });
  });
  return { consoleErrors, failedNet };
}

async function openPurchaseReceipt(page: import("@playwright/test").Page, name: string) {
  await page.goto(`/desk/purchase-receipt/${encodeURIComponent(name)}`, {
    waitUntil: "domcontentloaded",
  });
  await page.waitForFunction(
    () =>
      (window as unknown as { cur_frm?: { doc?: { doctype?: string; name?: string } } }).cur_frm?.doc
        ?.doctype === "Purchase Receipt",
    { timeout: 120_000 }
  );
}

async function armAutoConfirmSubmit(page: import("@playwright/test").Page) {
  await page.evaluate(() => {
    const w = window as unknown as {
      frappe: { confirm: (msg: string, yes?: () => void) => void };
    };
    w.frappe.confirm = (_msg, yes) => {
      if (typeof yes === "function") yes();
    };
  });
}

/** Desk savedocs Submit — same path as the Submit button, without frm.savesubmit navigation races. */
async function deskSubmit(page: import("@playwright/test").Page): Promise<{ ok: boolean; message: string }> {
  await armAutoConfirmSubmit(page);
  return page.evaluate(async () => {
    const w = window as unknown as {
      cur_frm: { doc: Record<string, unknown> };
      frappe: {
        call: (opts: Record<string, unknown>) => Promise<{ message?: unknown; _server_messages?: string; exc?: string }>;
        parse_json?: (s: string) => unknown;
      };
    };
    try {
      await w.frappe.call({
        method: "frappe.desk.form.save.savedocs",
        args: {
          action: "Submit",
          doc: JSON.stringify(w.cur_frm.doc),
        },
        freeze: false,
      });
      return { ok: true, message: "" };
    } catch (e: unknown) {
      const err = e as { message?: string; _server_messages?: string; responseJSON?: { _server_messages?: string } };
      let detail = err?.message || "";
      const raw = err?._server_messages || err?.responseJSON?._server_messages;
      if (raw) {
        try {
          const arr = JSON.parse(raw);
          detail = (Array.isArray(arr) ? arr : [arr])
            .map((x: unknown) => {
              if (typeof x === "string") {
                try {
                  return JSON.parse(x).message;
                } catch {
                  return x;
                }
              }
              return String(x);
            })
            .join("\n");
        } catch {
          detail = String(raw);
        }
      }
      return { ok: false, message: String(detail || e) };
    }
  });
}

async function uiSubmitExpectError(page: import("@playwright/test").Page): Promise<string> {
  const res = await deskSubmit(page);
  return res.ok ? "" : res.message;
}

async function uiSubmitExpectOk(page: import("@playwright/test").Page): Promise<void> {
  const res = await deskSubmit(page);
  if (!res.ok) {
    throw new Error(`Submit failed: ${res.message}`);
  }
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (window as unknown as { cur_frm?: { doc?: { docstatus?: number } } }).cur_frm?.doc?.docstatus === 1,
    { timeout: 180_000 }
  );
}

test.describe("Purchase Receipt Class A/B Round Off UI @release-blocking", () => {
  test("Class B blocks submit without Round Off / Stock Adjustment / AD default messaging", async ({
    page,
    loginPage,
  }) => {
    const mon = attachMonitors(page);
    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    const prep = await callMethod(page, "ensure_round_off_ui_prerequisites", {
      company: erpnextConfig.company,
    });
    let prName = "";
    try {
      await callMethod(page, "set_company_round_off_department_default", {
        company: prep.company,
        department: "",
      });
      const draft = await callMethod(page, "create_class_b_pr_draft", { company: prep.company });
      prName = draft.name;
      expect(draft.decision_status).toBe("class_b_error");

      await openPurchaseReceipt(page, prName);
      await captureStep(page, "pr_class_b_01_open");
      const err = await uiSubmitExpectError(page);
      expect(err.toLowerCase()).toMatch(/class b|valuation inconsistency/);
      expect(err.toLowerCase()).not.toMatch(/accounting dimension default|general department|round off dimension defaults/);
      await captureStep(page, "pr_class_b_02_blocked");

      const snap = await callMethod(page, "get_pr_ledger_snapshot", { voucher_no: prName });
      expect(snap.docstatus).toBe(0);
      expect(snap.residual_count).toBe(0);
      expect(snap.sa_rows.length).toBe(0);
      expect(snap.gl_count).toBe(0);
      expect(snap.sle_count).toBe(0);

      const uiDoc = await page.evaluate(() => {
        const d = (window as unknown as { cur_frm: { doc: { docstatus: number; name: string } } }).cur_frm.doc;
        return { docstatus: d.docstatus, name: d.name };
      });
      expect(uiDoc.docstatus).toBe(0);

      const unexpected = mon.failedNet.filter(
        (f) =>
          f.status >= 500 &&
          !/savesubmit|run_doc_method|frappe.desk.form.save|socket\.io/.test(f.url)
      );
      // Ignore expected Desk validation noise; block only hard page errors with stack traces
      const hardConsole = mon.consoleErrors.filter(
        (e) => /TypeError|ReferenceError|SyntaxError/.test(e.text)
      );
      expect(hardConsole, JSON.stringify(hardConsole)).toEqual([]);
      expect(unexpected, JSON.stringify(unexpected)).toEqual([]);
    } finally {
      try {
        if (prName) await callMethod(page, "cancel_and_delete_pr", { voucher_no: prName });
      } catch (e) {
        console.warn("cleanup PR", e);
      }
      try {
        await callMethod(page, "restore_round_off_ui_prerequisites", { payload: prep });
      } catch (e) {
        console.warn("restore prep", e);
      }
    }
  });

  test("Class A header Department, Company default, missing default, and RIV×2", async ({
    page,
    loginPage,
  }) => {
    const mon = attachMonitors(page);
    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    const prep = await callMethod(page, "ensure_round_off_ui_prerequisites", {
      company: erpnextConfig.company,
    });
    const company = prep.company as string;
    const department = prep.department as string;
    const created: string[] = [];

    try {
      // --- A) Header Department ---
      await callMethod(page, "set_company_round_off_department_default", {
        company,
        department: "",
      });
      const headerDraft = await callMethod(page, "create_class_a_pr", {
        company,
        mode: "header",
        department,
        submit: 0,
      });
      created.push(headerDraft.name);
      expect(headerDraft.pre_submit_status).toBe("ready");
      expect(headerDraft.net_signed_debit).toBe(1);

      await openPurchaseReceipt(page, headerDraft.name);
      await captureStep(page, "pr_class_a_header_01_open");
      await uiSubmitExpectOk(page);
      await captureStep(page, "pr_class_a_header_02_submitted");

      let snap = await callMethod(page, "get_pr_ledger_snapshot", { voucher_no: headerDraft.name });
      expect(snap.docstatus).toBe(1);
      expect(snap.gl_balanced).toBeTruthy();
      expect(snap.residual_count).toBe(1);
      expect(snap.account_on_residual).toBe(prep.round_off_account);
      expect(snap.cost_center_on_residual).toBe(prep.round_off_cost_center);
      expect(snap.department_on_residual).toBe(department);
      expect(snap.sa_rows.length).toBe(0);
      expect(snap.sle_count).toBe(1);

      // RIV ×2 immediately on header fixture (before other scenarios clear Company defaults)
      const riv1 = await callMethod(page, "run_riv_for_pr", { voucher_no: headerDraft.name });
      expect(riv1.rivs, JSON.stringify(riv1.rivs)).toEqual(
        expect.arrayContaining([expect.objectContaining({ status: "Completed" })])
      );
      expect(riv1.ledger.residual_count).toBe(1);
      expect(riv1.ledger.account_on_residual).toBe(prep.round_off_account);
      expect(riv1.ledger.cost_center_on_residual).toBe(prep.round_off_cost_center);
      expect(riv1.ledger.department_on_residual).toBe(department);
      expect(riv1.ledger.sa_rows.length).toBe(0);

      const riv2 = await callMethod(page, "run_riv_for_pr", { voucher_no: headerDraft.name });
      expect(riv2.rivs, JSON.stringify(riv2.rivs)).toEqual(
        expect.arrayContaining([expect.objectContaining({ status: "Completed" })])
      );
      expect(riv2.ledger.residual_count).toBe(1);
      expect(riv2.ledger.account_on_residual).toBe(prep.round_off_account);
      expect(riv2.ledger.cost_center_on_residual).toBe(prep.round_off_cost_center);
      expect(riv2.ledger.department_on_residual).toBe(department);
      expect(riv2.ledger.sa_rows.length).toBe(0);
      expect(riv2.ledger.gl_balanced).toBeTruthy();

      await openPurchaseReceipt(page, headerDraft.name);
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.waitForFunction(
        () => (window as unknown as { cur_frm?: { doc?: { docstatus?: number } } }).cur_frm?.doc?.docstatus === 1,
        { timeout: 120_000 }
      );
      await captureStep(page, "pr_class_a_riv_01_stable");

      // --- B) Company default ---
      await callMethod(page, "set_company_round_off_department_default", {
        company,
        department,
      });
      const companyDraft = await callMethod(page, "create_class_a_pr", {
        company,
        mode: "company_default",
        department: "",
        submit: 0,
      });
      created.push(companyDraft.name);
      expect(companyDraft.pre_submit_status).toBe("ready");

      await openPurchaseReceipt(page, companyDraft.name);
      await uiSubmitExpectOk(page);
      snap = await callMethod(page, "get_pr_ledger_snapshot", { voucher_no: companyDraft.name });
      expect(snap.residual_count).toBe(1);
      expect(snap.department_on_residual).toBe(department);
      expect(snap.account_on_residual).toBe(prep.round_off_account);
      expect(snap.cost_center_on_residual).toBe(prep.round_off_cost_center);
      expect(snap.sa_rows.length).toBe(0);
      await captureStep(page, "pr_class_a_company_01_ok");

      // --- C) Missing dimension ---
      await callMethod(page, "set_company_round_off_department_default", {
        company,
        department: "",
      });
      const missingDraft = await callMethod(page, "create_class_a_pr", {
        company,
        mode: "missing",
        department: "",
        submit: 0,
      });
      created.push(missingDraft.name);
      expect(missingDraft.pre_submit_status).toBe("config_error");

      await openPurchaseReceipt(page, missingDraft.name);
      const missErr = await uiSubmitExpectError(page);
      expect(missErr).toMatch(/Round Off Dimension Defaults/);
      expect(missErr.toLowerCase()).not.toMatch(/default_dimension/);
      expect(missErr.toLowerCase()).not.toMatch(/accounting dimension default/);
      const missSnap = await callMethod(page, "get_pr_ledger_snapshot", { voucher_no: missingDraft.name });
      expect(missSnap.docstatus).toBe(0);
      expect(missSnap.gl_count).toBe(0);
      await captureStep(page, "pr_class_a_missing_01_blocked");

      const hardConsole = mon.consoleErrors.filter((e) =>
        /TypeError|ReferenceError|SyntaxError/.test(e.text)
      );
      expect(hardConsole, JSON.stringify(hardConsole)).toEqual([]);
    } finally {
      for (const name of created.reverse()) {
        try {
          await callMethod(page, "cancel_and_delete_pr", { voucher_no: name });
        } catch (e) {
          console.warn("cleanup PR", name, e);
        }
      }
      try {
        await callMethod(page, "restore_round_off_ui_prerequisites", { payload: prep });
      } catch (e) {
        console.warn("restore prep", e);
      }
    }
  });
});
