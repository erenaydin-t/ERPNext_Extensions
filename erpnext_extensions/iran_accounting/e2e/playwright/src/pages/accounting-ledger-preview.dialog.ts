import { expect, type Page } from "@playwright/test";

export type PreviewRow = {
  account: string;
  debit: number;
  credit: number;
};

export type PreviewParseResult = {
  title: string;
  rows: PreviewRow[];
  debitTotal: number;
  creditTotal: number;
  rawText: string;
};

export class AccountingLedgerPreviewDialog {
  constructor(private readonly page: Page) {}

  private dialogRoot() {
    return this.page
      .getByRole("dialog")
      .filter({ has: this.page.locator(".modal-title", { hasText: /Accounting Ledger Preview/i }) });
  }

  async waitForOpen(): Promise<void> {
    const dialog = this.dialogRoot();
    await expect(dialog).toBeVisible({ timeout: 60_000 });
    await expect(dialog.locator(".modal-title")).toContainText(/Accounting Ledger Preview/i, {
      timeout: 30_000,
    });
    await this.page.waitForFunction(
      () => {
        const modals = Array.from(document.querySelectorAll(".modal.fade.show"));
        const modal = modals.find((m) =>
          /Accounting Ledger Preview/i.test(m.querySelector(".modal-title")?.textContent || "")
        );
        if (!modal) return false;
        return (
          modal.querySelector(".dt-scrollable, .datatable, table") !== null ||
          (modal.textContent?.length ?? 0) > 50
        );
      },
      { timeout: 60_000 }
    );
  }

  async parse(): Promise<PreviewParseResult> {
    return this.page.evaluate(() => {
      const modals = Array.from(document.querySelectorAll(".modal.fade.show"));
      const modal = modals.find((m) =>
        /Accounting Ledger Preview/i.test(m.querySelector(".modal-title")?.textContent || "")
      ) as HTMLElement | null;
      if (!modal) {
        return { title: "", rows: [], debitTotal: 0, creditTotal: 0, rawText: "" };
      }
      const title = modal.querySelector(".modal-title")?.textContent?.trim() || "";
      const rawText = modal.innerText || "";

      const parseNum = (s: string) => {
        if (!s) return 0;
        const m = s.replace(/\s/g, "").match(/[\d,]+\.?\d*/);
        if (!m) return 0;
        const n = parseFloat(m[0].replace(/,/g, ""));
        return Number.isFinite(n) ? n : 0;
      };

      type PreviewRow = { account: string; debit: number; credit: number };
      const rows: PreviewRow[] = [];

      const scroll = modal.querySelector(".dt-scrollable") || modal;
      const headerRow =
        scroll.querySelector(".dt-row-header") ||
        scroll.querySelector(".dt-header .dt-row") ||
        scroll.querySelector(".dt-row");
      let accountIdx = 2;
      let debitIdx = 3;
      let creditIdx = 4;
      if (headerRow) {
        const headers = Array.from(headerRow.querySelectorAll(".dt-cell")).map((cell) => {
          const el = cell as HTMLElement;
          return (el.getAttribute("title") || el.dataset.fieldname || el.textContent || "")
            .trim()
            .toLowerCase();
        });
        const idxAccount = headers.findIndex(
          (h) => h === "account" || (h.includes("account") && !h.includes("against") && !h.includes("voucher"))
        );
        const idxDebit = headers.findIndex((h) => h.includes("debit"));
        const idxCredit = headers.findIndex((h) => h.includes("credit"));
        if (idxAccount >= 0) accountIdx = idxAccount;
        if (idxDebit >= 0) debitIdx = idxDebit;
        if (idxCredit >= 0) creditIdx = idxCredit;
      } else {
        const titled = Array.from(modal.querySelectorAll("[title]")).map((el) =>
          (el.getAttribute("title") || "").trim().toLowerCase()
        );
        if (titled.includes("account")) accountIdx = titled.indexOf("account");
        const debitTitle = titled.findIndex((t) => t.includes("debit"));
        const creditTitle = titled.findIndex((t) => t.includes("credit"));
        if (debitTitle >= 0) debitIdx = debitTitle;
        if (creditTitle >= 0) creditIdx = creditTitle;
      }

      const bodyRows = scroll.querySelectorAll(
        ".dt-row:not(.dt-row-header):not(.dt-row-filter)"
      );
      bodyRows.forEach((rowEl) => {
        const cells = rowEl.querySelectorAll(".dt-cell");
        if (cells.length < Math.max(accountIdx, debitIdx, creditIdx) + 1) return;
        const account = (cells[accountIdx]?.textContent || "").trim();
        const debit = parseNum(cells[debitIdx]?.textContent || "");
        const credit = parseNum(cells[creditIdx]?.textContent || "");
        if (!account || account === "Account") return;
        if (/^filter based on/i.test(account)) return;
        rows.push({ account, debit, credit });
      });

      if (!rows.length) {
        const rowBlocks = scroll.querySelectorAll(".dt-scrollable .dt-row, [class*='dt-scroll'] > div > div");
        rowBlocks.forEach((rowEl) => {
          const cells = rowEl.querySelectorAll("[title], .dt-cell, generic");
          const texts = Array.from(rowEl.children).map((c) => (c.textContent || "").trim());
          if (texts.length < 5) return;
          const account = texts[2];
          const debit = parseNum(texts[3]);
          const credit = parseNum(texts[4]);
          if (account && debit + credit > 0) rows.push({ account, debit, credit });
        });
      }

      let debitTotal = 0;
      let creditTotal = 0;
      for (const r of rows) {
        debitTotal += r.debit;
        creditTotal += r.credit;
      }
      return { title, rows, debitTotal, creditTotal, rawText };
    });
  }

  async close(): Promise<void> {
    const dialog = this.dialogRoot();
    const closeBtn = dialog.locator(".btn-modal-close, .btn-close");
    if (await closeBtn.count()) {
      await closeBtn.first().click();
    } else {
      await this.page.keyboard.press("Escape");
    }
    await expect(this.dialogRoot()).toHaveCount(0, { timeout: 15_000 });
  }

  assertNoForbiddenAccounts(parse: PreviewParseResult): void {
    const blob = parse.rawText.toLowerCase();
    expect(blob).not.toMatch(/stock adjustment/);
    expect(blob).not.toMatch(/round off/);
  }

  assertBalancedTotals(parse: PreviewParseResult, expected?: number): void {
    expect(parse.debitTotal).toBe(parse.creditTotal);
    if (expected !== undefined && expected > 0) {
      expect(parse.debitTotal).toBe(expected);
    }
  }

  findWipAndStockRows(parse: PreviewParseResult): { wipDebit: number; stockCredit: number } {
    let wipDebit = 0;
    let stockCredit = 0;
    for (const row of parse.rows) {
      const acct = row.account.toLowerCase();
      if (acct.includes("wip") || acct.includes("work in progress")) {
        wipDebit += row.debit;
      }
      if (acct.includes("stock in hand") || acct.includes("stock -")) {
        stockCredit += row.credit;
      }
    }
    return { wipDebit, stockCredit };
  }
}
