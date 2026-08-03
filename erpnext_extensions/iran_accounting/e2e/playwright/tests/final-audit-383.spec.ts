import fs from "node:fs";
import { test, expect } from "../src/fixtures/erpnext.fixture";
import { erpnextConfig } from "../src/fixtures/erpnext.fixture";
import { captureStep } from "../src/utils/screenshots";

const ARTIFACT = "/tmp/irr_final_audit_383_vouchers.json";

type Artifact = {
  company: string;
  cfg: { account: string; cost_center: string };
  vouchers: Record<string, string>;
};

function loadArtifact(): Artifact {
  const raw = fs.readFileSync(ARTIFACT, "utf8");
  return JSON.parse(raw) as Artifact;
}

function isFrac(v: unknown): boolean {
  if (v === null || v === undefined || v === "") return false;
  const n = Number(v);
  return Number.isFinite(n) && Math.abs(n - Math.round(n)) > 1e-9;
}

test.describe("Final audit 3.8.4 UI vs DB @release-blocking", () => {
  test("residual Stock Entry UI matches DB integers and Round Off GL", async ({
    page,
    loginPage,
  }) => {
    const artifact = loadArtifact();
    const voucher =
      artifact.vouchers.positive_residual ||
      artifact.vouchers.cancel_resubmit ||
      Object.values(artifact.vouchers)[0];
    expect(voucher, "audit artifact voucher").toBeTruthy();

    await loginPage.login(erpnextConfig.user, erpnextConfig.password);

    const dbRes = await page.request.get(
      `/api/resource/Stock%20Entry/${encodeURIComponent(voucher!)}?fields=["*"]`
    );
    expect(dbRes.ok()).toBeTruthy();
    const dbDoc = (await dbRes.json()).data as Record<string, unknown> & {
      items?: Array<Record<string, unknown>>;
    };

    const glRes = await page.request.get(
      `/api/resource/GL%20Entry?filters=${encodeURIComponent(
        JSON.stringify([
          ["voucher_type", "=", "Stock Entry"],
          ["voucher_no", "=", voucher],
          ["is_cancelled", "=", 0],
        ])
      )}&fields=${encodeURIComponent(
        JSON.stringify(["account", "debit", "credit", "remarks", "cost_center"])
      )}&limit_page_length=50`
    );
    expect(glRes.ok()).toBeTruthy();
    const glRows = ((await glRes.json()).data || []) as Array<Record<string, unknown>>;
    const roundOff = glRows.filter(
      (r) =>
        String(r.account) === artifact.cfg.account &&
        String(r.remarks || "").includes("IRR rate rounding residual")
    );

    await page.goto(`/desk/stock-entry/${encodeURIComponent(voucher!)}`, {
      waitUntil: "domcontentloaded",
    });
    await page.waitForFunction(
      () => {
        const w = window as unknown as { cur_frm?: { doc?: { doctype?: string } } };
        return w.cur_frm?.doc?.doctype === "Stock Entry";
      },
      { timeout: 120_000 }
    );
    await captureStep(page, "fa383_01_stock_entry");

    const ui = await page.evaluate(() => {
      const frm = (
        window as unknown as {
          cur_frm: { doc: Record<string, unknown> & { items?: Array<Record<string, unknown>> } };
        }
      ).cur_frm;
      const doc = frm.doc;
      const fractional: string[] = [];
      const isF = (v: unknown) => {
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
        ]) {
          if (isF(row[f])) fractional.push(`${row.item_code}.${f}=${row[f]}`);
        }
      }
      return {
        name: String(doc.name),
        items: (doc.items || []).map((r) => ({
          item_code: r.item_code,
          basic_rate: Number(r.basic_rate),
          valuation_rate: Number(r.valuation_rate),
          amount: Number(r.amount),
          basic_amount: Number(r.basic_amount),
        })),
        fractional,
      };
    });

    expect(ui.fractional, JSON.stringify(ui)).toEqual([]);
    expect(ui.name).toBe(voucher);

    const dbItems = dbDoc.items || [];
    expect(ui.items.length).toBe(dbItems.length);
    for (let i = 0; i < ui.items.length; i++) {
      const u = ui.items[i];
      const d = dbItems[i];
      expect(u.basic_rate).toBe(Number(d.basic_rate));
      expect(u.valuation_rate).toBe(Number(d.valuation_rate));
      expect(u.amount).toBe(Number(d.amount));
      expect(u.basic_amount).toBe(Number(d.basic_amount));
      expect(isFrac(u.basic_rate)).toBeFalsy();
      expect(isFrac(u.valuation_rate)).toBeFalsy();
      expect(isFrac(u.amount)).toBeFalsy();
    }

    // Positive residual vouchers must show exactly one Round Off GL row in DB
    if (voucher === artifact.vouchers.positive_residual) {
      expect(roundOff.length).toBe(1);
      expect(String(roundOff[0].cost_center)).toBe(artifact.cfg.cost_center);
    }

    await captureStep(page, "fa383_02_ui_db_match");
  });
});
