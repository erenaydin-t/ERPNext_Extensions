/**
 * Facility Repayment: draft account/dimension overrides → preview → submit → read-only.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute, waitDocstatus, getDocumentState } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "repayment_draft_overrides");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

const ACCOUNT_FIELDS = [
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
];
const DIMENSION_FIELDS = ["cost_center", "department", "bank_dimension", "bank_account_dimension"];
const ALL_FIELDS = [...ACCOUNT_FIELDS, ...DIMENSION_FIELDS];
const SECTION_FIELDS = ["section_accounts", "section_dimensions"];

function bench(method) {
	return benchExecute(method);
}

async function login(page) {
	await page.goto(`${BASE}/login`, { waitUntil: "load", timeout: 120000 });
	await page.waitForSelector("#login_email", { state: "visible", timeout: 60000 });
	await page.fill("#login_email", process.env.FRAPPE_E2E_USER || "Administrator");
	await page.fill("#login_password", process.env.FRAPPE_E2E_PASSWORD || "admin");
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitFormShell(page) {
	await page.waitForFunction(
		() =>
			window.cur_frm?.doc?.doctype === "Facility Repayment" &&
			!window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
}

async function waitFieldsInForm(page, fieldnames) {
	await page.waitForFunction(
		(fields) => {
			const frm = window.cur_frm;
			if (!frm || frm.is_loading || frm.doc.docstatus > 1) {
				return false;
			}
			for (const sec of ["section_accounts", "section_dimensions"]) {
				const head = frm.fields_dict?.[sec]?.$wrapper?.[0]?.querySelector?.(".section-head");
				if (head?.classList.contains("collapsed")) {
					head.click();
				}
			}
			return fields.every((fn) => {
				try {
					frm.scroll_to_field(fn);
				} catch {
					/* ignore */
				}
				return !!frm.fields_dict?.[fn];
			});
		},
		fieldnames,
		{ timeout: 180000, polling: 500 }
	);
}

/**
 * Wait for account/dimension controls in fields_dict; expand sections; audit via df.read_only.
 */
async function waitAndAuditRepaymentFields(page, fieldnames, { docstatusExpected, expectEditable }) {
	return page.evaluate(
		async ({ fieldnames, sectionFields, docstatusExpected, expectEditable }) => {
			const cint = (v) => parseInt(v, 10) || 0;
			const deadline = Date.now() + 180000;

			const readFieldState = (fn) => {
				const frm = window.cur_frm;
				const fld =
					frm?.fields_dict?.[fn] ||
					(typeof frm?.get_field === "function" ? frm.get_field(fn) : null);
				const df =
					fld?.df ||
					frappe.meta.get_docfield(frm.doctype, fn, frm.doc.name) ||
					frappe.meta.get_docfield(frm.doctype, fn);

				const in_fields_dict = !!(frm?.fields_dict?.[fn] || fld);
				const has_wrapper = !!(fld && fld.$wrapper && fld.$wrapper.length);

				if (!in_fields_dict || !df) {
					if (frm.doc.docstatus === 1) {
						return {
							state: "read_only",
							in_fields_dict,
							has_wrapper,
							df_read_only: df?.read_only,
							disabled: fld?.disable,
							reason: "submitted_document",
						};
					}
					return {
						state: "not_rendered",
						in_fields_dict,
						has_wrapper,
						df_read_only: df?.read_only,
						disabled: fld?.disable,
					};
				}

				const dfReadOnly = cint(df.read_only);
				const controlDisabled = fld?.disable === true || fld?.read_only === true;
				const readOnly = dfReadOnly === 1 || controlDisabled;

				return {
					state: readOnly ? "read_only" : "editable",
					in_fields_dict,
					has_wrapper,
					df_read_only: dfReadOnly,
					disabled: fld?.disable,
					fetch_if_empty: cint(df.fetch_if_empty),
				};
			};

			const expandSections = () => {
				const frm = window.cur_frm;
				for (const sec of sectionFields) {
					const s = frm.fields_dict?.[sec];
					if (!s?.$wrapper) {
						continue;
					}
					const head = s.$wrapper[0]?.querySelector?.(".section-head");
					if (head?.classList.contains("collapsed")) {
						head.click();
					}
					if (typeof s.collapse === "function") {
						try {
							s.collapse(false);
						} catch {
							/* ignore */
						}
					}
				}
			};

			let audit = {};
			while (Date.now() < deadline) {
				const frm = window.cur_frm;
				if (!frm || frm.is_loading || frm.doc.docstatus !== docstatusExpected) {
					await new Promise((r) => setTimeout(r, 350));
					continue;
				}

				expandSections();

				for (const fn of fieldnames) {
					try {
						await frm.scroll_to_field(fn);
					} catch {
						/* ignore */
					}
					if (frm.fields_dict[fn]?.refresh) {
						frm.fields_dict[fn].refresh();
					}
				}

				audit = {};
				let allRendered = true;
				for (const fn of fieldnames) {
					audit[fn] = readFieldState(fn);
					if (audit[fn].state === "not_rendered") {
						allRendered = false;
					}
				}

				if (allRendered) {
					const statesOk = fieldnames.every((fn) => {
						const st = audit[fn].state;
						return expectEditable ? st === "editable" : st === "read_only";
					});
					if (statesOk) {
						return {
							ok: true,
							audit,
							docstatus: frm.doc.docstatus,
							doctype: frm.doctype,
						};
					}
				}

				await new Promise((r) => setTimeout(r, 400));
			}

			return {
				ok: false,
				audit,
				docstatus: window.cur_frm?.doc?.docstatus,
				doctype: window.cur_frm?.doctype,
				timeout: true,
			};
		},
		{
			fieldnames,
			sectionFields: SECTION_FIELDS,
			docstatusExpected,
			expectEditable,
		}
	);
}

