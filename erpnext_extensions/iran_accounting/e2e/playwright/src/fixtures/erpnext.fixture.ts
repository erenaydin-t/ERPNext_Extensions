import { test as base } from "@playwright/test";
import { LoginPage } from "../pages/login.page";
import { StockEntryPage } from "../pages/stock-entry.page";
import { AccountingLedgerPreviewDialog } from "../pages/accounting-ledger-preview.dialog";
import { config } from "../utils/env";
import { resolveMtfmContext, type MtfmContext } from "../utils/frappe-api";

type ErpnextFixtures = {
  loginPage: LoginPage;
  stockEntryPage: StockEntryPage;
  ledgerPreview: AccountingLedgerPreviewDialog;
  mtfmContext: MtfmContext;
};

export const test = base.extend<ErpnextFixtures>({
  mtfmContext: async ({}, use) => {
    const ctx = resolveMtfmContext();
    await use(ctx);
  },

  loginPage: async ({ page }, use) => {
    await use(new LoginPage(page));
  },

  stockEntryPage: async ({ page }, use) => {
    await use(new StockEntryPage(page));
  },

  ledgerPreview: async ({ page }, use) => {
    await use(new AccountingLedgerPreviewDialog(page));
  },
});

export { expect } from "@playwright/test";

export const erpnextConfig = config;
