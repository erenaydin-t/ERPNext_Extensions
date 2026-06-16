/**
 * Playwright browser E2E for PDC list empty ID filter bug.
 *
 * Usage (from frappe-bench root):
 *   node apps/erpnext_extensions/erpnext_extensions/cheque_management/tests/pdc_list_filter_browser_e2e.mjs
 *
 * Env:
 *   PDC_E2E_BASE_URL (default http://development.localhost:8000)
 *   PDC_E2E_USER (default Administrator)
 *   PDC_E2E_PASSWORD (required)
 */
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const OUT_DIR = path.join(__dirname, "browser_e2e_output");
const BASE_URL = process.env.PDC_E2E_BASE_URL || "http://development.localhost:8000";
const USER = process.env.PDC_E2E_USER || "Administrator";
const PASSWORD = process.env.PDC_E2E_PASSWORD || process.env.FRAPPE_ADMIN_PASSWORD || "admin";

const PDC_LIST = `${BASE_URL}/app/post-dated-cheque`;

function ensureOut() {
	fs.mkdirSync(OUT_DIR, { recursive: true });
}

async function login(page) {
	await page.goto(`${BASE_URL}/login`, { waitUntil: "networkidle", timeout: 120000 });
	const email = page.locator('input[data-fieldname="email"], #login_email').first();
	const pwd = page.locator('input[data-fieldname="password"], #login_password').first();
	await email.fill(USER);
	await pwd.fill(PASSWORD);
	await page.locator('button.btn-login, button[type="submit"]').first().click();
	await page.waitForFunction(
		() => window.frappe?.session?.user && window.frappe.session.user !== "Guest",
		{ timeout: 120000 }
	);
}

