/**
 * Facility Repayment JE template E2E (preview + submit).
 * DB-first: Journal Entry docstatus after submit.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute, getDocumentState, waitDocstatus } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "repayment_je");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

function bench(method) {
	return benchExecute(method);
}

async function login(page) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", process.env.FRAPPE_E2E_USER || "Administrator");
	await page.fill("#login_password", process.env.FRAPPE_E2E_PASSWORD || "admin");
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitForm(page) {
	await page.waitForFunction(() => window.cur_frm && !window.cur_frm.is_loading, { timeout: 180000 });
	await page.waitForFunction(
		() => window.cur_frm?.fields_dict?.facility || window.cur_frm?.doc?.facility,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(1000);
}

async function run() {
	const preview = bench(
		"erpnext_extensions.facility_management.e2e.facility_repayment_je_prep.preview_standard_template"
	);
	if (!preview.balanced || preview.total_debit !== 1140 || preview.rows.length !== 6) {
		console.error(JSON.stringify({ preview }, null, 2));
		process.exit(1);
	}
	const draft = bench(
		"erpnext_extensions.facility_management.e2e.facility_repayment_je_prep.create_draft_repayment_for_e2e"
	);

	const browser = await chromium.launch({ headless: true });
	const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
	const results = [];
	try {
		await login(page);
		await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(draft.repayment)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page);

		const uiPreview = await page.evaluate(async () => {
			const r = await frappe.call({
				method:
					"erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
				args: { doc: cur_frm.doc },
			});
			return r.message;
		});
		results.push({
			test: "A_preview",
			ok: uiPreview.balanced && uiPreview.rows.length === 6 && uiPreview.total_debit === 1140,
			uiPreview,
		});

		const saveSubmit = await page.evaluate(async () => {
			const r = await frappe.call({
				method: "frappe.client.submit",
				args: { doc: cur_frm.doc },
			});
			const doc = r.message || {};
			return { name: doc.name, je: doc.journal_entry };
		});
		const dbJe = await waitDocstatus("Journal Entry", saveSubmit.je, 1, { timeoutMs: 120000 });
		await page.waitForTimeout(1500);
		const jeRows = await page.evaluate(async (je) => {
			const r = await frappe.db.get_doc("Journal Entry", je);
			return r.accounts.map((a) => ({
				account: a.account,
				debit: a.debit_in_account_currency,
				credit: a.credit_in_account_currency,
			}));
		}, saveSubmit.je);

		fs.mkdirSync(SCREEN, { recursive: true });
		await page.goto(`${BASE}/desk/journal-entry/${encodeURIComponent(saveSubmit.je)}`, {
			waitUntil: "domcontentloaded",
		});
		await page.waitForTimeout(2500);
		const shot = path.join(SCREEN, "repayment_je.png");
		await page.screenshot({ path: shot, fullPage: true });

		results.push({
			test: "B_submit",
			ok: !!saveSubmit.je && dbJe.ok && jeRows.length === 6,
			saveSubmit,
			jeRows,
			db_je: getDocumentState("Journal Entry", saveSubmit.je, ["name", "docstatus"]),
			db_wait: dbJe,
			screenshot: shot,
		});
	} finally {
		await browser.close();
	}
	const all_ok = results.every((r) => r.ok);
	console.log(JSON.stringify({ all_ok, results, serverPreview: preview, draft }, null, 2));
	process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
