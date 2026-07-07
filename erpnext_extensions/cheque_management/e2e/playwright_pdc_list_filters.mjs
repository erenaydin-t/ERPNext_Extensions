/**
 * Real browser E2E (Playwright). Run from bench root:
 *
 *   bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.seed
 *   bench build --app erpnext_extensions && bench --site development.localhost clear-cache
 *   PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright FRAPPE_E2E_PASSWORD=admin \
 *     node apps/erpnext_extensions/erpnext_extensions/cheque_management/e2e/playwright_pdc_list_filters.mjs
 *
 * UI-primary: list filter client behavior; seed via bench execute only.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN_DIR = path.join(__dirname, "screenshots");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const USER = process.env.FRAPPE_E2E_USER || "Administrator";
const PASS = process.env.FRAPPE_E2E_PASSWORD || "admin";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

const results = [];

function log(test, ok, detail = {}) {
	results.push({ test, ok, detail });
	console.log(JSON.stringify({ test, ok, detail }));
}

async function login(page) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", USER);
	await page.fill("#login_password", PASS);
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function waitForPdcList(page) {
	await page.goto(`${BASE}/desk/post-dated-cheque`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.waitForFunction(
		() => {
			const lv = window.cur_list;
			return (
				lv &&
				lv.doctype === "Post Dated Cheque" &&
				typeof lv.get_filters_for_args === "function" &&
				lv.filter_area &&
				!lv.loading &&
				Array.isArray(lv.data)
			);
		},
		{ timeout: 180000 }
	);
	await page.waitForTimeout(1500);
}

function getListViewHandle() {
	return `(() => {
		const lv = window.cur_list;
		if (!lv || lv.doctype !== "Post Dated Cheque" || typeof lv.get_filters_for_args !== "function") {
			throw new Error("Post Dated Cheque ListView not ready");
		}
		return lv;
	})()`;
}

function lvScript(fnBody) {
	return `(() => {
		const lv = ${getListViewHandle()};
		return (${fnBody})(lv);
	})()`;
}

async function filterXActive(page) {
	return page.evaluate(lvScript(`(lv) => {
		const fl = lv.filter_area?.filter_list;
		const applied = (fl?.get_filters?.() || []).length;
		const btn = document.querySelector(".filter-button");
		return applied > 0 || btn?.classList.contains("btn-primary-light");
	}`));
}

async function popoverHasEmptyIdEquals(page) {
	return page.evaluate(lvScript(`(lv) => {
		const fl = lv.filter_area?.filter_list;
		if (!fl?.filters) return false;
		return fl.filters.some((f) => {
			if (!f.field || f.field.df?.fieldname !== "name") return false;
			if ((f.get_condition?.() || "").toLowerCase() !== "=") return false;
			const v = f.get_selected_value?.();
			return v === "" || v == null;
		});
	}`));
}

async function listDebug(page) {
	return page.evaluate(lvScript(`(lv) => {
		const dbg = window.erpnext_extensions?.cheque_management?.pdc_list_view?.get_filter_debug?.(lv);
		return {
			data_length: lv.data?.length ?? 0,
			get_args: lv.get_filters_for_args?.() || [],
			filter_area_get: lv.filter_area?.get?.() || [],
			dbg,
		};
	}`));
}

async function applyIdEqualsFilter(page, value) {
	await page.evaluate(async (val) => {
		const lv = window.cur_list;
		erpnext_extensions.cheque_management.pdc_list_view.reset_reconcile_state(lv);
		lv._pdc_filter_reconcile_state.user_interacted = true;
		if (window.location.search) {
			window.history.replaceState({}, "", window.location.pathname);
		}
		frappe.route_options = null;
		lv.filter_area.filter_list.clear_filters();
		await lv.filter_area.clear(false);
		if (lv.page.fields_dict.name) {
			await lv.page.fields_dict.name.set_value("");
		}
		await lv.filter_area.filter_list.add_filters([["Post Dated Cheque", "name", "=", val]]);
		lv.filter_area.filter_list.update_filters?.();
		lv.filter_area.filter_list.update_filter_button?.();
		lv.save_view_user_settings?.({ filters: lv.filter_area.get() });
		await lv.filter_area.refresh_list_view();
		await new Promise((r) => setTimeout(r, 2000));
	}, value);
	await page.waitForFunction(
		() => {
			const lv = window.cur_list;
			return lv && lv.doctype === "Post Dated Cheque" && !lv.loading;
		},
		{ timeout: 120000 }
	);
}

async function screenshot(page, name) {
	fs.mkdirSync(SCREEN_DIR, { recursive: true });
	const file = path.join(SCREEN_DIR, `${name}.png`);
	await page.screenshot({ path: file, fullPage: true });
	return file;
}

async function run() {
	fs.mkdirSync(SCREEN_DIR, { recursive: true });
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({
		viewport: { width: 1400, height: 900 },
		locale: "en-US",
	});
	const page = await context.newPage();
	page.setDefaultTimeout(180000);

	try {
		const seedOut = execSync(
			`cd ${BENCH} && bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.seed`,
			{ encoding: "utf8" }
		);
		const seedLine = seedOut.trim().split("\n").filter(Boolean).pop();
		const seeded = JSON.parse(seedLine);
		log(
			"A0_seed_dirty_before_list",
			(seeded.filters || []).some((f) => f[1] === "name" && f[3] === ""),
			{ seeded }
		);
		await login(page);
		await waitForPdcList(page);
		const beforeA = await listDebug(page);
		const shotA = await screenshot(page, "A_after_load");
		log(
			"A_empty_id_removed_on_load",
			beforeA.data_length > 0 &&
				!(await filterXActive(page)) &&
				!(await popoverHasEmptyIdEquals(page)) &&
				!beforeA.get_args.some((f) => f[1] === "name" && f[2] === "=" && (f[3] === "" || f[3] == null)),
			{ beforeA, screenshot: shotA }
		);

		await page.reload({ waitUntil: "domcontentloaded" });
		await waitForPdcList(page);
		const dbgE = await listDebug(page);
		const shotE = await screenshot(page, "E_reload_clean");
		log(
			"E_reload_no_empty_id",
			dbgE.data_length > 0 && !(await filterXActive(page)) && !(await popoverHasEmptyIdEquals(page)),
			{ dbgE, screenshot: shotE }
		);

		const sample = await page.evaluate(async () => {
			const rows = await frappe.db.get_list("Post Dated Cheque", {
				fields: ["name"],
				limit: 1,
				order_by: "modified desc",
			});
			return rows[0]?.name;
		});
		if (sample) {
			await applyIdEqualsFilter(page, sample);
			const dbgB = await listDebug(page);
			const shotB = await screenshot(page, "B_valid_id_filter");
			log(
				"B_valid_id_filter_kept",
				dbgB.data_length === 1 &&
					(await filterXActive(page)) &&
					dbgB.get_args.some((f) => f[1] === "name" && f[3] === sample),
				{ dbgB, sample, screenshot: shotB }
			);
		} else {
			log("B_valid_id_filter_kept", false, { error: "no sample PDC" });
		}

		await applyIdEqualsFilter(page, "PDC-DOES-NOT-EXIST");
		const dbgC = await listDebug(page);
		const shotC = await screenshot(page, "C_intentional_empty");
		log(
			"C_intentional_empty_kept",
			dbgC.data_length === 0 && (await filterXActive(page)) && dbgC.get_args.some((f) => f[3] === "PDC-DOES-NOT-EXIST"),
			{ dbgC, screenshot: shotC }
		);

		await page.evaluate(async () => {
			const lv = window.cur_list;
			erpnext_extensions.cheque_management.pdc_list_view.reset_reconcile_state(lv);
			await lv.filter_area.clear(false);
			if (lv.page.fields_dict.name) {
				await lv.page.fields_dict.name.set_value("");
			}
			lv.filter_area.filter_list.clear_filters();
			await lv.filter_area.refresh_list_view();
		});
		await waitForPdcList(page);
		await page.evaluate(async () => {
			const lv = window.cur_list;
			erpnext_extensions.cheque_management.pdc_list_view.reset_reconcile_state(lv);
			lv._pdc_filter_reconcile_state.user_interacted = true;
			await lv.filter_area.filter_list.add_filters([["Post Dated Cheque", "name", "=", ""]]);
			lv.filter_area.filter_list.apply();
			await new Promise((r) => setTimeout(r, 2500));
			await lv.refresh();
		});
		const dbgD = await listDebug(page);
		const shotD = await screenshot(page, "D_empty_apply_blocked");
		log(
			"D_empty_apply_safe",
			dbgD.data_length > 0 && !(await popoverHasEmptyIdEquals(page)) && !dbgD.get_args.some((f) => f[1] === "name" && f[3] === ""),
			{ dbgD, screenshot: shotD }
		);
	} finally {
		await browser.close();
		execSync(
			`cd ${BENCH} && bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.restore_empty`,
			{ stdio: "inherit" }
		);
	}

	const main = results.filter((r) => !r.test.startsWith("A0_"));
	const all_ok = main.every((r) => r.ok);
	console.log(JSON.stringify({ all_ok, results }, null, 2));
	process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
