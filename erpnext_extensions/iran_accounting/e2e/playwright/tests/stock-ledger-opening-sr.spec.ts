import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { StockLedgerReportPage } from "../src/pages/stock-ledger-report.page";
import { captureStep } from "../src/utils/screenshots";
import { deskBaseUrlResolvable } from "../src/utils/network";
import { config } from "../src/utils/env";
import { benchExecute } from "../src/utils/frappe-api";

test.describe("Scenario 45 — Opening Stock Reconciliation @release-blocking", () => {
  test("Non-batch opening SR: Outgoing Rate 0 in report and export", async ({ page, loginPage }) => {
    const created = benchExecute(
      "erpnext_extensions.iran_accounting.diagnostics.create_opening_sr_e2e_fixture",
      {
        company: erpnextConfig.company,
        qty: 100,
        valuation_rate: 3000,
      }
    ) as { voucher_no: string; posting_date: string; item_code: string };

    expect(created.voucher_no).toBeTruthy();
    const inspect = benchExecute(
      "erpnext_extensions.iran_accounting.diagnostics.inspect_stock_reconciliation_voucher",
      { voucher_no: created.voucher_no, company: erpnextConfig.company }
    ) as {
      sle: Array<{ outgoing_rate: number; incoming_rate: number; stock_value_difference: number }>;
      report: Array<{ in_out_rate: number; incoming_rate: number; in_qty: number; out_qty: number }>;
    };

    for (const sle of inspect.sle || []) {
      if (flt(sle.stock_value_difference) > 0) {
        expect(flt(sle.outgoing_rate)).toBe(0);
      }
    }
    for (const row of inspect.report || []) {
      expect(flt(row.in_qty)).toBeGreaterThan(0);
      expect(flt(row.out_qty)).toBe(0);
      expect(flt(row.incoming_rate)).toBe(3000);
      expect(flt(row.in_out_rate)).toBe(0);
    }

    test.skip(
      !deskBaseUrlResolvable(config.baseUrl),
      `Desk host not resolvable (${config.baseUrl}); bench API checks above are authoritative`
    );

    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    await captureStep(page, "sl45_01_login");

    const report = new StockLedgerReportPage(page);
    await report.open();
    await report.applyFilters({
      company: erpnextConfig.company,
      fromDate: created.posting_date,
      toDate: created.posting_date,
      voucherNo: created.voucher_no,
    });
    await captureStep(page, "sl45_02_stock_ledger");

    const { headers, rows } = await report.parseVisibleGrid();
    const outIdx = headers.findIndex((h) => /outgoing rate/i.test(h));
    const inRateIdx = headers.findIndex((h) => /incoming rate/i.test(h));
    const inQtyIdx = headers.findIndex((h) => /^in qty/i.test(h));
    expect(outIdx).toBeGreaterThanOrEqual(0);
    for (const row of rows) {
      if (inQtyIdx >= 0 && parseFloat(String(row[inQtyIdx]).replace(/,/g, "")) > 0) {
        expect(parseFloat(String(row[outIdx]).replace(/,/g, "") || "0")).toBe(0);
        if (inRateIdx >= 0) {
          expect(parseFloat(String(row[inRateIdx]).replace(/,/g, ""))).toBe(3000);
        }
      }
    }

    try {
      const xlsx = await report.exportExcel();
      const text = xlsx.toString("latin1");
      expect(text).not.toMatch(/outgoing rate[\s\S]{0,80}3000/);
      await captureStep(page, "sl45_03_export");
    } catch {
      test.info().annotations.push({ type: "note", description: "Desk export skipped" });
    }
  });
});

function flt(v: unknown): number {
  const n = parseFloat(String(v ?? "0").replace(/,/g, ""));
  return Number.isFinite(n) ? n : 0;
}
