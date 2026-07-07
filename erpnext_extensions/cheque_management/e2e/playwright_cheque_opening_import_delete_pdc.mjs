/**
 * Cheque Opening Import — Delete Imported PDC E2E (Playwright).
 * DB-first: document existence verified via e2e_playwright_db.mjs.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import {
	benchExecute,
	documentExists,
	waitDocumentAbsent,
} from "../../e2e/e2e_playwright_db.mjs";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "coi_delete_imported_pdc");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const PDC = "Post Dated Cheque";

function pdcExists(pdcName) {
	return documentExists(PDC, pdcName);
}

async function pdcAbsent(pdcName, timeoutMs = 90000) {
	const r = await waitDocumentAbsent(PDC, pdcName, { timeoutMs });
	return r.ok;
}

async function shot(page, name) {
	fs.mkdirSync(SCREEN, { recursive: true });
	const p = path.join(SCREEN, `${name}.png`);
	await page.screenshot({ path: p, fullPage: true });
	return p;
}

async function login(page, user, pass) {
	await page.goto(`${BASE}/login`, { waitUntil: "load", timeout: 180000 });
	const email = page.locator("#login_email");
	const visible = await email.isVisible().catch(() => false);
	if (!visible) {
		await page.goto(`${BASE}/app`, { waitUntil: "domcontentloaded" });
		return;
	}
	await email.fill(user);
	await page.fill("#login_password", pass);
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 180000 });
}

async function openCoi(page, name) {
	await page.goto(`${BASE}/app/cheque-opening-import/${encodeURIComponent(name)}`, {
		waitUntil: "load",
		timeout: 180000,
	});
	await page.waitForFunction(
		() =>
			window.cur_frm?.doc?.doctype === "Cheque Opening Import" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
	await page.waitForTimeout(5000);
	await page.waitForFunction(
		() =>
			typeof window.erpnext_extensions?.cheque_opening_import
				?.open_delete_imported_pdc_dialog === "function",
		{ timeout: 120000 }
	);
}

async function openDeleteDialog(page, pdcName) {
	return page.evaluate(async (pdc) => {
		const ns = window.erpnext_extensions?.cheque_opening_import;
		if (!ns?.open_delete_imported_pdc_dialog) {
			return { ok: false, step: "no_js_namespace" };
		}
		await ns.open_delete_imported_pdc_dialog(pdc, window.cur_frm);
		return { ok: true };
	}, pdcName);
}

async function clickDeleteImportedPdcButton(page) {
	return page.evaluate(() => {
		const findBtn = () => {
			const btns = Array.from(
				document.querySelectorAll(".custom-actions .btn, .page-actions .btn, .btn")
			);
			return btns.find((b) => (b.textContent || "").includes("Delete Imported PDC"));
		};
		let btn = findBtn();
		if (!btn) {
			const actions = Array.from(document.querySelectorAll(".btn")).find(
				(b) => (b.textContent || "").trim() === "Actions"
			);
			if (actions) {
				actions.click();
				btn = findBtn();
			}
		}
		if (!btn) return { ok: false, step: "no_button" };
		btn.click();
		return { ok: true };
	});
}

async function waitForDialog(page, titlePart, timeoutMs = 90000) {
	const deadline = Date.now() + timeoutMs;
	while (Date.now() < deadline) {
		const found = await page.evaluate((part) => {
			const modals = document.querySelectorAll(".modal-dialog");
			for (const m of modals) {
				const h = m.querySelector(".modal-title");
				if (h && (h.textContent || "").includes(part)) return true;
			}
			return false;
		}, titlePart);
		if (found) return true;
		await page.waitForTimeout(300);
	}
	return false;
}

async function fillDialogReasonAndConfirm(page, reason) {
	const modal = page.locator(".modal-dialog").filter({ hasText: "Delete Imported PDC" }).last();
	await modal.waitFor({ state: "visible", timeout: 60000 });
	const textarea = modal.locator('textarea[data-fieldname="reason"], textarea').first();
	if (await textarea.count()) {
		await textarea.fill(reason);
	}
	const primary = modal.locator(".btn-primary").first();
	const label = ((await primary.textContent()) || "").trim();
	if (label.includes("Confirm") && (await primary.isEnabled())) {
		await primary.click();
		return { clicked: true, label };
	}
	return { clicked: false, label, disabled: !label.includes("Confirm") };
}

async function apiPreviewRejected(page, pdcName) {
	return page.evaluate(async (pdc) => {
		try {
			await frappe.call({
				method:
					"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.preview_delete_imported_pdc",
				args: { pdc_name: pdc },
			});
			return { rejected: false };
		} catch (e) {
			return { rejected: true, message: e?.message || String(e) };
		}
	}, pdcName);
}

const results = {};

async function scenarioA(page, prep) {
	await openCoi(page, prep.coi_name);
	await shot(page, "A_coi_open");
	let click = await clickDeleteImportedPdcButton(page);
	if (!click.ok) {
		click = await openDeleteDialog(page, prep.pdc_name);
	}
	if (!click.ok) {
		results.A = { ok: false, step: click.step };
		return;
	}
	await waitForDialog(page, "Delete Imported PDC");
	await shot(page, "A_preview_dialog");
	const dialogStateA = await page.evaluate(() => {
		const modal = document.querySelector(".modal-dialog");
		const primary = modal?.querySelector(".btn-primary");
		const reason = modal?.querySelector('[data-fieldname="reason"]');
		return {
			hasAudit: (modal?.querySelector(".modal-body")?.textContent || "").includes("Safety audit"),
			reasonFieldInDom: !!reason,
			primaryLabel: (primary?.textContent || "").trim(),
		};
	});
	const hasAudit = dialogStateA.hasAudit;
	const confirm = await fillDialogReasonAndConfirm(page, "E2E safe delete reason");
	await page.waitForTimeout(2000);
	const absentOk = await pdcAbsent(prep.pdc_name);
	const existsAfter = !absentOk;
	await openCoi(page, prep.coi_name);
	const cleared = await page.evaluate((pdc) => {
		const items = window.cur_frm?.doc?.items || [];
		return !items.some((r) => r.imported_pdc === pdc || r.post_dated_cheque === pdc);
	}, prep.pdc_name);
	results.A = {
		ok:
			hasAudit &&
			dialogStateA.reasonFieldInDom &&
			dialogStateA.primaryLabel.includes("Confirm") &&
			confirm.clicked &&
			!existsAfter &&
			cleared,
		hasAudit,
		dialogStateA,
		confirm,
		existsAfter,
		cleared,
	};
	await shot(page, "A_after_delete");
}

async function scenarioB(page, prep) {
	await openCoi(page, prep.coi_name);
	let click = await clickDeleteImportedPdcButton(page);
	if (!click.ok) {
		await openDeleteDialog(page, prep.pdc_name);
	}
	await waitForDialog(page, "Delete Imported PDC");
	await shot(page, "B_blocked_dialog");
	const state = await page.evaluate(() => {
		const modal = document.querySelector(".modal-dialog");
		const text = modal?.querySelector(".modal-body")?.textContent || "";
		const primary = modal?.querySelector(".btn-primary");
		const reason = modal?.querySelector('[data-fieldname="reason"]');
		return {
			hasBlockers: text.includes("Blockers") || text.includes("Journal Reference"),
			primaryLabel: (primary?.textContent || "").trim(),
			reasonFieldInDom: !!reason,
		};
	});
	if (state.primaryLabel === "Close") {
		await page.locator(".modal-dialog .btn-primary").click();
	}
	const confirmDisabled =
		state.primaryLabel === "Close" && !state.primaryLabel.includes("Confirm");
	results.B = {
		ok: state.hasBlockers && confirmDisabled && !state.reasonFieldInDom,
		...state,
	};
}

async function scenarioC(prep, nonAdmin) {
	const mayDelete = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_may_delete_as_user",
		{ user_email: nonAdmin.email }
	);
	const api = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_preview_as_user",
		{ pdc_name: prep.pdc_name, user_email: nonAdmin.email }
	);
	results.C = {
		ok: mayDelete.may_delete === false && api.rejected === true,
		mayDelete,
		api,
	};
}

async function scenarioD(prep) {
	try {
		if (pdcExists(prep.pdc_name)) {
			results.D = { ok: false, step: "pdc_still_exists_after_ui_delete" };
			return;
		}
		const re = benchExecute(
			"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_reimport_row",
			{ cheque_no: prep.cheque_no, company: prep.company }
		);
		results.D = {
			ok: !!re.pdc_name,
			new_pdc: re.pdc_name,
		};
	} catch (e) {
		results.D = { ok: false, error: String(e) };
	}
}

async function main() {
	const safe = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_safe_delete"
	);
	const blocked = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_blocked_delete"
	);
	const nonAdmin = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_non_admin_user"
	);
	const safeForC = benchExecute(
		"erpnext_extensions.cheque_management.e2e.coi_delete_imported_pdc_prep.e2e_prep_safe_delete"
	);

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US" });
	const page = await context.newPage();

	try {
		await login(page, "Administrator", "admin");
		await scenarioA(page, safe);
		await scenarioB(page, blocked);
		await scenarioC(safeForC, nonAdmin);
		await scenarioD(safe);
	} finally {
		await browser.close();
	}

	const all_ok = Object.values(results).every((r) => r && r.ok);
	const report = { all_ok, results, screenshots_dir: SCREEN };
	console.log(JSON.stringify(report, null, 2));
	process.exit(all_ok ? 0 : 1);
}

main().catch((e) => {
	console.error(e);
	process.exit(1);
});
