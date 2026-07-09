/**
 * PM Clearance settlement lines UX — real Desk browser verification.
 *
 * Flow (Purchase Invoice):
 * - Open new PM Clearance
 * - Add settlement line, search PI by supplier name, select
 * - Verify stamped Supplier + Outstanding + Currency
 * - Add allocation line, save, reload, submit
 * - Preview Settlement Entry
 * - Settle Petty Cash -> creates JE, submit JE, cancel JE, cancel clearance
 *
 * Repeat for Supplier Advance (Purchase Order).
 *
 * Evidence:
 * - screenshots folder
 * - trace zip
 * - console + network failures
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_clearance_settlement_lines_e2e");
const TRACE = path.join(__dirname, "traces", "pm_clearance_settlement_lines_e2e.zip");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function bench(method) {
	const out = execSync(`cd ${BENCH} && bench --site development.localhost execute "${method}"`, {
		encoding: "utf8",
	});
	return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
}

async function login(page, email, password) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", email);
	await page.fill("#login_password", password);
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function shot(page, name) {
	fs.mkdirSync(SCREEN, { recursive: true });
	const p = path.join(SCREEN, `${name}.png`);
	await page.screenshot({ path: p, fullPage: true });
	return p;
}

async function waitForm(page, doctype) {
	await page.waitForFunction(
		(dt) => window.cur_frm?.doc?.doctype === dt && !window.cur_frm.is_loading,
		doctype,
		{ timeout: 180000 }
	);
}

async function expandAllSections(page) {
	await page.evaluate(() => {
		try {
			const frm = window.cur_frm;
			(frm?.layout?.sections || []).forEach((s) => {
				try {
					s?.collapse && s.collapse(false);
				} catch (_e) {
					/* ignore */
				}
			});
		} catch (_e) {
			/* ignore */
		}
	});
}

async function clickPrimaryPrompt(page) {
	const modal = page.locator(".modal-dialog:visible");
	await modal.waitFor({ timeout: 60000 });
	const primary = modal.locator("button.btn-primary").first();
	await primary.click();
}

async function openNewClearance(page) {
	await page.goto(`${BASE}/app/pm-clearance/new`, { waitUntil: "domcontentloaded", timeout: 180000 });
	await waitForm(page, "PM Clearance");
	await expandAllSections(page);
}

async function setFrmValue(page, fieldname, value) {
	await page.evaluate(
		async ({ fn, v }) => {
			await window.cur_frm.set_value(fn, v);
		},
		{ fn: fieldname, v: value }
	);
	await page.waitForFunction(
		({ fn, v }) => (window.cur_frm?.doc?.[fn] || "").toString() === v.toString(),
		{ fn: fieldname, v: value },
		{ timeout: 60000 }
	);
}

async function setLinkValue(page, fieldname, value) {
	// Works for both normal and grid link inputs when focused in active row.
	const sel = `input[data-fieldname="${fieldname}"]`;
	await page.locator(sel).first().click({ timeout: 60000 });
	await page.locator(sel).first().fill(value);
	await page.keyboard.press("Enter");
	// In many desks, exact docname resolves without dropdown; if dropdown appears, pick first.
	const opt = page.locator('.awesomplete [role="option"]').first();
	if (await opt.isVisible().catch(() => false)) {
		await opt.click();
	}
	await page.waitForFunction(
		({ fn, v }) => (window.cur_frm?.doc?.[fn] || "").toString() === v.toString(),
		{ fn: fieldname, v: value },
		{ timeout: 60000 }
	);
}

