import { execSync } from "child_process";
import { config } from "./env";

export type MtfmContext = {
  stock_entry: string;
  company: string;
  docstatus: number;
  purpose: string;
  source_warehouse: string | null;
  target_warehouse: string | null;
  total_incoming_value: number;
  total_outgoing_value: number;
  value_difference: number;
  desk_url: string;
};

export type GlValidation = {
  status: string;
  sum_debit: number;
  sum_credit: number;
  total_incoming_value: number;
  debit_equals_credit: boolean;
  debit_equals_incoming: boolean;
  not_doubled: boolean;
  gl_row_count: number;
  checks: Record<string, unknown>;
};

function toPythonKwargs(obj: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(obj)) {
    if (value === undefined || value === null || value === "") continue;
    if (typeof value === "boolean") {
      parts.push(`"${key}": ${value ? "True" : "False"}`);
    } else if (typeof value === "number") {
      parts.push(`"${key}": ${value}`);
    } else {
      parts.push(`"${key}": ${JSON.stringify(value)}`);
    }
  }
  return `{${parts.join(", ")}}`;
}

function benchExecute(method: string, kwargs: Record<string, unknown> = {}): unknown {
  const kwargsPy = toPythonKwargs(kwargs);
  const cmd = `cd ${config.benchRoot} && bench --site ${config.site} execute ${method} --kwargs '${kwargsPy}'`;
  const out = execSync(cmd, { encoding: "utf8", maxBuffer: 10 * 1024 * 1024 });
  const line = out.trim().split("\n").filter(Boolean).pop() || "{}";
  return JSON.parse(line);
}

export function resolveMtfmContext(stockEntry?: string): MtfmContext {
  const kwargs: Record<string, unknown> = {
    company: config.company,
    create_if_missing: true,
  };
  const se = stockEntry || config.mtfmStockEntry;
  if (se) kwargs.stock_entry = se;
  return benchExecute("erpnext_extensions.iran_accounting.e2e_playwright.resolve_mtfm_stock_entry", kwargs) as MtfmContext;
}

export function validateGlSql(stockEntry: string): GlValidation {
  return benchExecute("erpnext_extensions.iran_accounting.e2e_playwright.validate_stock_entry_gl_sql", {
    stock_entry: stockEntry,
  }) as GlValidation;
}

export async function frappeCall<T>(
  page: import("@playwright/test").Page,
  method: string,
  args: Record<string, unknown> = {}
): Promise<T> {
  return page.evaluate(
    async ({ method, args }) => {
      const w = window as unknown as {
        frappe?: { call: (o: { method: string; args: Record<string, unknown> }) => Promise<{ message: unknown }> };
      };
      if (!w.frappe?.call) {
        throw new Error("frappe.call not available — open a Desk form first");
      }
      const r = await w.frappe.call({ method, args, freeze: true });
      return r.message as T;
    },
    { method, args }
  );
}
