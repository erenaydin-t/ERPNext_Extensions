import { expect, type Page } from "@playwright/test";
import { findMonetaryDecimalViolations } from "../utils/irr-monetary";

export type StockLedgerReportFilters = {
  company: string;
  fromDate: string;
  toDate: string;
  voucherNo: string;
};

export class StockLedgerReportPage {
  constructor(private readonly page: Page) {}

  async open(): Promise<void> {
    await this.page.goto("/app/query-report/Stock%20Ledger", { waitUntil: "domcontentloaded" });
    await this.page.waitForFunction(
      () => {
        const w = window as unknown as { frappe?: { query_report?: { filters?: unknown[] } } };
        return Boolean(w.frappe?.query_report?.filters);
      },
      { timeout: 120_000 }
    );
  }

  async applyFilters(filters: StockLedgerReportFilters): Promise<void> {
    await this.page.evaluate(async (f) => {
      const w = window as unknown as {
        frappe?: {
          query_report?: {
            set_filter_value: (field: string, value: string) => void;
            refresh: () => Promise<void>;
          };
        };
      };
      const qr = w.frappe?.query_report;
      if (!qr) throw new Error("query_report not ready");
      qr.set_filter_value("company", f.company);
      qr.set_filter_value("from_date", f.fromDate);
      qr.set_filter_value("to_date", f.toDate);
      qr.set_filter_value("voucher_no", f.voucherNo);
      qr.set_filter_value("valuation_field_type", "Currency");
      await qr.refresh();
    }, filters);
    await this.page.waitForFunction(
      () => {
        const w = window as unknown as {
          frappe?: { query_report?: { datatable?: { datamanager?: { data?: unknown[] } } } };
        };
        const data = w.frappe?.query_report?.datatable?.datamanager?.data;
        return Array.isArray(data) && data.length > 0;
      },
      { timeout: 180_000 }
    );
  }

  async parseVisibleGrid(): Promise<{ headers: string[]; rows: string[][] }> {
    return this.page.evaluate(() => {
      const w = window as unknown as {
        frappe?: {
          query_report?: {
            columns?: Array<{ label?: string; fieldname?: string }>;
            datatable?: { datamanager?: { data?: Record<string, unknown>[] } };
          };
        };
      };
      const qr = w.frappe?.query_report;
      const columns = qr?.columns || [];
      const headers = columns.map((c) => (c.label || c.fieldname || "").trim());
      const data = qr?.datatable?.datamanager?.data || [];
      const rows = data.map((row) =>
        columns.map((col) => {
          const fn = col.fieldname || "";
          const v = row[fn];
          return v === null || v === undefined ? "" : String(v);
        })
      );
      return { headers, rows };
    });
  }

  assertNoMonetaryDecimals(headers: string[], rows: string[][]): void {
    const violations = findMonetaryDecimalViolations(headers, rows);
    expect(violations, `IRR monetary decimals in grid: ${JSON.stringify(violations.slice(0, 5))}`).toEqual([]);
  }

  async exportExcel(): Promise<Buffer> {
    const downloadPromise = this.page.waitForEvent("download", { timeout: 120_000 });
    await this.page.getByRole("button", { name: /Menu|Actions/i }).first().click();
    const exportItem = this.page.getByRole("menuitem", { name: /Export/i }).or(this.page.getByText("Export", { exact: true }));
    await exportItem.first().click();
    const excel = this.page.getByRole("menuitem", { name: /Excel/i }).or(this.page.getByText("Excel"));
    if (await excel.count()) {
      await excel.first().click();
    }
    const download = await downloadPromise;
    const path = await download.path();
    if (!path) throw new Error("Export download path missing");
    const fs = await import("fs");
    return fs.readFileSync(path);
  }
}