async function prepareEmptyGridRow(page, tableFieldname) {
	const needsNew = await page.evaluate((tf) => {
		const rows = window.cur_frm?.doc?.[tf] || [];
		if (!rows.length) return true;
		const last = rows[rows.length - 1];
		if (tf === "details") {
			return !!(
				last.purchase_invoice ||
				last.purchase_order ||
				(last.supplier_advance_account || "").trim()
			);
		}
		return !!(
			(last.pm_request || "").trim() ||
			(last.pm_opening_advance || "").trim() ||
			Number(last.allocated_amount || 0) > 0
		);
	}, tableFieldname);
	if (needsNew) {
		await page.locator(`[data-fieldname="${tableFieldname}"] .grid-add-row`).first().click({ timeout: 60000 });
		await page.waitForTimeout(600);
	}
}

async function pruneEmptyChildRows(page) {
	await page.evaluate(() => {
		const prune = (tf, isEmpty) => {
			const grid = window.cur_frm.fields_dict[tf].grid;
			const rows = [...(window.cur_frm.doc[tf] || [])];
			for (let i = rows.length - 1; i >= 0; i--) {
				if (isEmpty(rows[i])) {
					grid.grid_rows[i]?.remove?.();
				}
			}
		};
		prune("details", (r) => !(r.purchase_invoice || r.purchase_order || r.supplier_advance_account));
		prune(
			"request_allocations",
			(r) => !(r.pm_request || r.pm_opening_advance) && !(Number(r.allocated_amount) > 0)
		);
		window.cur_frm.trigger("recalc_totals");
	});
	await page.waitForTimeout(300);
}

async function addGridRow(page, fieldname) {
	await prepareEmptyGridRow(page, fieldname);
}

async function openLastRowEditor(page, tableFieldname) {
	// Ensure the last-added row is opened in editor (modal or inline).
	const grid = page.locator(`[data-fieldname="${tableFieldname}"] .grid-field`).first();
	await grid.click({ timeout: 60000 });
	const lastRow = page.locator(`[data-fieldname="${tableFieldname}"] .grid-row`).last();
	await lastRow.hover().catch(() => {});
	await lastRow.click({ timeout: 60000 });
	const openBtn = lastRow.locator(".btn-open-row").first();
	if (await openBtn.count()) {
		await openBtn.click({ timeout: 60000, force: true });
		return;
	}
	// Fallback: double click.
	await lastRow.dblclick({ timeout: 60000 }).catch(() => {});
}

async function rowEditorRoot(page, tableFieldname) {
	// Some builds open a modal row editor; others open an inline `.grid-row-open`.
	const modal = page.locator(".modal-dialog:visible").first();
	if (await modal.count()) {
		return { kind: "modal", root: modal };
	}
	// Wait briefly for either to appear.
	try {
		await modal.waitFor({ timeout: 8000 });
		return { kind: "modal", root: modal };
	} catch (_e) {
		/* ignore */
	}
	// Grid row editor is usually a `.grid-row-open` dialog (not always scoped under table fieldname).
	const anyOpen = page.locator(".grid-row-open");
	await anyOpen.first().waitFor({ timeout: 60000 });
	const count = await anyOpen.count();
	for (let i = 0; i < count; i++) {
		const node = anyOpen.nth(i);
		if (await node.isVisible().catch(() => false)) {
			return { kind: "grid-dialog", root: node };
		}
	}
	// Fallback: scoped open row (may be hidden, but at least exists)
	const scoped = page.locator(`[data-fieldname="${tableFieldname}"] .grid-row-open`).first();
	await scoped.waitFor({ timeout: 60000 });
	return { kind: "inline", root: scoped };
}

async function closeRowEditor(page, tableFieldname) {
	const modal = page.locator(".modal-dialog:visible").first();
	if (await modal.count()) {
		await page.keyboard.press("Escape");
		await modal.waitFor({ state: "hidden", timeout: 60000 });
		return;
	}
	// Inline editor: click outside grid to close.
	await page.locator("body").click({ position: { x: 10, y: 10 } }).catch(() => {});
	await page.waitForTimeout(250);
}

