import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { captureStep } from "../src/utils/screenshots";

/**
 * Desk UI: IRR monetary rates/amounts must display as integers (no hidden fractions).
 */
test.describe("IRR rate-first Desk UI @release-blocking", () => {
  test("Stock Entry form shows integer rates and amounts", async ({ page, loginPage }) => {
    await loginPage.login(erpnextConfig.user, erpnextConfig.password);
    await page.goto("/desk", { waitUntil: "domcontentloaded" });
    await captureStep(page, "irr_01_login");

    const list = await page.request.get(
      "/api/resource/Stock%20Entry?filters=[[\"docstatus\",\"=\",1]]&fields=[\"name\"]&order_by=modified%20desc&limit_page_length=1"
    );
    expect(list.ok()).toBeTruthy();
    const payload = await list.json();
    const name = payload?.data?.[0]?.name as string | undefined;
    expect(name).toBeTruthy();

    await page.goto(`/desk/stock-entry/${encodeURIComponent(name!)}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => {
        const w = window as unknown as { cur_frm?: { doc?: { doctype?: string } } };
        return w.cur_frm?.doc?.doctype === "Stock Entry";
      },
      { timeout: 120_000 }
    );
    await captureStep(page, "irr_02_stock_entry_open");

    const check = await page.evaluate(() => {
      const frm = (
        window as unknown as {
          cur_frm: { doc: Record<string, unknown> & { items?: Array<Record<string, unknown>> } };
        }
      ).cur_frm;
      const doc = frm.doc;
      const fractional: string[] = [];
      const isFrac = (v: unknown) => {
        if (v === null || v === undefined || v === "") return false;
        const n = Number(v);
        return Number.isFinite(n) && Math.abs(n - Math.round(n)) > 1e-9;
      };
      for (const row of doc.items || []) {
        for (const f of [
          "basic_rate",
          "valuation_rate",
          "incoming_rate",
          "outgoing_rate",
          "amount",
          "basic_amount",
          "additional_cost",
          "landed_cost_voucher_amount",
        ]) {
          if (isFrac(row[f])) fractional.push(`${row.item_code}.${f}=${row[f]}`);
        }
      }
      for (const f of [
        "total_incoming_value",
        "total_outgoing_value",
        "value_difference",
        "total_additional_costs",
      ]) {
        if (isFrac(doc[f])) fractional.push(`header.${f}=${doc[f]}`);
      }
      return {
        name: String(doc.name),
        purpose: String(doc.purpose),
        item_count: (doc.items || []).length,
        fractional,
        sample: (doc.items || []).slice(0, 2).map((r) => ({
          item_code: r.item_code,
          basic_rate: r.basic_rate,
          valuation_rate: r.valuation_rate,
          amount: r.amount,
          basic_amount: r.basic_amount,
        })),
      };
    });

    expect(check.item_count).toBeGreaterThan(0);
    expect(check.fractional, JSON.stringify(check)).toEqual([]);
    await captureStep(page, "irr_03_integer_rates_verified");
  });
});
