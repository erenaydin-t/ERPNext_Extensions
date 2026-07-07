/**
 * Capture screenshots proving Delete Imported PDC button placement (COI + PDC forms).
 * DB: prep documents must exist before UI capture.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { benchExecute, getDocumentState } from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "delete_imported_pdc_button_proof");
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

async function main() {
	fs.mkdirSync(SCREEN, { recursive: true });
	const prep = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_safe_delete"
	);
	const browser = await chromium.launch({ headless: true });
	const page = await browser.newPage({ locale: "en-US" });
	await login(page);

	await page.goto(`${BASE}/app/cheque-opening-import/${encodeURIComponent(prep.coi_name)}`, {
		waitUntil: "load",
		timeout: 180000,
	});
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Cheque Opening Import" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(5000);
	await page.screenshot({ path: path.join(SCREEN, "01_coi_form_top_actions.png"), fullPage: true });

	await page.goto(`${BASE}/app/post-dated-cheque/${encodeURIComponent(prep.pdc_name)}`, {
		waitUntil: "load",
		timeout: 180000,
	});
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Post Dated Cheque" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(5000);
	const pdcBtn = await page.evaluate(() => {
		const btns = Array.from(document.querySelectorAll(".custom-actions .btn, .page-actions .btn"));
		return btns.some((b) => (b.textContent || "").includes("Delete Imported PDC"));
	});
	const coiDb = getDocumentState("Cheque Opening Import", prep.coi_name, ["name", "docstatus"]);
	const pdcDb = getDocumentState("Post Dated Cheque", prep.pdc_name, ["name", "workflow_state", "docstatus"]);
	await page.screenshot({ path: path.join(SCREEN, "02_pdc_form_custom_delete_button.png"), fullPage: true });

	await browser.close();
	const all_ok =
		coiDb.exists &&
		pdcDb.exists &&
		pdcBtn;
	console.log(
		JSON.stringify(
			{
				all_ok,
				screenshots_dir: SCREEN,
				coi_name: prep.coi_name,
				pdc_name: prep.pdc_name,
				pdc_has_delete_imported_pdc_button: pdcBtn,
				db: { coi: coiDb, pdc: pdcDb },
			},
			null,
			2
		)
	);
	process.exit(all_ok ? 0 : 1);
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