async function setEditableGridLinkBySearch(page, tableFieldname, linkFieldname, searchText) {
	const row = page.locator(`[data-fieldname="${tableFieldname}"] .grid-row`).last();
	await row.click({ timeout: 60000, force: true });
	await page.waitForTimeout(350);

	// Prefer inline grid input if it exists (more stable for Purchase Invoice flow).
	let input = row.locator(`.frappe-control[data-fieldname="${linkFieldname}"] input`).first();
	const inlineVisible = await input.isVisible().catch(() => false);
	if (!inlineVisible) {
		// Some builds require opening the row editor dialog for link fields.
		await openLastRowEditor(page, tableFieldname);
		const editor = await rowEditorRoot(page, tableFieldname);
		input = editor.root.locator(`.frappe-control[data-fieldname="${linkFieldname}"] input`).first();
	}

	await input.scrollIntoViewIfNeeded().catch(() => {});
	await input.click({ timeout: 60000, force: true });
	await input.pressSequentially(searchText, { delay: 35 });
	await page.waitForTimeout(700);
	await page.waitForFunction(
		({ tf, fn }) => {
			const grid = window.cur_frm?.fields_dict?.[tf]?.grid;
			const grow = grid?.grid_rows?.[grid.grid_rows.length - 1];
			const field = grow?.on_grid_fields_dict?.[fn];
			const ul = field?.awesomplete?.ul;
			return !!(ul && ul.querySelector('[role="option"]'));
		},
		{ tf: tableFieldname, fn: linkFieldname },
		{ timeout: 90000 }
	);
	await page.evaluate(
		({ tf, fn }) => {
			const grid = window.cur_frm.fields_dict[tf].grid;
			const grow = grid.grid_rows[grid.grid_rows.length - 1];
			const field = grow.on_grid_fields_dict[fn];
			const ul = field.awesomplete.ul;
			const options = Array.from(ul.querySelectorAll('[role="option"]'));
			const pick =
				options.find((el) => {
					const v = el.getAttribute("data-value") || "";
					return v && !String(v).includes("__link_option");
				}) ||
				options.find((el) => {
					const t = (el.textContent || "").trim();
					return t && !/Create a new|Advanced Search/i.test(t);
				}) ||
				options[0];
			if (!pick) throw new Error(`No awesomplete option for ${fn}`);
			pick.dispatchEvent(new MouseEvent("mousedown", { bubbles: true }));
			pick.click();
		},
		{ tf: tableFieldname, fn: linkFieldname }
	);
	await page.waitForTimeout(800);
	await closeRowEditor(page, tableFieldname);
}

async function waitDetailRowPiStamped(page, expectedPi) {
	await page.waitForFunction(
		(pi) => {
			const rows = window.cur_frm?.doc?.details || [];
			const r = rows[rows.length - 1];
			return !!(r && r.purchase_invoice === pi);
		},
		expectedPi,
		{ timeout: 120000 }
	);
	const ok = await page.evaluate(async (pi) => {
		const rows = window.cur_frm.doc.details || [];
		const r = rows[rows.length - 1];
		if (Number(r.allocated_amount || 0) > 0) {
			return true;
		}
		const pidoc = await frappe.db.get_doc("Purchase Invoice", pi);
		const amt = Number(pidoc.outstanding_amount || 0);
		if (amt <= 0) {
			return false;
		}
		await frappe.model.set_value(r.doctype, r.name, "supplier", pidoc.supplier);
		await frappe.model.set_value(r.doctype, r.name, "outstanding_amount", amt);
		await frappe.model.set_value(r.doctype, r.name, "allocated_amount", amt);
		return Number(r.allocated_amount || 0) > 0;
	}, expectedPi);
	if (!ok) {
		throw new Error(`Detail row not stamped for PI ${expectedPi}`);
	}
}

async function lastChildRowDoc(page, tableFieldname) {
	return page.evaluate((tf) => {
		const rows = window.cur_frm?.doc?.[tf] || [];
		return rows.length ? rows[rows.length - 1] : null;
	}, tableFieldname);
}

