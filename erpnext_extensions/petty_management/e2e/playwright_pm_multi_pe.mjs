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

		const multi = bench(
			"erpnext_extensions.petty_management.e2e.pm_multi_pe_prep.prepare_two_submitted_partial"
		);

		const results = [];
	const evidence = { screenshots: {}, partial, full, draftCase, multi, trace: null };

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

		await page.goto(`${BASE}/app/pm-request/${encodeURIComponent(multi.pm_request)}`, {
			waitUntil: "domcontentloaded",
		});
		await waitPmRequestForm(page);
		evidence.screenshots.multi_pe_form = await shot(page, "05_multi_pe_form");
		const flagsMulti = await actionFlags(page);
		results.push({
			test: "multi_pe_reject_hidden_in_flags",
			pass: flagsMulti.can_reject === false && flagsMulti.submitted_payment_entry_count >= 2,
			flags: flagsMulti,
		});
		results.push({
			test: "multi_pe_view_payment_entries_flag",
			pass: Boolean(flagsMulti.can_view_payment_entries),
		});

		const menuInfo = await page.evaluate(async () => {
			await new Promise((r) => setTimeout(r, 2000));
			const group = document.querySelector(".actions-btn-group");
			if (!group) {
				return { ok: false, items: [], reason: "no_actions_group" };
			}
			const btn = group.querySelector("button") || group.querySelector(".btn");
			btn?.click();
			await new Promise((r) => setTimeout(r, 400));
			const items = Array.from(group.querySelectorAll(".dropdown-item")).map((el) =>
				(el.textContent || "").trim()
			);
			return { ok: true, items };
		});
		const menuText = (menuInfo.items || []).join("\n");
		results.push({
			test: "actions_menu_no_pm_reject",
			pass: menuInfo.ok && !/PM Reject/i.test(menuText),
			evidence: menuInfo,
		});
		results.push({
			test: "actions_menu_has_view_payment_entries",
			pass: menuInfo.ok && /View Payment Entries/i.test(menuText),
		});
		if (menuInfo.ok) {
			const routed = await page.evaluate((args) => {
				frappe.route_options = args.filters || { reference_no: args.pm_request };
				frappe.set_route("List", "Payment Entry");
				return frappe.get_route();
			}, { filters: flagsMulti.payment_entry_list_filters, pm_request: multi.pm_request });
			await page.waitForTimeout(2500);
			evidence.screenshots.pe_list_view = await shot(page, "06_payment_entry_list");
			const listBody = await page.locator("body").innerText();
			results.push({
				test: "view_payment_entries_route",
				pass: Array.isArray(routed) && routed[0] === "List",
				evidence: { routed },
			});
			for (const pe of multi.payment_entries || []) {
				results.push({
					test: `pe_list_shows_${pe}`,
					pass: listBody.includes(pe),
				});
			}
		} else {
			results.push({
				test: "desk_actions_menu_skipped",
				pass: true,
				evidence: menuInfo,
			});
		}

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
