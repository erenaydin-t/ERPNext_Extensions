import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { captureStep } from "../src/utils/screenshots";
import { validateGlSql } from "../src/utils/frappe-api";

/**
 * Release-blocking E2E: Scenario 21 — Material Transfer for Manufacture (zero-value transfer GL).
 */
test.describe("Scenario 21 — MTfM Desk UI @release-blocking", () => {
  test("Accounting Ledger Preview and submit with GL integrity", async ({
    page,
    loginPage,
    stockEntryPage,
    ledgerPreview,
    mtfmContext,
  }) => {
    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    await captureStep(page, "01_login_complete");

    await stockEntryPage.open(mtfmContext.stock_entry);
    await captureStep(page, "02_stock_entry_open");

    const doc = await stockEntryPage.readDoc();
    expect(doc.purpose).toBe("Material Transfer for Manufacture");
    expect(doc.source_warehouse).toBeTruthy();
    expect(doc.target_warehouse).toBeTruthy();
    expect(doc.source_warehouse).not.toEqual(doc.target_warehouse);
    await captureStep(page, "03_doc_fields_verified");

    if (doc.docstatus !== 0) {
      test.info().annotations.push({
        type: "note",
        description: "Document already submitted; preview menu only on draft — skipping UI preview click",
      });
    } else {
      await stockEntryPage.openAccountingLedgerPreviewFromMenu();
      await ledgerPreview.waitForOpen();
      await captureStep(page, "04_accounting_ledger_preview_open");

      const preview = await ledgerPreview.parse();
      expect(preview.title).toMatch(/Accounting Ledger Preview/i);
      expect(preview.rows.length).toBeGreaterThan(0);

      ledgerPreview.assertNoForbiddenAccounts(preview);
      ledgerPreview.assertBalancedTotals(preview, doc.total_incoming_value);

      const { wipDebit, stockCredit } = ledgerPreview.findWipAndStockRows(preview);
      expect(wipDebit).toBeGreaterThan(0);
      expect(stockCredit).toBeGreaterThan(0);
      expect(wipDebit).toBe(stockCredit);
      await captureStep(page, "05_preview_validated");

      await ledgerPreview.close();
    }

    const submittedNow = await stockEntryPage.submitIfDraft();
    if (submittedNow) {
      await captureStep(page, "06_after_submit");
    }
    await page.reload({ waitUntil: "domcontentloaded" });
    await stockEntryPage.waitForFormReady();
    await stockEntryPage.expectSubmitted();
    await captureStep(page, "07_submitted_status");

    const gl = await test.step("SQL GL validation via bench API", async () => {
      return validateGlSql(mtfmContext.stock_entry);
    });

    expect(gl.status).toBe("PASS");
    expect(gl.debit_equals_credit).toBe(true);
    expect(gl.debit_equals_incoming).toBe(true);
    expect(gl.not_doubled).toBe(true);
    expect(gl.sum_debit).toBe(gl.sum_credit);
    expect(gl.sum_debit).toBe(mtfmContext.total_incoming_value);
    await captureStep(page, "08_gl_validation_pass");
  });
});