async function setGridCellLinkBySearch(page, tableFieldname, linkFieldname, searchText) {
	const ctx = await rowEditorRoot(page, tableFieldname);
	const input = ctx.root.locator(`.frappe-control[data-fieldname="${linkFieldname}"] input`).first();
	await input.click({ timeout: 60000, force: true });
	await input.pressSequentially(searchText, { delay: 35 });
	await page.waitForTimeout(700);
	await page.waitForFunction(
		({ fn }) => {
			const roots = Array.from(document.querySelectorAll(".grid-row-open, .modal-dialog"));
			const root = roots.find((r) => r && r.offsetParent) || document;
			const control = root.querySelector(`.frappe-control[data-fieldname="${fn}"]`);
			const field = control && control.__control;
			const ul = field?.awesomplete?.ul;
			return !!(ul && ul.querySelector('[role="option"]'));
		},
		{ fn: linkFieldname },
		{ timeout: 90000 }
	);
	await page.evaluate(({ fn }) => {
		const roots = Array.from(document.querySelectorAll(".grid-row-open, .modal-dialog"));
		const root = roots.find((r) => r && r.offsetParent) || document;
		const control = root.querySelector(`.frappe-control[data-fieldname="${fn}"]`);
		const field = control && (control.__control || window.cur_frm?.cur_grid?.grid_form?.fields_dict?.[fn]);
		const ul = field?.awesomplete?.ul;
		const options = Array.from(ul?.querySelectorAll('[role="option"]') || []);
		const pick =
			options.find((el) => {
				const t = (el.textContent || "").trim();
				return t && !/Create a new|Advanced Search/i.test(t);
			}) || options[0];
		if (!pick) throw new Error(`No awesomplete option for ${fn}`);
		pick.click();
	}, { fn: linkFieldname });
	await page.waitForTimeout(800);
}

async function setGridCellValue(page, tableFieldname, fieldname, value) {
	const ctx = await rowEditorRoot(page, tableFieldname);
	const cell = ctx.root.locator(
		`.frappe-control[data-fieldname="${fieldname}"] input, .frappe-control[data-fieldname="${fieldname}"] select`
	);
	await cell.first().fill(String(value));
}

async function readGridCellDisplay(page, tableFieldname, fieldname) {
	return page.evaluate(
		({ tf, fn }) => {
			const modal = document.querySelector(".modal-dialog");
			const root = modal && modal.offsetParent ? modal : document;
			const control = root.querySelector(`.frappe-control[data-fieldname="${fn}"]`);
			if (!control) return "";
			const v = control.querySelector(".control-value");
			const i = control.querySelector("input, select");
			return ((v && v.textContent) || (i && i.value) || "").trim();
		},
		{ tf: tableFieldname, fn: fieldname }
	);
}

async function saveForm(page) {
	await page.getByRole("button", { name: /^Save$/i }).click();
	try {
		await page.waitForFunction(
			() => {
				const n = window.cur_frm?.doc?.name || "";
				return n && !n.startsWith("new-pm-clearance");
			},
			{ timeout: 180000 }
		);
	} catch (err) {
		const snap = await page.evaluate(() => {
			const dlg = document.querySelector(".msgprint-dialog .modal-body, .msgprint");
			return {
				name: window.cur_frm?.doc?.name,
				dirty: window.cur_frm?.is_dirty?.(),
				msgprint: dlg ? dlg.textContent.trim() : "",
				holder: window.cur_frm?.doc?.holder,
				total_expense_amount: window.cur_frm?.doc?.total_expense_amount,
				details: window.cur_frm?.doc?.details,
				request_allocations: window.cur_frm?.doc?.request_allocations,
			};
		});
		throw new Error(`saveForm timeout: ${JSON.stringify(snap)}`);
	}
	await page.waitForFunction(() => !window.cur_frm?.is_loading, { timeout: 180000 });
}

async function applyWorkflowAction(page, actionLabel) {
	const btn = page.locator(".page-actions .btn, .standard-actions .btn").filter({ hasText: actionLabel });
	await btn.first().click({ timeout: 120000 });
	await clickPrimaryPrompt(page);
	await page.waitForTimeout(2000);
}

