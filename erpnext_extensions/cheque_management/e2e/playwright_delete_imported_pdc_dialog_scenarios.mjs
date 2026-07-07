/**
 * Delete Imported PDC dialog — Scenario A (safe) vs B (blocked) screenshots.
 * Prep via benchExecute; use shared DB helpers for delete outcomes in sibling COI script.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "delete_imported_pdc_dialog_audit");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";

async function login(page) {
	await page.goto(`${BASE}/login`, { waitUntil: "load", timeout: 180000 });
	const email = page.locator("#login_email");
	if (await email.isVisible().catch(() => false)) {
		await email.fill("Administrator");
		await page.fill("#login_password", "admin");
		await page.click('button[type="submit"]');
		await page.waitForURL(/\/(app|desk)/, { timeout: 180000 });
	}
}

async function openDialog(page, pdcName) {
	await page.waitForFunction(
		() =>
			typeof window.erpnext_extensions?.cheque_opening_import?.open_delete_imported_pdc_dialog ===
			"function",
		{ timeout: 180000 }
	);
	await page.evaluate(async (pdc) => {
		const ns = window.erpnext_extensions.cheque_opening_import;
		await ns.open_delete_imported_pdc_dialog(pdc, window.cur_frm);
	}, pdcName);
	await page.waitForSelector(".modal-dialog .modal-title", { timeout: 60000 });
	await page.waitForTimeout(800);
}

async function dialogUiState(page) {
	return page.evaluate(() => {
		const modal = document.querySelector(".modal-dialog");
		const primary = modal?.querySelector(".btn-primary");
		const reason = modal?.querySelector('[data-fieldname="reason"]');
		const body = modal?.querySelector(".modal-body")?.textContent || "";
		return {
			primaryLabel: (primary?.textContent || "").trim(),
			reasonFieldInDom: !!reason,
			hasBlockers: body.includes("Blockers"),
			hasSafetyAudit: body.includes("Safety audit"),
		};
	});
}

async function main() {
	fs.mkdirSync(SCREEN, { recursive: true });
	const safe = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_safe_delete"
	);
	const blocked = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_blocked_delete"
	);

	const browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ locale: "en-US" });
	await login(page);

	await page.goto(`${BASE}/app/cheque-opening-import/${encodeURIComponent(safe.coi_name)}`, {
		waitUntil: "load",
		timeout: 180000,
	});
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Cheque Opening Import" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
	await page.waitForFunction(
		() =>
			typeof window.erpnext_extensions?.cheque_opening_import?.open_delete_imported_pdc_dialog ===
			"function",
		{ timeout: 120000 }
	);
	await page.waitForTimeout(5000);

	await openDialog(page, safe.pdc_name);
	const stateA = await dialogUiState(page);
	await page.screenshot({ path: path.join(SCREEN, "Scenario_A_safe_delete_dialog.png"), fullPage: true });
	await page.locator(".modal-dialog .btn-secondary, .modal-dialog .btn-default").first().click().catch(() => page.keyboard.press("Escape"));
	await page.waitForTimeout(500);

	await page.goto(`${BASE}/app/cheque-opening-import/${encodeURIComponent(blocked.coi_name)}`, {
		waitUntil: "load",
		timeout: 180000,
	});
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Cheque Opening Import" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(5000);

	await openDialog(page, blocked.pdc_name);
	const stateB = await dialogUiState(page);
	await page.screenshot({
		path: path.join(SCREEN, "Scenario_B_blocked_audit_dialog.png"),
		fullPage: true,
	});
	await page.locator(".modal-dialog .btn-primary").click();
	await page.waitForTimeout(300);
	const missingValuesVisible = await page.evaluate(() => {
		return (document.body.textContent || "").includes("Missing Values Required");
	});

	await browser.close();

	const report = {
		scenarioA: {
			...stateA,
			ok:
				stateA.reasonFieldInDom &&
				stateA.primaryLabel.includes("Confirm") &&
				stateA.hasSafetyAudit,
		},
		scenarioB: {
			...stateB,
			ok:
				!stateB.reasonFieldInDom &&
				stateB.primaryLabel === "Close" &&
				stateB.hasBlockers &&
				!missingValuesVisible,
			missingValuesAfterCloseClick: missingValuesVisible,
		},
		screenshots_dir: SCREEN,
		all_ok:
			stateA.reasonFieldInDom &&
			stateA.primaryLabel.includes("Confirm") &&
			!stateB.reasonFieldInDom &&
			stateB.primaryLabel === "Close" &&
			!missingValuesVisible,
	};
	console.log(JSON.stringify(report, null, 2));
	process.exit(report.all_ok ? 0 : 1);
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
