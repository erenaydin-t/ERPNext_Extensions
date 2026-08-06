import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { captureStep } from "../src/utils/screenshots";
import { frappeCall } from "../src/utils/frappe-api";

const METHOD = "erpnext_extensions.iran_accounting.e2e_round_off_ui";

async function callMethod(page: import("@playwright/test").Page, method: string, args: Record<string, unknown> = {}) {
  return frappeCall(page, `${METHOD}.${method}`, args);
}

async function openCompany(page: import("@playwright/test").Page, company: string) {
  await page.goto(`/desk/company/${encodeURIComponent(company)}`, { waitUntil: "domcontentloaded" });
  await page.waitForFunction(
    () => (window as unknown as { cur_frm?: { doc?: { doctype?: string } } }).cur_frm?.doc?.doctype === "Company",
    { timeout: 120_000 }
  );
}

async function saveCompanyForm(page: import("@playwright/test").Page): Promise<{ ok: boolean; message: string; rowCount?: number }> {
  return page.evaluate(async () => {
    const w = window as unknown as {
      cur_frm: {
        doc: { round_off_dimension_defaults?: unknown[] } & Record<string, unknown>;
        reload_doc: () => Promise<unknown>;
      };
      frappe: {
        call: (o: Record<string, unknown>) => Promise<{ message?: unknown; exc?: string; _server_messages?: string }>;
        request?: { xhr?: unknown };
      };
    };
    const rowCount = (w.cur_frm.doc.round_off_dimension_defaults || []).length;
    try {
      const r = await w.frappe.call({
        method: "frappe.desk.form.save.savedocs",
        args: { action: "Save", doc: JSON.stringify(w.cur_frm.doc) },
        freeze: false,
      });
      if ((r as { exc?: string })?.exc) {
        return { ok: false, message: String((r as { exc?: string }).exc), rowCount };
      }
      await w.cur_frm.reload_doc();
      return { ok: true, message: "", rowCount };
    } catch (e: unknown) {
      const err = e as {
        message?: string;
        _server_messages?: string;
        responseJSON?: { _server_messages?: string; exc?: string };
        status?: number;
      };
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
      return { ok: false, message: String(detail || e), rowCount };
    }
  });
}

