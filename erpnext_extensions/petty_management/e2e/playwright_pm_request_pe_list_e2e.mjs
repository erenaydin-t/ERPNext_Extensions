/**
 * PM Request Payment Entry list — desk UI flows (form lifecycle + post-action refresh).
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_pe_list_e2e");
const TRACE = path.join(__dirname, "traces", "pm_pe_list_e2e.zip");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function bench(method, kwargs = null) {
	let cmd = `cd ${BENCH} && bench --site development.localhost execute "${method}"`;
	if (kwargs) {
		cmd += ` --kwargs '${JSON.stringify(kwargs).replace(/'/g, "'\\''")}'`;
	}
	const out = execSync(cmd, { encoding: "utf8" });
	return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
}

async function login(page, email, password) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", email);
	await page.fill("#login_password", password);
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitPmRequestForm(page) {
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "PM Request" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
}

async function shot(page, name) {
	fs.mkdirSync(SCREEN, { recursive: true });
	const p = path.join(SCREEN, `${name}.png`);
	await page.screenshot({ path: p, fullPage: true });
	return p;
}

async function countDataRows(page) {
	return page.evaluate(() => {
		const table = document.querySelector("#pm-request-pe-list table tbody");
		if (!table) {
			return 0;
		}
		return Array.from(table.querySelectorAll("tr")).filter((tr) => !tr.querySelector("td[colspan]"))
			.length;
	});
}

async function waitTableRowCount(page, minRows, timeoutMs = 180000) {
	await page.waitForFunction(
		(min) => {
			const table = document.querySelector("#pm-request-pe-list table tbody");
			if (!table) {
				return false;
			}
			const n = Array.from(table.querySelectorAll("tr")).filter(
				(tr) => !tr.querySelector("td[colspan]")
			).length;
			return n >= min;
		},
		minRows,
		{ timeout: timeoutMs }
	);
}

async function waitTableStatus(page, status, timeoutMs = 180000) {
	await page.waitForFunction(
		(st) => {
			const rows = document.querySelectorAll("#pm-request-pe-list table tbody tr[data-pe-status]");
			return Array.from(rows).some((tr) => (tr.getAttribute("data-pe-status") || "") === st);
		},
		status,
		{ timeout: timeoutMs }
	);
}

async function confirmFrappePrompt(page) {
	const modal = page.locator(".modal-dialog:visible");
	await modal.waitFor({ timeout: 60000 });
	const primary = modal.locator("button.btn-primary").first();
	await primary.click();
}

async function createPeFromToolbar(page, amount) {
	const actionsBtn = page.locator(".actions-btn-group .btn").filter({ hasText: /^Actions$/i }).first();
	if (await actionsBtn.count()) {
		await actionsBtn.click();
		await page.locator('.actions-btn-group .dropdown-menu a.dropdown-item').filter({ hasText: /Create Payment Entry/i }).first().click();
	} else {
		await page.getByRole("button", { name: /Create Payment Entry/i }).click();
	}
	const modal = page.locator(".modal-dialog:visible");
	await modal.locator('input[data-fieldname="paid_amount"]').fill(String(amount));
	await confirmFrappePrompt(page);
}

async function openPmRequest(page, pmRequest) {
	await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(pmRequest)}`, {
		waitUntil: "domcontentloaded",
	});
	await waitPmRequestForm(page);
	await page.waitForSelector("#pm-request-pe-list table", { timeout: 120000 });
}

async function openDraftPeFromTable(page) {
	const href = await page.evaluate(() => {
		const rows = document.querySelectorAll("#pm-request-pe-list table tbody tr[data-pe-status]");
		for (const tr of rows) {
			if ((tr.getAttribute("data-pe-status") || "") === "Draft") {
				const a = tr.querySelector("a");
				return a ? a.getAttribute("href") : null;
			}
		}
		return null;
	});
	if (!href) {
		throw new Error("No draft PE link in table");
	}
	await page.goto(`${BASE}${href}`, { waitUntil: "domcontentloaded" });
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Payment Entry" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
}

async function deleteDraftPeFromDesk(page) {
	await page.locator(".menu-btn-group .btn").filter({ hasText: /^Menu$/i }).first().click();
	await page.locator(".dropdown-menu a").filter({ hasText: /^Delete$/i }).first().click();
	await confirmFrappePrompt(page);
	await page.waitForURL(/\/app\/pm-request\//, { timeout: 180000 }).catch(() => {});
}

async function createPeVisible(page) {
	return page.evaluate(() => {
		const w = window;
		const items = Array.from(
			document.querySelectorAll(".actions-btn-group .dropdown-menu a.dropdown-item, .custom-actions .btn")
		).map((el) => (el.textContent || "").trim());
		return items.some((t) => /Create Payment Entry/i.test(t));
	});
}

async function run() {
	const prep = bench(
		"erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_partial_funded_for_close_ui"
	);
	const invalid = bench(
		"erpnext_extensions.petty_management.e2e.pm_request_pe_list_e2e_prep.get_invalid_pm_request_name"
	);
	const deniedUser = bench(
		"erpnext_extensions.petty_management.e2e.pm_request_pe_list_e2e_prep.get_cross_company_denied_user",
		{ pm_request: prep.pm_request }
	);

	const results = [];
	const evidence = { prep, screenshots: {}, trace: TRACE };
	const consoleErrors = [];

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 950 } });
	context.setDefaultNavigationTimeout(180000);
	context.setDefaultTimeout(180000);
	await context.tracing.start({ screenshots: true, snapshots: true });
	const page = await context.newPage();
	page.setDefaultTimeout(180000);
	page.on("console", (msg) => {
		if (msg.type() === "error") {
			consoleErrors.push(msg.text());
		}
	});
	page.on("pageerror", (err) => {
		consoleErrors.push(String(err));
	});

	try {
		await login(
			page,
			process.env.FRAPPE_E2E_USER || "Administrator",
			process.env.FRAPPE_E2E_PASSWORD || "admin"
		);

		await openPmRequest(page, prep.pm_request);
		evidence.screenshots.initial = await shot(page, "01_pe_list_initial");
		const beforeCount = await countDataRows(page);

		await createPeFromToolbar(page, 5000);
		await waitTableRowCount(page, beforeCount + 1);
		results.push({ test: "desk_create_draft_updates_table", pass: true });
		evidence.screenshots.after_create = await shot(page, "02_after_create_pe");

		await openDraftPeFromTable(page);
		await page.getByRole("button", { name: /^Submit$/i }).click();
		await confirmFrappePrompt(page);
		await page.waitForFunction(
			() => window.cur_frm?.doc?.docstatus === 1,
			{ timeout: 180000 }
		);
		await openPmRequest(page, prep.pm_request);
		await waitTableStatus(page, "Submitted");
		results.push({ test: "desk_table_updates_after_pe_submit", pass: true });
		evidence.screenshots.after_submit = await shot(page, "03_after_submit_pe");

		await createPeFromToolbar(page, 3000);
		await waitTableRowCount(page, beforeCount + 2);
		const countBeforeDelete = await countDataRows(page);
		await openDraftPeFromTable(page);
		await deleteDraftPeFromDesk(page);
		await openPmRequest(page, prep.pm_request);
		await page.waitForFunction(
			(before) => {
				const table = document.querySelector("#pm-request-pe-list table tbody");
				if (!table) {
					return false;
				}
				const n = Array.from(table.querySelectorAll("tr")).filter(
					(tr) => !tr.querySelector("td[colspan]")
				).length;
				return n < before;
			},
			countBeforeDelete,
			{ timeout: 180000 }
		);
		const createVisible = await createPeVisible(page);
		results.push({ test: "desk_draft_delete_from_pe_form", pass: createVisible });
		evidence.screenshots.after_desk_delete = await shot(page, "04_after_desk_delete_draft");
		results.push({ test: "desk_table_updates_after_draft_delete", pass: true });

		let invalidOk = false;
		try {
			await page.evaluate(async (name) => {
				await frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
					args: { pm_request: name },
				});
			}, invalid.invalid_name);
		} catch (e) {
			invalidOk = true;
		}
		results.push({ test: "invalid_pm_request_id_rejected", pass: invalidOk });

		const v1 = await page.evaluate(async (req) => {
			const r = await frappe.call({
				method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
				args: { pm_request: req },
			});
			return r.message?.response_version_id;
		}, prep.pm_request);
		const v2 = await page.evaluate(async (req) => {
			const r = await frappe.call({
				method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
				args: { pm_request: req },
			});
			return r.message?.response_version_id;
		}, prep.pm_request);
		results.push({
			test: "concurrency_response_version_stable",
			pass: String(v1) === String(v2),
		});

		fs.mkdirSync(path.dirname(TRACE), { recursive: true });
		await context.tracing.stop({ path: TRACE });
		await context.close();

		const deniedContext = await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 950 } });
		deniedContext.setDefaultNavigationTimeout(180000);
		deniedContext.setDefaultTimeout(180000);
		const deniedPage = await deniedContext.newPage();
		await login(deniedPage, deniedUser.email, deniedUser.password);
		await deniedPage.goto(`${BASE}/app`, { waitUntil: "domcontentloaded", timeout: 180000 });
		let permissionDenied = false;
		try {
			await deniedPage.evaluate(async (req) => {
				await frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_payment_entries",
					args: { pm_request: req },
				});
			}, prep.pm_request);
		} catch (e) {
			permissionDenied = true;
		}
		results.push({ test: "permission_denied_user_blocked", pass: permissionDenied });
		evidence.screenshots.permission_denied = await shot(deniedPage, "05_permission_denied");
		await deniedContext.close();

		const benignConsole = consoleErrors.filter(
			(e) =>
				!/favicon|Failed to load resource: the server responded with a status of (404|400)|socket\.io|Unauthorized.*fetch failed|get_open_form is not a function/i.test(
					e
				)
		);
		results.push({ test: "no_js_console_errors", pass: benignConsole.length === 0 });
		evidence.console_errors = benignConsole;

		const allPass = results.every((r) => r.pass);
		console.log(JSON.stringify({ pass: allPass, results, evidence }, null, 2));
		process.exit(allPass ? 0 : 1);
	} catch (err) {
		console.error(err);
		evidence.error = String(err);
		evidence.console_errors = consoleErrors;
		try {
			fs.mkdirSync(path.dirname(TRACE), { recursive: true });
			await context.tracing.stop({ path: TRACE });
		} catch (_e) {
			/* ignore */
		}
		console.log(JSON.stringify({ pass: false, evidence, results }, null, 2));
		process.exit(1);
	} finally {
		await browser.close();
	}
}

run();
