/**
 * Receipt JE row dimensions E2E (Desk Journal Entry form).
 *
 *   bench --site development.localhost execute \\
 *     erpnext_extensions.facility_management.e2e.facility_receipt_je_dimensions_prep.prepare_receipt_je_with_dimensions
 *
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \\
 *     node apps/erpnext_extensions/erpnext_extensions/facility_management/e2e/playwright_facility_receipt_je_dimensions.mjs
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute as sharedBenchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN_DIR = path.join(__dirname, "screenshots", "receipt_je_dims");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

function benchExecute(method) {
	return sharedBenchExecute(method);
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
	await page.waitForTimeout(1200);
}

function assertReceiptRows(prep) {
	const { je_rows, dim_fn, bank_gl, loan_gl, deferred_gl, expected_bank_dimension, facility } = prep;
	const bank = je_rows.find((r) => r.account === bank_gl && r.debit > 0);
	const deferred = je_rows.find((r) => r.account === deferred_gl && r.debit > 0);
	const loanCredits = je_rows.filter((r) => r.account === loan_gl && r.credit > 0);
	const errors = [];
	if (!bank?.dims?.bank_dimension) errors.push("bank row missing bank_dimension");
	if (bank?.dims?.bank_dimension !== expected_bank_dimension) errors.push("bank_dimension mismatch");
	if (bank?.dims?.department) errors.push("bank row has department");
	if (bank?.dims?.bank_account_dimension) errors.push("bank row has bank_account_dimension");
	if (dim_fn && bank?.dims?.[dim_fn]) errors.push("bank row has facility dimension");

	if (!deferred) errors.push("deferred row missing");
	if (loanCredits.length !== 2) errors.push(`expected 2 loan credit rows, got ${loanCredits.length}`);

	for (const [label, row] of [
		["deferred", deferred],
		...loanCredits.map((r, i) => [`loan_credit_${i}`, r]),
	]) {
		if (!row) {
			errors.push(`${label} row missing`);
			continue;
		}
		if (dim_fn && row.dims?.[dim_fn] !== facility) errors.push(`${label} facility dim`);
		if (row.dims?.department) errors.push(`${label} has department`);
		if (row.dims?.bank_dimension) errors.push(`${label} has bank_dimension`);
		if (row.dims?.bank_account_dimension) errors.push(`${label} has bank_account_dimension`);
	}
	return { ok: !errors.length, errors, bank, deferred, loanCredits };
}

async function run() {
	const prep = benchExecute(
		"erpnext_extensions.facility_management.e2e.facility_receipt_je_dimensions_prep.prepare_receipt_je_with_dimensions"
	);
	const apiCheck = assertReceiptRows(prep);
	if (!apiCheck.ok) {
		console.error(JSON.stringify({ apiCheck, prep }, null, 2));
		process.exit(1);
	}

	const browser = await chromium.launch({ headless: true });
	const page = await (await browser.newContext({ viewport: { width: 1600, height: 900 } })).newPage();
	try {
		await login(page);
		const route = `/desk/journal-entry/${encodeURIComponent(prep.je)}`;
		await page.goto(`${BASE}${route}`, { waitUntil: "domcontentloaded" });
		await waitForm(page);
		fs.mkdirSync(SCREEN_DIR, { recursive: true });
		const screenshot = path.join(SCREEN_DIR, "receipt_je_rows.png");
		await page.screenshot({ path: screenshot, fullPage: true });

		const uiRows = await page.evaluate(() => {
			const dimFn = frappe.boot?.accounting_dimensions?.find?.((d) => d.document_type === "Facility")
				?.fieldname;
			return (cur_frm.doc.accounts || []).map((row) => {
				const dims = {};
				for (const fn of [
					"department",
					"bank_dimension",
					"bank_account_dimension",
					"cost_center",
					dimFn,
				]) {
					if (fn && row[fn]) dims[fn] = row[fn];
				}
				return { account: row.account, debit: row.debit_in_account_currency, credit: row.credit_in_account_currency, dims };
			});
		});

		console.log(
			JSON.stringify(
				{
					all_ok: true,
					route: `${BASE}${route}`,
					facility: prep.facility,
					je: prep.je,
					api: apiCheck,
					gl_rows: prep.gl_rows,
					ui_rows: uiRows,
					screenshot,
				},
				null,
				2
			)
		);
	} finally {
		await browser.close();
	}
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