async function waitForListView(page) {
	await page.waitForFunction(
		() => {
			if (window.cur_list && window.cur_list.doctype === "Post Dated Cheque") {
				return true;
			}
			if (window.frappe?.set_route) {
				const r = window.frappe.get_route?.() || [];
				if (r[0] === "List" && r[1] === "Post Dated Cheque") {
					return !!window.cur_list;
				}
			}
			return false;
		},
		{ timeout: 180000 }
	);
	await page.waitForFunction(
		() =>
			window.cur_list &&
			window.cur_list.doctype === "Post Dated Cheque" &&
			Array.isArray(window.cur_list.data) &&
			window.cur_list.loading !== true,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(2000);
}

async function evalDebug(page) {
	return page.evaluate(() => {
		const lv = window.cur_list;
		const dbg = window.erpnext_extensions?.cheque_management?.pdc_list_view?.get_filter_debug?.(lv);
		const args = lv?.get_filters_for_args?.() || [];
		const combined = lv?.filter_area?.get?.() || [];
		const xVisible = document.querySelector(".filter-x-button")?.offsetParent !== null;
		const filterBtn = document.querySelector(".filter-button");
		const filterActive = filterBtn?.classList.contains("btn-primary-light");
		return { dbg, args, combined, xVisible, filterActive, rows: lv?.data?.length ?? 0 };
	});
}

async function openFilterPopover(page) {
	await page.locator(".filter-button").first().click();
	await page.waitForSelector(".filter-popover, .filter-area .filter-edit-area", {
		timeout: 15000,
	});
}

async function popoverHasEmptyIdEquals(page) {
	return page.evaluate(() => {
		const boxes = document.querySelectorAll(".filter-popover .filter-box, .filter-area .filter-box");
		for (const box of boxes) {
			const cond = box.querySelector(".condition")?.value || "";
			const fieldLabel = box.querySelector(".fieldname .awesomplete input")?.value || "";
			const valInput = box.querySelector(".form-group input.input-with-feedback");
			const val = valInput?.value ?? "";
			const isId =
				fieldLabel === "ID" ||
				fieldLabel === "name" ||
				(fieldLabel && fieldLabel.toLowerCase().includes("id"));
			if (isId && (cond === "=" || cond === "Equals") && String(val).trim() === "") {
				return true;
			}
		}
		return false;
	});
}

async function applyFiltersInPopover(page) {
	const btn = page.locator(".filter-popover .apply-filters, .filter-area .apply-filters").first();
	if (await btn.isVisible()) {
		await btn.click();
	} else {
		await page.keyboard.press("Escape");
	}
	await waitForListView(page);
}

const results = [];

function record(name, ok, detail) {
	results.push({ test: name, ok, detail });
	console.log(`${ok ? "PASS" : "FAIL"} ${name}`, detail);
}

async function main() {
	ensureOut();
	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ viewport: { width: 1400, height: 900 } });
	const page = await context.newPage();

	try {
		await login(page);
		console.log("Logged in to", BASE_URL);

		// Test A — dirty saved filter cleaned on load
		await page.goto(`${BASE_URL}/desk`, { waitUntil: "networkidle", timeout: 120000 });
		await page.waitForFunction(() => window.frappe?.boot?.sitename, { timeout: 120000 });
		await page.evaluate(
			() =>
				new Promise((resolve) => {
					frappe.ready(() => {
						frappe.set_route("List", "Post Dated Cheque");
						setTimeout(resolve, 3000);
					});
				})
		);
		await waitForListView(page);
		const debugA = await evalDebug(page);
		await page.screenshot({ path: path.join(OUT_DIR, "A_after_load.png"), fullPage: true });
		const badNameFilter = (f) =>
			f[1] === "name" && f[2] === "=" && (f[3] === "" || f[3] === null || f[3] === undefined);
		record(
			"A_rows_visible",
			debugA.rows > 0,
			{ rows: debugA.rows, combined: debugA.combined }
		);
		record(
			"A_no_name_equals_empty_in_args",
			!debugA.args.some(badNameFilter),
			{ args: debugA.args }
		);
		record(
			"A_filter_button_not_active",
			!debugA.filterActive,
			{ filterActive: debugA.filterActive }
		);
		await openFilterPopover(page);
		const emptyIdA = await popoverHasEmptyIdEquals(page);
		await page.screenshot({ path: path.join(OUT_DIR, "A_filter_popover.png"), fullPage: true });
		record("A_no_empty_id_row_in_popover", !emptyIdA, { emptyIdA });
		await page.keyboard.press("Escape");

		// Test B — valid ID filter via UI
		const sampleName = await page.evaluate(async () => {
			const rows = await frappe.db.get_list("Post Dated Cheque", {
				fields: ["name"],
				limit: 1,
				order_by: "modified desc",
			});
			return rows[0]?.name;
		});
		if (!sampleName) {
			record("B_valid_id_filter", false, { error: "no PDC in DB" });
		} else {
			await page.locator(".filter-x-button").click({ force: true }).catch(() => {});
			await waitForListView(page);
			await openFilterPopover(page);
			await page.locator(".filter-popover .add-filter, .filter-area .add-filter").first().click();
			await page.waitForTimeout(500);
			// Set field to ID / name via first filter row
			await page.evaluate((pdcName) => {
				const fl = cur_list.filter_area.filter_list;
				return fl.add_filter("Post Dated Cheque", "name", "=", pdcName).then(() => fl.apply());
			}, sampleName);
			await waitForListView(page);
			const debugB = await evalDebug(page);
			await page.screenshot({ path: path.join(OUT_DIR, "B_valid_id_filter.png"), fullPage: true });
			record(
				"B_filter_preserved",
				debugB.args.some((f) => f[1] === "name" && f[3] === sampleName),
				{ args: debugB.args, sampleName }
			);
			record("B_rows_match", debugB.rows >= 1 && debugB.rows <= 5, { rows: debugB.rows });
			record("B_filter_active", debugB.filterActive, { filterActive: debugB.filterActive });
		}

		// Test C — intentional empty result
		await page.locator(".filter-x-button").click({ force: true }).catch(() => {});
		await waitForListView(page);
		await page.evaluate(() => {
			const fl = cur_list.filter_area.filter_list;
			return fl.add_filter("Post Dated Cheque", "name", "=", "PDC-DOES-NOT-EXIST").then(() =>
				fl.apply()
			);
		});
		await waitForListView(page);
		const debugC = await evalDebug(page);
		await page.screenshot({ path: path.join(OUT_DIR, "C_intentional_empty.png"), fullPage: true });
		record("C_list_empty", debugC.rows === 0, { rows: debugC.rows });
		record("C_filter_still_active", debugC.filterActive, { filterActive: debugC.filterActive });
		record(
			"C_filter_preserved",
			debugC.args.some((f) => f[1] === "name" && f[3] === "PDC-DOES-NOT-EXIST"),
			{ args: debugC.args }
		);

		// Test D — apply empty equals should not empty list permanently
		await page.locator(".filter-x-button").click({ force: true }).catch(() => {});
		await waitForListView(page);
		await page.evaluate(() => {
			const fl = cur_list.filter_area.filter_list;
			return fl.add_filter("Post Dated Cheque", "name", "=", "").then(() => fl.apply());
		});
		await waitForListView(page);
		const debugD = await evalDebug(page);
		await page.screenshot({ path: path.join(OUT_DIR, "D_empty_equals_apply.png"), fullPage: true });
		record(
			"D_no_empty_name_in_args_after_apply",
			!debugD.args.some(badNameFilter),
			{ args: debugD.args, rows: debugD.rows }
		);
		record("D_rows_visible_after_empty_apply", debugD.rows > 0, { rows: debugD.rows });

		// Test E — reload persistence
		await page.reload({ waitUntil: "networkidle" });
		await waitForListView(page);
		const debugE = await evalDebug(page);
		await page.screenshot({ path: path.join(OUT_DIR, "E_after_reload.png"), fullPage: true });
		record("E_rows_after_reload", debugE.rows > 0, { rows: debugE.rows });
		record(
			"E_no_empty_name_filter",
			!debugE.args.some(badNameFilter),
			{ args: debugE.args }
		);
		record("E_filter_inactive", !debugE.filterActive, { filterActive: debugE.filterActive });

		const allOk = results.every((r) => r.ok);
		const report = { allOk, results, outDir: OUT_DIR, baseUrl: BASE_URL };
		fs.writeFileSync(path.join(OUT_DIR, "report.json"), JSON.stringify(report, null, 2));
		console.log("\n=== SUMMARY ===");
		console.table(results);
		if (!allOk) {
			process.exit(1);
		}
	} finally {
		await browser.close();
	}
}

main().catch((err) => {
	console.error(err);
	process.exit(1);
});
