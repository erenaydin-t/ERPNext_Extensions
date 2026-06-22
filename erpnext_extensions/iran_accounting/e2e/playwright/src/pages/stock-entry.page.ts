import { expect, type Page } from "@playwright/test";

export type StockEntryDocSnapshot = {
  name: string;
  purpose: string;
  docstatus: number;
  company: string;
  total_incoming_value: number;
  total_outgoing_value: number;
  value_difference: number;
  source_warehouse: string | null;
  target_warehouse: string | null;
};

export class StockEntryPage {
  constructor(private readonly page: Page) {}

  async open(stockEntryName: string): Promise<void> {
    await this.page.goto(`/desk/stock-entry/${encodeURIComponent(stockEntryName)}`, {
      waitUntil: "domcontentloaded",
    });
    await this.waitForFormReady();
  }

  async waitForFormReady(): Promise<void> {
    await this.page.waitForFunction(
      () => {
        const w = window as unknown as {
          cur_frm?: { doc?: { doctype?: string }; is_loading?: boolean };
        };
        return w.cur_frm?.doc?.doctype === "Stock Entry" && !w.cur_frm?.is_loading;
      },
      { timeout: 180_000 }
    );
  }

  async readDoc(): Promise<StockEntryDocSnapshot> {
    return this.page.evaluate(() => {
      const frm = (window as unknown as { cur_frm: { doc: Record<string, unknown> & { items?: Array<Record<string, unknown>> } } })
        .cur_frm;
      const doc = frm.doc;
      let source_warehouse: string | null = null;
      let target_warehouse: string | null = null;
      for (const row of doc.items || []) {
        if (row.s_warehouse) source_warehouse = source_warehouse || String(row.s_warehouse);
        if (row.t_warehouse) target_warehouse = target_warehouse || String(row.t_warehouse);
      }
      return {
        name: String(doc.name),
        purpose: String(doc.purpose),
        docstatus: Number(doc.docstatus),
        company: String(doc.company),
        total_incoming_value: Number(doc.total_incoming_value),
        total_outgoing_value: Number(doc.total_outgoing_value),
        value_difference: Number(doc.value_difference),
        source_warehouse,
        target_warehouse,
      };
    });
  }

  async openAccountingLedgerPreviewFromMenu(): Promise<void> {
    const actions = this.page.locator(".page-actions, .form-page");
    const previewBtn = actions.getByRole("button", { name: /^Preview$/ }).first();
    await expect(previewBtn).toBeVisible({ timeout: 60_000 });
    await previewBtn.click();
    const accountingItem = this.page.getByRole("link", { name: "Accounting Ledger" });
    await expect(accountingItem).toBeVisible({ timeout: 30_000 });
    await accountingItem.click();
  }

  async submitIfDraft(): Promise<boolean> {
    const doc = await this.readDoc();
    if (doc.docstatus !== 0) return false;
    const submit = this.page.getByRole("button", { name: "Submit" }).first();
    await expect(submit).toBeEnabled({ timeout: 30_000 });
    await submit.click();
    const confirmDialog = this.page.getByRole("dialog").filter({ hasText: /Permanently Submit|Confirm/i });
    const yes = confirmDialog.getByRole("button", { name: "Yes" });
    await expect(yes).toBeVisible({ timeout: 30_000 });
    await yes.click();
    await expect
      .poll(async () => (await this.readDoc()).docstatus, { timeout: 180_000 })
      .toBe(1);
    return true;
  }

  async expectSubmitted(): Promise<void> {
    await expect
      .poll(async () => (await this.readDoc()).docstatus, { timeout: 60_000 })
      .toBe(1);
  }
}
