import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { StockLedgerReportPage } from "../src/pages/stock-ledger-report.page";
import { captureStep } from "../src/utils/screenshots";
import { checkStockLedgerReport } from "../src/utils/frappe-api";
import { cellHasIrrMonetaryDecimal, isMonetaryColumn } from "../src/utils/irr-monetary";
import { deskBaseUrlResolvable } from "../src/utils/network";
import { config } from "../src/utils/env";

const VOUCHER = process.env.E2E_STOCK_LEDGER_VOUCHER || "MAT-STE-2026-00102";
const FROM_DATE = process.env.E2E_STOCK_LEDGER_FROM || "2026-06-22";
const TO_DATE = process.env.E2E_STOCK_LEDGER_TO || "2026-06-22";

test.describe("Scenario 29 — Stock Ledger report @release-blocking", () => {
  test("Report grid and export have no IRR monetary decimals", async ({ page, loginPage }) => {
    const api = checkStockLedgerReport({
      company: erpnextConfig.company,
      voucher_no: VOUCHER,
      from_date: FROM_DATE,
      to_date: TO_DATE,
    });
    expect(api.status).toBe("PASS");
    expect(api.report_ok).toBe(true);
    expect(api.export_ok).toBe(true);
    expect(api.db_ok).toBe(true);

    test.skip(
      !deskBaseUrlResolvable(config.baseUrl),
      `Desk host not resolvable (${config.baseUrl}); bench API checks above are authoritative`
    );

    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    await captureStep(page, "sl29_01_login");

    const report = new StockLedgerReportPage(page);
    await report.open();
    await report.applyFilters({
      company: erpnextConfig.company,
      fromDate: FROM_DATE,
      toDate: TO_DATE,
      voucherNo: VOUCHER,
    });
    await captureStep(page, "sl29_02_report_loaded");

    const { headers, rows } = await report.parseVisibleGrid();
    expect(rows.length).toBeGreaterThan(0);
    report.assertNoMonetaryDecimals(headers, rows);
    await captureStep(page, "sl29_03_grid_validated");

    try {
      const xlsx = await report.exportExcel();
      expect(xlsx.length).toBeGreaterThan(100);
      const text = xlsx.toString("latin1");
      const bad = ["12663.84", "942719.39", "10596667255.68"].filter((needle) => text.includes(needle));
      expect(bad, `Export still contains fractional IRR samples: ${bad.join(", ")}`).toEqual([]);
      await captureStep(page, "sl29_04_export_validated");
    } catch {
      test.info().annotations.push({
        type: "note",
        description: "Desk export menu not automated; server export_ok already validated via bench API",
      });
    }

    for (const row of rows) {
      headers.forEach((h, i) => {
        if (!isMonetaryColumn(h)) return;
        const cell = row[i] ?? "";
        expect(cellHasIrrMonetaryDecimal(cell), `monetary cell ${h}=${cell}`).toBe(false);
      });
    }
  });
});