test.describe("Company Round Off Dimension Defaults UI @release-blocking", () => {
  test("child table CRUD, persistence, duplicate and forbidden values", async ({ page, loginPage }) => {
    const consoleErrors: { text: string }[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push({ text: msg.text() });
    });

    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    const prep = await callMethod(page, "ensure_round_off_ui_prerequisites", {
      company: erpnextConfig.company,
    });
    const company = prep.company as string;
    const department = prep.department as string;
    const adBefore = await callMethod(page, "get_ad_default_dimension", {
      company,
      document_type: "Department",
    });

    try {
      await openCompany(page, company);
      await captureStep(page, "ro_company_01_open");

      const ui0 = await page.evaluate(() => {
        const frm = (
          window as unknown as {
            cur_frm: { doc: Record<string, unknown>; fields_dict: Record<string, unknown> };
          }
        ).cur_frm;
        return { hasField: !!frm.fields_dict.round_off_dimension_defaults };
      });
      expect(ui0.hasField, "Round Off Dimension Defaults field visible").toBeTruthy();

      await page.evaluate(() => {
        const frm = (
          window as unknown as {
            cur_frm: { clear_table: (f: string) => void; refresh_field: (f: string) => void };
          }
        ).cur_frm;
        frm.clear_table("round_off_dimension_defaults");
        frm.refresh_field("round_off_dimension_defaults");
      });

      const addResult = await page.evaluate(({ department }) => {
        const frm = (
          window as unknown as {
            cur_frm: {
              add_child: (f: string, v: Record<string, unknown>) => Record<string, unknown>;
              refresh_field: (f: string) => void;
            };
          }
        ).cur_frm;
        const row = frm.add_child("round_off_dimension_defaults", {
          accounting_dimension: "department",
          reference_doctype: "Department",
          default_value: department,
        });
        frm.refresh_field("round_off_dimension_defaults");
        return {
          accounting_dimension: row.accounting_dimension,
          reference_doctype: row.reference_doctype,
          default_value: row.default_value,
        };
      }, { department });
      const saved = await saveCompanyForm(page);
      expect(saved.ok, saved.message).toBeTruthy();
      expect(addResult.accounting_dimension).toBe("department");
      expect(addResult.reference_doctype).toBe("Department");
      expect(addResult.default_value).toBe(department);
      await captureStep(page, "ro_company_02_saved_row");

      await openCompany(page, company);
      const uiPersist = await page.evaluate(() => {
        const doc = (
          window as unknown as {
            cur_frm: { doc: { round_off_dimension_defaults: Array<Record<string, unknown>> } };
          }
        ).cur_frm.doc;
        return doc.round_off_dimension_defaults || [];
      });
      expect(uiPersist.length).toBe(1);
      expect(uiPersist[0].accounting_dimension).toBe("department");
      expect(uiPersist[0].default_value).toBe(department);

      const apiRows = await callMethod(page, "get_company_round_off_child_rows", { company });
      expect(apiRows.length).toBe(1);
      expect(apiRows[0].accounting_dimension).toBe("department");
      expect(apiRows[0].reference_doctype).toBe("Department");
      expect(apiRows[0].default_value).toBe(department);

      const altDepts = (await callMethod(page, "get_company_round_off_child_rows", { company })) as unknown[];
      void altDepts;
      const altDeptList = await page.evaluate(async ({ company, department }) => {
        const w = window as unknown as {
          frappe: { call: (o: Record<string, unknown>) => Promise<{ message: Array<{ name: string }> }> };
        };
        const r = await w.frappe.call({
          method: "frappe.client.get_list",
          args: {
            doctype: "Department",
            filters: { company, name: ["!=", department] },
            fields: ["name"],
            limit_page_length: 1,
          },
        });
        return r.message || [];
      }, { company, department });
      const altDept = altDeptList[0]?.name || department;

      await page.evaluate(({ altDept }) => {
        const frm = (
          window as unknown as {
            cur_frm: {
              doc: { round_off_dimension_defaults: Array<Record<string, unknown>> };
              refresh_field: (f: string) => void;
            };
          }
        ).cur_frm;
        frm.doc.round_off_dimension_defaults[0].default_value = altDept;
        frm.refresh_field("round_off_dimension_defaults");
      }, { altDept });
      expect((await saveCompanyForm(page)).ok).toBeTruthy();
      const afterEdit = await callMethod(page, "get_company_round_off_child_rows", { company });
      expect(afterEdit[0].default_value).toBe(altDept);

      await page.evaluate(() => {
        const frm = (
          window as unknown as {
            cur_frm: { clear_table: (f: string) => void; refresh_field: (f: string) => void };
          }
        ).cur_frm;
        frm.clear_table("round_off_dimension_defaults");
        frm.refresh_field("round_off_dimension_defaults");
      });
      expect((await saveCompanyForm(page)).ok).toBeTruthy();
      expect((await callMethod(page, "get_company_round_off_child_rows", { company })).length).toBe(0);

      await page.evaluate(({ department }) => {
        const frm = (
          window as unknown as {
            cur_frm: {
              add_child: (f: string, v: Record<string, unknown>) => void;
              refresh_field: (f: string) => void;
            };
          }
        ).cur_frm;
        frm.add_child("round_off_dimension_defaults", {
          accounting_dimension: "department",
          reference_doctype: "Department",
          default_value: department,
        });
        frm.refresh_field("round_off_dimension_defaults");
      }, { department });
      expect((await saveCompanyForm(page)).ok).toBeTruthy();

      // Build a 2-row payload explicitly (grid add_child may collapse identical dims client-side)
      const dup = await page.evaluate(async ({ department }) => {
        const w = window as unknown as {
          cur_frm: { doc: Record<string, unknown>; reload_doc: () => Promise<unknown> };
          frappe: { call: (o: Record<string, unknown>) => Promise<{ exc?: string }> };
        };
        const doc = {
          ...w.cur_frm.doc,
          round_off_dimension_defaults: [
            {
              doctype: "Round Off Dimension Default",
              accounting_dimension: "department",
              reference_doctype: "Department",
              default_value: department,
              idx: 1,
            },
            {
              doctype: "Round Off Dimension Default",
              accounting_dimension: "department",
              reference_doctype: "Department",
              default_value: department,
              idx: 2,
            },
          ],
        };
        try {
          await w.frappe.call({
            method: "frappe.desk.form.save.savedocs",
            args: { action: "Save", doc: JSON.stringify(doc) },
            freeze: false,
          });
          return { ok: true, message: "", rowCount: 2 };
        } catch (e: unknown) {
          const err = e as {
            message?: string;
            _server_messages?: string;
            responseJSON?: { _server_messages?: string; exception?: string };
            responseText?: string;
          };
          let detail = "";
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
                  if (x && typeof x === "object" && "message" in (x as object)) {
                    return String((x as { message: unknown }).message);
                  }
                  return JSON.stringify(x);
                })
                .join("\n");
            } catch {
              detail = String(raw);
            }
          }
          if (!detail) detail = err?.message || err?.responseJSON?.exception || "";
          if (!detail || detail === "[object Object]") {
            try {
              detail = JSON.stringify(e);
            } catch {
              detail = String(e);
            }
          }
          return { ok: false, message: detail, rowCount: 2 };
        }
      }, { department });
      expect(dup.ok, JSON.stringify(dup)).toBeFalsy();
      expect(String(dup.message).toLowerCase()).toMatch(/duplicat/);

      await openCompany(page, company);

      for (const forbidden of ["cost_center", "account"]) {
        const masters = await page.evaluate(async ({ company, forbidden }) => {
          const w = window as unknown as {
            frappe: { call: (o: Record<string, unknown>) => Promise<{ message: Array<{ name: string }> }> };
          };
          if (forbidden === "cost_center") {
            const r = await w.frappe.call({
              method: "frappe.client.get_list",
              args: {
                doctype: "Cost Center",
                filters: { company, is_group: 0 },
                fields: ["name"],
                limit_page_length: 1,
              },
            });
            return { value: r.message?.[0]?.name, reference_doctype: "Cost Center" };
          }
          const r = await w.frappe.call({
            method: "frappe.client.get_list",
            args: {
              doctype: "Account",
              filters: { company, is_group: 0 },
              fields: ["name"],
              limit_page_length: 1,
            },
          });
          return { value: r.message?.[0]?.name, reference_doctype: "Account" };
        }, { company, forbidden });
        expect(masters.value, forbidden).toBeTruthy();

        await page.evaluate(({ forbidden, masters }) => {
          const frm = (
            window as unknown as {
              cur_frm: {
                clear_table: (f: string) => void;
                add_child: (f: string, v: Record<string, unknown>) => void;
                refresh_field: (f: string) => void;
              };
            }
          ).cur_frm;
          frm.clear_table("round_off_dimension_defaults");
          frm.add_child("round_off_dimension_defaults", {
            accounting_dimension: forbidden,
            reference_doctype: masters.reference_doctype,
            default_value: masters.value,
          });
          frm.refresh_field("round_off_dimension_defaults");
        }, { forbidden, masters });
        const err = await saveCompanyForm(page);
        expect(err.ok, `${forbidden}: ${err.message}`).toBeFalsy();
        expect(err.message.toLowerCase()).toMatch(/must not include|invalid round off dimension|cost_center|account/);
      }

      await page.evaluate(() => {
        const frm = (
          window as unknown as {
            cur_frm: {
              clear_table: (f: string) => void;
              add_child: (f: string, v: Record<string, unknown>) => void;
              refresh_field: (f: string) => void;
            };
          }
        ).cur_frm;
        frm.clear_table("round_off_dimension_defaults");
        frm.add_child("round_off_dimension_defaults", {
          accounting_dimension: "department",
          reference_doctype: "Department",
          default_value: "NO-SUCH-DEPARTMENT-E2E-XYZ",
        });
        frm.refresh_field("round_off_dimension_defaults");
      });
      const invalid = await saveCompanyForm(page);
      expect(invalid.ok).toBeFalsy();
      expect(invalid.message.toLowerCase()).toMatch(/does not exist|invalid default|could not find/);

      const adAfter = await callMethod(page, "get_ad_default_dimension", {
        company,
        document_type: "Department",
      });
      expect(adAfter).toEqual(adBefore);

      const fakeExists = await page.evaluate(async () => {
        const w = window as unknown as {
          frappe: { call: (o: Record<string, unknown>) => Promise<{ message?: unknown }> };
        };
        try {
          await w.frappe.call({
            method: "frappe.client.get",
            args: { doctype: "Department", name: "NO-SUCH-DEPARTMENT-E2E-XYZ" },
          });
          return true;
        } catch {
          return false;
        }
      });
      expect(fakeExists).toBeFalsy();

      await captureStep(page, "ro_company_03_validations_done");
      const hardConsole = consoleErrors.filter((e) => /TypeError|ReferenceError|SyntaxError/.test(e.text));
      expect(hardConsole, JSON.stringify(hardConsole)).toEqual([]);
    } finally {
      try {
        await callMethod(page, "restore_round_off_ui_prerequisites", { payload: prep });
      } catch (e) {
        console.warn("restore prep", e);
      }
    }
  });
});
