/**
 * Facility Type + facility_name JE template E2E.
 */
import { chromium } from "/tmp/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "facility_type");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function bench(method, argsJson) {
	const argsPart = argsJson ? ` --args '${argsJson}'` : "";
	const out = execSync(`cd ${BENCH} && bench --site development.localhost execute "${method}"${argsPart}`, {
		encoding: "utf8",
	});
	return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
}

async function login(page) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", process.env.FRAPPE_E2E_USER || "Administrator");
	await page.fill("#login_password", process.env.FRAPPE_E2E_PASSWORD || "admin");
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function shot(page, name) {
	fs.mkdirSync(SCREEN, { recursive: true });
	const p = path.join(SCREEN, `${name}.png`);
	await page.screenshot({ path: p, fullPage: true });
	return p;
}

async function run() {
	const prep = bench(
		"erpnext_extensions.facility_management.e2e.facility_type_templates_prep.prepare_facility_for_template_e2e"
	);
	const tmpl = bench(
		"erpnext_extensions.facility_management.e2e.facility_type_templates_prep.template_migration_sample"
	);
	const results = [];
	const evidence = { prep, tmpl, screenshots: {} };

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 950 } });
	const page = await context.newPage();
	page.setDefaultTimeout(180000);

	try {
		await login(page);

		const typeName = `وام قرض الحسنه تست ${Date.now().toString().slice(-4)}`;
		await page.goto(`${BASE}/desk/facility-type/new-facility-type-1`, { waitUntil: "domcontentloaded" });
		await page.waitForFunction(() => cur_frm?.doc?.doctype === "Facility Type", { timeout: 180000 });
		await page.evaluate(async (n) => {
			await cur_frm.set_value("facility_type_name", n);
			await cur_frm.save();
		}, typeName);
		evidence.screenshots.facility_type = await shot(page, "A_facility_type_saved");
		results.push({ test: "A_facility_type_master", ok: !!typeName });

		await page.goto(`${BASE}/desk/facility/${encodeURIComponent(prep.facility)}`, {
			waitUntil: "domcontentloaded",
		});
		await page.waitForFunction(() => cur_frm?.doc?.doctype === "Facility", { timeout: 180000 });
		const facCheck = await page.evaluate(() => ({
			type: cur_frm.doc.facility_type,
			name: cur_frm.doc.facility_name,
		}));
		evidence.screenshots.facility_form = await shot(page, "B_facility_with_type");
		results.push({
			test: "B_facility_form_type_and_name",
			ok: facCheck.type === prep.facility_type && facCheck.name === prep.facility_name,
			facCheck,
		});

		const receiptPrev = await page.evaluate(async () => {
			const r = await frappe.call({
				method:
					"erpnext_extensions.facility_management.doctype.facility.facility.preview_receipt_journal_entry",
				args: { name: cur_frm.doc.name },
			});
			return r.message;
		});
		const receiptText = (receiptPrev.rows || []).map((x) => x.user_remark).join(" ");
		results.push({
			test: "C_receipt_preview_facility_name",
			ok: receiptText.includes(prep.facility_name) && !/FAC-\d{4}-\d+/.test(receiptText),
			receiptText,
		});

		await page.evaluate(async (fac) => {
			await frappe.call({
				method:
					"erpnext_extensions.facility_management.doctype.facility.facility.create_receipt_journal_entry",
				args: { name: fac },
			});
		}, prep.facility);

		const repayDraft = bench(
			"erpnext_extensions.facility_management.e2e.facility_type_templates_prep.create_draft_repayment_for_facility",
			JSON.stringify([prep.facility])
		);
		await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(repayDraft.repayment)}`, {
			waitUntil: "domcontentloaded",
		});
		await page.waitForFunction(() => cur_frm?.doc?.doctype === "Facility Repayment", { timeout: 180000 });
		const repayPrev = await page.evaluate(async () => {
			const r = await frappe.call({
				method:
					"erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
				args: { doc: cur_frm.doc },
			});
			erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog(
				r.message,
				"Repayment Preview"
			);
			return r.message;
		});
		await page.waitForSelector(".modal-dialog:visible", { timeout: 30000 });
		evidence.screenshots.repayment_preview = await shot(page, "D_repayment_preview");
		const facDoc = await page.evaluate(async (fac) => {
			const d = await frappe.db.get_doc("Facility", fac);
			return d.facility_name;
		}, prep.facility);
		const repayText = (repayPrev.rows || []).map((x) => x.user_remark).join(" ");
		results.push({
			test: "D_repayment_preview_facility_name",
			ok: repayText.includes(facDoc),
			repayText,
		});

		results.push({
			test: "E_settings_templates_migrated",
			ok: tmpl.uses_facility_name && tmpl.matches_new_default,
			tmpl,
		});

		const reportCheck = await page.evaluate(
			async ({ company, ft, fname }) => {
				const typeSearch = await frappe.call({
					method: "frappe.desk.search.search_link",
					args: { doctype: "Facility Type", txt: ft.slice(0, 6), page_length: 10 },
				});
				const facSearch = await frappe.call({
					method: "frappe.desk.search.search_link",
					args: { doctype: "Facility", txt: fname.slice(0, 8), page_length: 10 },
				});
				return {
					typeHits: (typeSearch.message || []).length,
					facHits: (facSearch.message || []).length,
				};
			},
			{ company: prep.company, ft: prep.facility_type, fname: prep.facility_name }
		);
		results.push({
			test: "F_reports_search_facility_type_and_name",
			ok: reportCheck.typeHits >= 1 && reportCheck.facHits >= 1,
			reportCheck,
		});
	} finally {
		await browser.close();
	}

	const all_ok = results.every((r) => r.ok);
	console.log(JSON.stringify({ all_ok, results, evidence }, null, 2));
	process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
