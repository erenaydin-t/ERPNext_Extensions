/**
 * PM Request multi-PE + Close E2E (architecture v2.1).
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pm_multi_pe");
const TRACE_DIR = path.join(__dirname, "trace", "pm_multi_pe");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function bench(method) {
	const out = execSync(`cd ${BENCH} && bench --site development.localhost execute "${method}"`, {
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

async function waitPmRequestForm(page) {
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "PM Request" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
}

async function actionFlags(page) {
	return page.evaluate(async () => {
		const r = await frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_action_flags",
			args: { pm_request: window.cur_frm.doc.name },
		});
		return r.message || {};
	});
}

async function run() {
	const partial = bench(
		"erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_partial_funded_for_close_ui"
	);
	const full = bench(
		"erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_fully_paid_for_close_ui"
	);
	const draftCase = bench(
		"erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_draft_pe_blocks_close"
	);

	const results = [];
	const evidence = { screenshots: {}, partial, full, draftCase, trace: null };

	fs.mkdirSync(TRACE_DIR, { recursive: true });
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 950 } });
	await context.tracing.start({ screenshots: true, snapshots: true, sources: true });
	const page = await context.newPage();
	page.setDefaultTimeout(180000);

	try {
		await login(page);

		// Partial funded: Close visible, Create PE visible, reason required path
		await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(partial.pm_request)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitPmRequestForm(page);
		evidence.screenshots.before_close_partial = await shot(page, "01_partial_before_close");
		const flagsPartial = await actionFlags(page);
		results.push({
			test: "partial_close_visible",
			pass: Boolean(flagsPartial.can_close_pm_request),
			flags: flagsPartial,
		});
		results.push({
			test: "partial_create_pe_visible",
			pass: Boolean(flagsPartial.can_create_payment_entry),
		});
		const duplicateActions = await page.evaluate(() => {
			const innerActions = Array.from(document.querySelectorAll(".inner-group-button .dropdown-toggle"))
				.filter((el) => (el.textContent || "").trim() === "Actions").length;
			const std = Array.from(document.querySelectorAll(".actions-btn-group")).filter(
				(el) => el.offsetParent !== null
			).length;
			return { innerActions, std };
		});
		results.push({
			test: "single_actions_menu_no_duplicate_toolbar_group",
			pass: duplicateActions.innerActions === 0 && duplicateActions.std >= 1,
			evidence: duplicateActions,
		});

		// Fully paid: Close still visible
		await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(full.pm_request)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitPmRequestForm(page);
		evidence.screenshots.fully_paid = await shot(page, "02_fully_paid_form");
		const flagsFull = await actionFlags(page);
		results.push({
			test: "fully_paid_close_visible",
			pass: Boolean(flagsFull.can_close_pm_request),
			flags: flagsFull,
		});

		// Draft PE blocks close
		await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(draftCase.pm_request)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitPmRequestForm(page);
		evidence.screenshots.draft_pe = await shot(page, "03_draft_pe_form");
		const flagsDraft = await actionFlags(page);
		results.push({
			test: "draft_pe_blocks_close",
			pass: flagsDraft.can_close_pm_request === false && /draft payment entries exist/i.test(
				flagsDraft.close_block_reason || ""
			),
			flags: flagsDraft,
		});
		results.push({
			test: "draft_pe_hides_create_pe",
			pass: flagsDraft.can_create_payment_entry === false,
			flags: flagsDraft,
		});

		await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(partial.pm_request)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitPmRequestForm(page);
		const peListVisible = await page.locator("#pm-request-pe-list table").count();
		results.push({
			test: "payment_entry_list_visible",
			pass: peListVisible > 0,
		});
		evidence.screenshots.pe_list = await shot(page, "04_pe_list");

		const tracePath = path.join(TRACE_DIR, "pm_multi_pe_trace.zip");
		await context.tracing.stop({ path: tracePath });
		evidence.trace = tracePath;

		const allPass = results.every((r) => r.pass);
		console.log(JSON.stringify({ pass: allPass, results, evidence }, null, 2));
		process.exit(allPass ? 0 : 1);
	} catch (err) {
		try {
			const tracePath = path.join(TRACE_DIR, "pm_multi_pe_trace_failure.zip");
			await context.tracing.stop({ path: tracePath });
			evidence.trace = tracePath;
		} catch (_) {
			/* ignore */
		}
		console.error(err);
		console.log(JSON.stringify({ pass: false, error: String(err), evidence }, null, 2));
		process.exit(1);
	} finally {
		await browser.close();
	}
}

run();