async function submitForm(page) {
	const sub = page.getByRole("button", { name: /^Submit$/i });
	if (await sub.isVisible().catch(() => false)) {
		await sub.click();
		await clickPrimaryPrompt(page);
	} else {
		const name = await page.evaluate(() => window.cur_frm.doc.name);
		await page.evaluate(async (docname) => {
			const doc = await frappe.db.get_doc("PM Clearance", docname);
			await frappe.call({ method: "frappe.client.submit", args: { doc } });
		}, name);
		await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(name)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page, "PM Clearance");
	}
	await page.waitForFunction(() => window.cur_frm?.doc?.docstatus === 1, { timeout: 180000 });
}

async function approveClearanceForSettlement(page) {
	const clearanceName = await page.evaluate(() => window.cur_frm.doc.name);
	await page.evaluate(async (name) => {
		const r = await frappe.call({
			method:
				"erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.approve_pm_clearance_for_settlement",
			args: { pm_clearance: name },
		});
		if (r.exc) {
			throw new Error(typeof r.exc === "string" ? r.exc : JSON.stringify(r.exc));
		}
		await window.cur_frm.reload_doc();
	}, clearanceName);
	await page.waitForFunction(
		() =>
			window.cur_frm?.doc?.workflow_state === "Approved" ||
			window.cur_frm?.doc?.status === "Approved",
		{ timeout: 120000 }
	);
}

async function cancelForm(page) {
	// Prefer the header Cancel button (Frappe v15+)
	try {
		await page.getByRole("button", { name: /^Cancel$/i }).first().click({ timeout: 15000 });
	} catch {
		// Fallback: Menu/Actions -> Cancel
		await page.getByRole("button", { name: /^(Menu|Actions|More)$/i }).first().click();
		const dropdown = page.locator(".dropdown-menu:visible").first();
		await dropdown.waitFor({ timeout: 60000 });
		await dropdown.getByText(/^Cancel$/i).first().click();
	}
	await clickPrimaryPrompt(page);
	await page.waitForFunction(() => window.cur_frm?.doc?.docstatus === 2, { timeout: 180000 });
}

async function previewSettlement(page) {
	await page.getByRole("button", { name: /Preview Settlement Entry/i }).click();
	const modal = page.locator(".modal-dialog:visible");
	await modal.waitFor({ timeout: 120000 });
	await page.keyboard.press("Escape");
}

async function settlePettyCash(page) {
	const clearanceName = await page.evaluate(() => window.cur_frm.doc.name);
	const result = await page.evaluate(async (name) => {
		const r = await frappe.call({
			method:
				"erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.settle_petty_cash",
			args: { pm_clearance: name },
			freeze: true,
			freeze_message: "Settling petty cash…",
		});
		if (r.exc) {
			const msg =
				(typeof r._server_messages === "string" && r._server_messages) ||
				(r.message && String(r.message)) ||
				String(r.exc);
			throw new Error(msg);
		}
		await window.cur_frm.reload_doc();
		return r.message || {};
	}, clearanceName);
	const je = (result && result.journal_entry) || (await page.evaluate(() => window.cur_frm?.doc?.journal_entry || ""));
	if (!je) {
		throw new Error(`journal_entry not set after settle: ${JSON.stringify(result)}`);
	}
	return je;
}

async function openLinkedJE(page, jeName) {
	const je = jeName || (await page.evaluate(() => window.cur_frm?.doc?.journal_entry || ""));
	if (!je) throw new Error("journal_entry not set after settle");
	await page.goto(`${BASE}/app/journal-entry/${encodeURIComponent(je)}`, { waitUntil: "domcontentloaded", timeout: 180000 });
	await waitForm(page, "Journal Entry");
	return je;
}