async function applyOverridesViaApi(page, repayment, overrides) {
	await page.evaluate(async (ovr) => {
		const doc = cur_frm.doc;
		for (const [fn, val] of Object.entries(ovr)) {
			if (!val) {
				continue;
			}
			await frappe.call({
				method: "frappe.client.set_value",
				args: {
					doctype: doc.doctype,
					name: doc.name,
					fieldname: fn,
					value: val,
				},
			});
		}
	}, overrides);
	await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(repayment)}`, {
		waitUntil: "domcontentloaded",
	});
	await waitFormShell(page);
	await waitFieldsInForm(page, ALL_FIELDS);
}

async function run() {
	const prep = bench(
		"erpnext_extensions.facility_management.e2e.facility_repayment_draft_override_prep.prepare_repayment_draft_override_e2e"
	);
	const overrides = prep.overrides || {};
	const results = [];

	const browser = await chromium.launch({ headless: true });
	const page = await (
		await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 900 } })
	).newPage();
	page.setDefaultTimeout(180000);
	page.setDefaultNavigationTimeout(180000);
	try {
		await login(page);
		await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(prep.repayment)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitFormShell(page);
		await waitFieldsInForm(page, ALL_FIELDS);

		const draftAudit = await waitAndAuditRepaymentFields(page, ALL_FIELDS, {
			docstatusExpected: 0,
			expectEditable: true,
		});
		results.push({
			test: "draft_fields_editable",
			ok: draftAudit.ok === true,
			draftAudit,
		});

		await applyOverridesViaApi(page, prep.repayment, overrides);

		const afterEdit = await page.evaluate((fields) => {
			const doc = {};
			for (const fn of fields) {
				doc[fn] = cur_frm.doc[fn];
			}
			return doc;
		}, ALL_FIELDS);
		results.push({
			test: "manual_overrides_on_form",
			ok: ACCOUNT_FIELDS.every((fn) => afterEdit[fn] === overrides[fn]),
			afterEdit,
		});

		await page.evaluate(async () => {
			await frappe.call({
				method: "frappe.client.save",
				args: { doc: cur_frm.doc },
			});
		});
		await page.waitForTimeout(800);
		await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(prep.repayment)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitFormShell(page);
		await page.reload({ waitUntil: "domcontentloaded" });
		await waitFormShell(page);
		await waitFieldsInForm(page, ALL_FIELDS);

		const reloadAudit = await waitAndAuditRepaymentFields(page, ALL_FIELDS, {
			docstatusExpected: 0,
			expectEditable: true,
		});
		const afterSaveReload = await page.evaluate((fields) => {
			const doc = {};
			for (const fn of fields) {
				doc[fn] = cur_frm.doc[fn];
			}
			return doc;
		}, ALL_FIELDS);
		results.push({
			test: "save_reload_f5_values_and_editable",
			ok:
				reloadAudit.ok === true &&
				ACCOUNT_FIELDS.every((fn) => afterSaveReload[fn] === overrides[fn]),
			reloadAudit,
			afterSaveReload,
		});

		fs.mkdirSync(SCREEN, { recursive: true });
		await page.screenshot({ path: path.join(SCREEN, "01_draft_overrides.png"), fullPage: true });

		const preview = await page.evaluate(async () => {
			const r = await frappe.call({
				method:
					"erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
				args: { doc: cur_frm.doc },
			});
			return r.message;
		});
		const previewAccounts = new Set((preview.rows || []).map((row) => row.account));
		results.push({
			test: "preview_uses_overrides",
			ok:
				preview.balanced &&
				previewAccounts.has(overrides.bank_account) &&
				previewAccounts.has(overrides.interest_expense_account),
			previewAccounts: [...previewAccounts],
		});
		await page.screenshot({ path: path.join(SCREEN, "02_preview.png"), fullPage: true });

		const submitted = await page.evaluate(async () => {
			const r = await frappe.call({
				method: "frappe.client.submit",
				args: { doc: cur_frm.doc },
			});
			return r.message || {};
		});
		const dbJe = await waitDocstatus("Journal Entry", submitted.journal_entry, 1, {
			timeoutMs: 120000,
		});
		const dbRepay = await waitDocstatus("Facility Repayment", prep.repayment, 1, {
			timeoutMs: 120000,
		});

		const jeAccounts = await page.evaluate(async (je) => {
			const doc = await frappe.db.get_doc("Journal Entry", je);
			return doc.accounts.map((a) => a.account);
		}, submitted.journal_entry);
		results.push({
			test: "submit_je_uses_overrides",
			ok:
				!!submitted.journal_entry &&
				dbJe.ok &&
				dbRepay.ok &&
				jeAccounts.includes(overrides.bank_account) &&
				jeAccounts.includes(overrides.interest_expense_account),
			je: submitted.journal_entry,
			jeAccounts,
			db: {
				je: getDocumentState("Journal Entry", submitted.journal_entry, ["name", "docstatus"]),
				repayment: getDocumentState("Facility Repayment", prep.repayment, ["name", "docstatus"]),
			},
		});

		await page.goto(`${BASE}/desk/journal-entry/${encodeURIComponent(submitted.journal_entry)}`, {
			waitUntil: "domcontentloaded",
		});
		await page.waitForTimeout(2000);
		await page.screenshot({ path: path.join(SCREEN, "03_submitted_je.png"), fullPage: true });

		await page.goto(`${BASE}/desk/facility-repayment/${encodeURIComponent(prep.repayment)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitFormShell(page);
		await waitFieldsInForm(page, ALL_FIELDS);

		const submittedAudit = await waitAndAuditRepaymentFields(page, ALL_FIELDS, {
			docstatusExpected: 1,
			expectEditable: false,
		});
		results.push({
			test: "submitted_fields_read_only",
			ok: submittedAudit.ok === true,
			submittedAudit,
		});
		await page.screenshot({ path: path.join(SCREEN, "04_submitted_read_only.png"), fullPage: true });
	} finally {
		await browser.close();
	}

	const all_ok = results.every((r) => r.ok);
	console.log(JSON.stringify({ all_ok, results, screenshots: SCREEN, prep: prep.repayment }, null, 2));
	process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