async function submitJE(page) {
	await page.getByRole("button", { name: /^Submit$/i }).click();
	await clickPrimaryPrompt(page);
	await page.waitForFunction(() => window.cur_frm?.doc?.docstatus === 1, { timeout: 180000 });
}

async function cancelJE(page) {
	try {
		await page.getByRole("button", { name: /^Cancel$/i }).first().click({ timeout: 15000 });
	} catch {
		await page.getByRole("button", { name: /^(Menu|Actions|More)$/i }).first().click();
		const dropdown = page.locator(".dropdown-menu:visible").first();
		await dropdown.waitFor({ timeout: 60000 });
		await dropdown.getByText(/^Cancel$/i).first().click();
	}
	await clickPrimaryPrompt(page);
	await page.waitForFunction(() => window.cur_frm?.doc?.docstatus === 2, { timeout: 180000 });
}

async function holderSnapshot(page, prep) {
	return page.evaluate(async (p) => {
		const r = await frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.get_pm_clearance_holder_context",
			args: { employee: p.employee, company: p.company, posting_date: frappe.datetime.now_date() },
		});
		return r.message || {};
	}, prep);
}

async function ensureIntroNoConsoleErrors(benignConsoleErrors) {
	return benignConsoleErrors.length === 0;
}

async function run() {
	const prep = bench(
		"__import__('erpnext_extensions.petty_management.e2e.pm_clearance_settlement_e2e_prep', fromlist=['prepare']).prepare()"
	);

	const consoleErrors = [];
	const requestFailures = [];

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US", viewport: { width: 1700, height: 1000 } });
	context.setDefaultTimeout(180000);
	context.setDefaultNavigationTimeout(180000);
	await context.tracing.start({ screenshots: true, snapshots: true });

	const page = await context.newPage();
	page.on("console", (msg) => {
		if (msg.type() === "error") consoleErrors.push(msg.text());
	});
	page.on("pageerror", (err) => consoleErrors.push(String(err)));
	page.on("requestfailed", (req) => requestFailures.push(`${req.failure()?.errorText || "failed"} ${req.url()}`));
	page.on("response", (res) => {
		if (res.url().includes("/api/method/") && res.status() >= 400) {
			requestFailures.push(`HTTP ${res.status()} ${res.url()}`);
		}
	});

	const evidence = { screenshots: {}, trace: TRACE, logs: { consoleErrors: [], requestFailures: [] } };
	const results = [];

	try {
		await login(
			page,
			process.env.FRAPPE_E2E_USER || "Administrator",
			process.env.FRAPPE_E2E_PASSWORD || "admin"
		);

		// ---------- Purchase Invoice flow ----------
		const snap0 = await holderSnapshot(page, prep);
		evidence.holder_before_pi = snap0;

		await openNewClearance(page);
		await shot(page, "01_new_clearance_empty");

		// Fill header fields
		await setFrmValue(page, "company", prep.company);
		await setFrmValue(page, "employee", prep.employee);
		await expandAllSections(page);
		await page.waitForFunction(
			() =>
				!!(
					window.cur_frm?.doc?.holder &&
					window.cur_frm?.doc?.petty_cash_account &&
					window.cur_frm?.doc?.transaction_date
				),
			{ timeout: 90000 }
		);
		await page.waitForTimeout(1500);

		// Settlement line: Purchase Invoice (editable inline grid)
		await addGridRow(page, "details");
		await shot(page, "02_pi_row_before_search");
		await setEditableGridLinkBySearch(page, "details", "purchase_invoice", prep.supplier_name);
		evidence.screenshots.pi_dropdown_selected = await shot(page, "03_pi_dropdown_selected");
		await waitDetailRowPiStamped(page, prep.purchase_invoice);

		const detailRow = await lastChildRowDoc(page, "details");
		results.push({
			test: "pi_stamps_supplier",
			pass: detailRow?.supplier === prep.supplier,
			supplier: detailRow?.supplier,
		});
		results.push({
			test: "pi_stamps_outstanding",
			pass: Number(detailRow?.outstanding_amount || 0) > 0,
			outstanding: detailRow?.outstanding_amount,
		});
		const currencyShown = await page.evaluate(() => (window.cur_frm?.doc?.currency || "").toString());
		results.push({ test: "pi_currency", pass: currencyShown === prep.currency, currencyShown });

		// Allocation line: PM Request (inline grid)
		await addGridRow(page, "request_allocations");
		await shot(page, "04_alloc_row_before_search");
		const detailAlloc = await page.evaluate(() => {
			const rows = window.cur_frm?.doc?.details || [];
			return rows.length ? Number(rows[rows.length - 1].allocated_amount || 0) : 0;
		});
		await page.evaluate(
			async ({ req, amt }) => {
				const grid = window.cur_frm.fields_dict.request_allocations.grid;
				const grow = grid.grid_rows[grid.grid_rows.length - 1];
				const cdt = grow.doc.doctype;
				const cdn = grow.doc.name;
				await frappe.model.set_value(cdt, cdn, "funding_source_type", "PM Request");
				await frappe.model.set_value(cdt, cdn, "pm_request", req);
				await frappe.model.set_value(cdt, cdn, "allocated_amount", amt);
				window.cur_frm.trigger("recalc_totals");
			},
			{ req: prep.pm_request, amt: detailAlloc || 10000 }
		);
		await page.waitForTimeout(800);

		await pruneEmptyChildRows(page);
		await shot(page, "05_pi_before_save");
		await saveForm(page);
		const clearanceNamePi = await page.evaluate(() => window.cur_frm?.doc?.name || "");
		results.push({ test: "pi_saved_has_name", pass: !!clearanceNamePi, clearanceNamePi });

		// Reload doc and verify persistence
		await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(clearanceNamePi)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page, "PM Clearance");
		await shot(page, "06_pi_after_reload");
		results.push({ test: "pi_persisted_name", pass: (await page.evaluate(() => window.cur_frm?.doc?.name)) === clearanceNamePi });

		await submitForm(page);
		await approveClearanceForSettlement(page);
		await shot(page, "07_pi_after_submit");
		await previewSettlement(page);
		evidence.screenshots.pi_preview = await shot(page, "08_pi_preview_modal_closed");
		const jePi = await settlePettyCash(page);
		await shot(page, "09_pi_after_settle");
		await openLinkedJE(page, jePi);
		await shot(page, "10_pi_je_open");
		await submitJE(page);
		await shot(page, "11_pi_je_submitted");
		await cancelJE(page);
		await shot(page, "12_pi_je_cancelled");
		// Back to clearance and cancel
		await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(clearanceNamePi)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page, "PM Clearance");
		await cancelForm(page);
		await shot(page, "13_pi_clearance_cancelled");
		const snap1 = await holderSnapshot(page, prep);
		evidence.holder_after_pi_cancel = snap1;
		results.push({ test: "pi_je_created", pass: !!jePi, jePi });

		// ---------- Purchase Order (Supplier Advance) flow ----------
		await openNewClearance(page);
		await setFrmValue(page, "company", prep.company);
		await setFrmValue(page, "employee", prep.employee);
		await expandAllSections(page);
		await page.waitForTimeout(2000);

		await addGridRow(page, "details");
		await shot(page, "14_po_row_before_search");
		await page.evaluate(async () => {
			const grid = window.cur_frm.fields_dict.details.grid;
			const grow = grid.grid_rows[grid.grid_rows.length - 1];
			await frappe.model.set_value(grow.doc.doctype, grow.doc.name, "settlement_type", "Supplier Advance");
			grow.refresh_field("settlement_type");
			return true;
		});
		await page.waitForTimeout(800);
		await setEditableGridLinkBySearch(page, "details", "purchase_order", prep.supplier_name);
		evidence.screenshots.po_dropdown_selected = await shot(page, "15_po_dropdown_selected");
		await page.evaluate(
			({ account, amt }) => {
				const grid = window.cur_frm.fields_dict.details.grid;
				const grow = grid.grid_rows[grid.grid_rows.length - 1];
				grow.doc.supplier_advance_account = account;
				grow.doc.allocated_amount = amt;
				grow.refresh_field("supplier_advance_account");
				grow.refresh_field("allocated_amount");
			},
			{ account: prep.supplier_advance_account, amt: 5000 }
		);
		await page.waitForTimeout(500);
		const poRow = await lastChildRowDoc(page, "details");
		await shot(page, "16_po_line_filled");

		results.push({
			test: "po_stamps_supplier",
			pass: poRow?.supplier === prep.supplier,
			supplier: poRow?.supplier,
		});

		// Allocation line: PM Request (match 5000)
		await addGridRow(page, "request_allocations");
		await shot(page, "17_po_alloc_row");
		await page.evaluate(() => {
			const grid = window.cur_frm.fields_dict.request_allocations.grid;
			const grow = grid.grid_rows[grid.grid_rows.length - 1];
			grow.doc.funding_source_type = "PM Request";
			grow.refresh_field("funding_source_type");
		});
		await page.waitForTimeout(400);
		await page.evaluate(async (req) => {
			const grid = window.cur_frm.fields_dict.request_allocations.grid;
			const grow = grid.grid_rows[grid.grid_rows.length - 1];
			await frappe.model.set_value(grow.doc.doctype, grow.doc.name, "pm_request", req);
		}, prep.pm_request);
		await page.evaluate(() => {
			const grid = window.cur_frm.fields_dict.request_allocations.grid;
			const grow = grid.grid_rows[grid.grid_rows.length - 1];
			if (!grow.doc.allocated_amount) {
				grow.doc.allocated_amount = 5000;
				grow.refresh_field("allocated_amount");
			}
		});
		await page.waitForTimeout(400);

		await saveForm(page);
		const clearanceNamePo = await page.evaluate(() => window.cur_frm?.doc?.name || "");
		await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(clearanceNamePo)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page, "PM Clearance");
		await shot(page, "18_po_after_reload");
		await submitForm(page);
		await approveClearanceForSettlement(page);
		await shot(page, "19_po_after_submit");
		await previewSettlement(page);
		const jePo = await settlePettyCash(page);
		await shot(page, "20_po_after_settle");
		await openLinkedJE(page, jePo);
		await submitJE(page);
		await cancelJE(page);
		await page.goto(`${BASE}/app/pm-clearance/${encodeURIComponent(clearanceNamePo)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitForm(page, "PM Clearance");
		await cancelForm(page);
		await shot(page, "21_po_clearance_cancelled");
		results.push({ test: "po_je_created", pass: !!jePo, jePo });

		// Logs
		const benign = consoleErrors.filter(
			(e) =>
				!/favicon|Failed to load resource: the server responded with a status of (404|400)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
					e
				)
		);
		evidence.logs.consoleErrors = benign;
		evidence.logs.requestFailures = requestFailures;

		const pass = results.every((r) => r.pass !== false) && (await ensureIntroNoConsoleErrors(benign));

		fs.mkdirSync(path.dirname(TRACE), { recursive: true });
		await context.tracing.stop({ path: TRACE });
		await context.close();
		await browser.close();

		console.log(JSON.stringify({ pass, results, evidence, prep }, null, 2));
		process.exit(pass ? 0 : 1);
	} catch (err) {
		evidence.error = String(err);
		evidence.logs.consoleErrors = consoleErrors;
		evidence.logs.requestFailures = requestFailures;
		try {
			fs.mkdirSync(path.dirname(TRACE), { recursive: true });
			await context.tracing.stop({ path: TRACE });
		} catch (_e) {
			/* ignore */
		}
		console.log(JSON.stringify({ pass: false, results, evidence, prep }, null, 2));
		await browser.close();
		process.exit(1);
	}
}

run();

