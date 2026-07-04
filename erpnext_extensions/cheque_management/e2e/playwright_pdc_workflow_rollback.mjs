/**
 * Post Dated Cheque workflow rollback E2E (Playwright).
 *
 * Scenarios A–K per rollback test matrix.
 */
import { chromium } from "/tmp/e2e-npm/node_modules/playwright/index.mjs";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";
import { execSync } from "child_process";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SCREEN = path.join(__dirname, "screenshots", "pdc_workflow_rollback");
const BASE = process.env.FRAPPE_E2E_BASE_URL || "http://development.localhost:8000";
const BENCH = process.env.FRAPPE_BENCH_ROOT || "/workspace/development/frappe-bench";

function benchExecute(method, kwargs = null) {
	let cmd = `cd ${BENCH} && bench --site development.localhost execute "${method}"`;
	if (kwargs) {
		cmd += ` --kwargs '${JSON.stringify(kwargs).replace(/'/g, "'\\''")}'`;
	}
	const out = execSync(cmd, { encoding: "utf8" });
	return JSON.parse(out.trim().split("\n").filter(Boolean).pop());
}

function sqlVerify(pdcName) {
	return benchExecute(
		"erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_sql_verify_pdc",
		{ pdc_name: pdcName }
	);
}

async function shot(page, name) {
	fs.mkdirSync(SCREEN, { recursive: true });
	const p = path.join(SCREEN, `${name}.png`);
	await page.screenshot({ path: p, fullPage: true });
	return p;
}

async function login(page, user, pass) {
	await page.goto(`${BASE}/login`, { waitUntil: "domcontentloaded", timeout: 120000 });
	await page.fill("#login_email", user);
	await page.fill("#login_password", pass);
	await page.click('button[type="submit"]');
	await page.waitForURL(/\/(app|desk)/, { timeout: 120000 });
}

async function openPdc(page, name) {
	await page.goto(`${BASE}/desk/post-dated-cheque/${encodeURIComponent(name)}`, {
		waitUntil: "domcontentloaded",
	});
	await page.waitForFunction(
		() => window.cur_frm?.doc?.doctype === "Post Dated Cheque" && !window.cur_frm.is_loading,
		{ timeout: 180000 }
	);
}

const FIND_ROLLBACK_BTN = `() => Array.from(document.querySelectorAll(".custom-actions .btn, .page-actions .btn")).find((b) => (b.textContent || "").trim() === "Rollback Workflow State")`;

async function openRollbackDialog(page) {
	return page.evaluate(async (findBtnSrc) => {
		const findBtn = eval(findBtnSrc);
		const btn = findBtn();
		if (!btn) return { ok: false, step: "no_button" };
		btn.click();
		await new Promise((r) => setTimeout(r, 700));
		const dialog =
			document.querySelector(".modal.show .modal-dialog") ||
			Array.from(document.querySelectorAll(".modal-dialog")).find((el) =>
				el.closest(".modal")?.classList.contains("show")
			);
		if (!dialog) return { ok: false, step: "no_dialog" };
		const title = (dialog.querySelector(".modal-title")?.textContent || "").trim();
		if (title !== "Rollback Workflow State") return { ok: false, step: "bad_title", title };
		return { ok: true };
	}, FIND_ROLLBACK_BTN);
}

async function rollbackViaUi(page, targetState, reason, { confirm = true } = {}) {
	const out = await page.evaluate(
		async ({ findBtnSrc, targetState, reason, confirm }) => {
			const findBtn = eval(findBtnSrc);
			const btn = findBtn();
			if (!btn) return { ok: false, step: "no_button" };
			btn.click();
			await new Promise((r) => setTimeout(r, 700));
			const dialog =
				document.querySelector(".modal.show .modal-dialog") ||
				Array.from(document.querySelectorAll(".modal-dialog")).find((el) =>
					el.closest(".modal")?.classList.contains("show")
				);
			if (!dialog) return { ok: false, step: "no_dialog" };
			const sel = dialog.querySelector('select[data-fieldname="target_state"]');
			if (sel) {
				sel.value = targetState;
				sel.dispatchEvent(new Event("change", { bubbles: true }));
			}
			await new Promise((r) => setTimeout(r, 1200));
			const ta = dialog.querySelector('textarea[data-fieldname="rollback_reason"]');
			if (ta) {
				ta.value = reason;
				ta.dispatchEvent(new Event("input", { bubbles: true }));
			}
			const preview = (dialog.querySelector('[data-fieldname="preview_html"]')?.innerHTML || "").trim();
			if (!confirm) {
				dialog.querySelector(".btn-modal-close, .close")?.click();
				return { ok: true, preview, confirmed: false };
			}
			dialog.querySelector(".btn-modal-primary")?.click();
			await new Promise((r) => setTimeout(r, 3500));
			await cur_frm.reload_doc();
			return {
				ok: true,
				preview,
				confirmed: true,
				workflow_state: cur_frm.doc.workflow_state,
				cheque_status: cur_frm.doc.cheque_status,
				docstatus: cur_frm.doc.docstatus,
			};
		},
		{ findBtnSrc: FIND_ROLLBACK_BTN, targetState, reason, confirm }
	);
	return out;
}

async function run() {
	const prep = benchExecute(
		"erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.prepare_pdc_workflow_rollback_e2e"
	);
	const results = [];
	const evidence = { screenshots: {}, prep, sql: {} };

	const browser = await chromium.launch({ headless: true });
	const context = await browser.newContext({ locale: "en-US", viewport: { width: 1600, height: 950 } });
	const page = await context.newPage();
	page.setDefaultTimeout(180000);

	try {
		await login(page, "Administrator", "admin");

		// A: Registered → Draft
		await openPdc(page, prep.payable_registered);
		const a1 = await page.evaluate((findBtnSrc) => ({ has: !!eval(findBtnSrc)() }), FIND_ROLLBACK_BTN);
		evidence.screenshots.A0 = await shot(page, "A_registered_button_visible");
		const a = await rollbackViaUi(page, "Draft", "E2E rollback A");
		evidence.screenshots.A1 = await shot(page, "A_registered_to_draft");
		evidence.sql.A = sqlVerify(prep.payable_registered);
		results.push({
			test: "A_registered_to_draft",
			ok: a1.has && a.ok && a.workflow_state === "Draft" && evidence.sql.A.clean,
			a,
		});

		// B: Issued → Registered
		await openPdc(page, prep.payable_issued);
		evidence.screenshots.B0 = await shot(page, "B_issued_loaded");
		const b = await rollbackViaUi(page, "Registered", "E2E rollback B");
		evidence.screenshots.B1 = await shot(page, "B_issued_to_registered");
		evidence.sql.B = sqlVerify(prep.payable_issued);
		results.push({
			test: "B_issued_to_registered",
			ok: b.ok && b.workflow_state === "Registered" && evidence.sql.B.clean,
			b,
		});

		// H: Rollback preview (no confirm)
		await openPdc(page, prep.payable_cleared_preview);
		const hOpen = await openRollbackDialog(page);
		const h = await rollbackViaUi(page, "Issued", "E2E preview H", { confirm: false });
		evidence.screenshots.H = await shot(page, "H_preview_dialog");
		results.push({
			test: "H_rollback_preview",
			ok: hOpen.ok && h.ok && (h.preview || "").length > 20,
			h,
		});

		// C/D: Cleared → Issued → Registered → Draft
		await openPdc(page, prep.payable_cleared);
		evidence.screenshots.C0 = await shot(page, "C_cleared_loaded");
		const c1 = await rollbackViaUi(page, "Issued", "E2E rollback C1");
		evidence.sql.C1 = sqlVerify(prep.payable_cleared);
		evidence.screenshots.C1 = await shot(page, "C_cleared_to_issued");
		const c2 = await rollbackViaUi(page, "Registered", "E2E rollback C2");
		evidence.sql.C2 = sqlVerify(prep.payable_cleared);
		evidence.screenshots.C2 = await shot(page, "C_issued_to_registered");
		const c3 = await rollbackViaUi(page, "Draft", "E2E rollback C3");
		evidence.sql.C3 = sqlVerify(prep.payable_cleared);
		evidence.screenshots.C3 = await shot(page, "C_registered_to_draft");
		results.push({
			test: "C_D_cleared_to_draft_multistep",
			ok:
				c1.workflow_state === "Issued" &&
				c2.workflow_state === "Registered" &&
				c3.workflow_state === "Draft" &&
				evidence.sql.C1.clean &&
				evidence.sql.C2.clean &&
				evidence.sql.C3.clean,
			c1,
			c2,
			c3,
		});

		// K: forward workflow after rollback (Register Cheque)
		const kForward = benchExecute(
			"erpnext_extensions.cheque_management.e2e.pdc_workflow_rollback_prep.e2e_forward_register_after_rollback",
			{ pdc_name: prep.payable_cleared }
		);
		await openPdc(page, prep.payable_cleared);
		evidence.screenshots.K = await shot(page, "K_forward_registered_after_rollback");
		results.push({
			test: "K_rollback_then_forward",
			ok: kForward.ok && kForward.workflow_state === "Registered",
			kForward,
		});

		// J: rollback twice Cleared → Issued (second should fail)
		await openPdc(page, prep.payable_cleared_double);
		const j1 = await rollbackViaUi(page, "Issued", "E2E rollback J1");
		const j2 = await page.evaluate(async (pdcName) => {
			try {
				await frappe.call({
					method:
						"erpnext_extensions.cheque_management.pdc_workflow_rollback.rollback_workflow_state",
					args: { pdc_name: pdcName, target_state: "Issued", reason: "duplicate" },
				});
				return { rejected: false };
			} catch (e) {
				return { rejected: true, msg: e.message || String(e) };
			}
		}, prep.payable_cleared_double);
		evidence.screenshots.J = await shot(page, "J_double_rollback");
		results.push({
			test: "J_rollback_twice_second_rejected",
			ok: j1.workflow_state === "Issued" && j2.rejected,
			j1,
			j2,
		});

		// E: Returned → Issued
		await openPdc(page, prep.payable_returned);
		const e = await rollbackViaUi(page, "Issued", "E2E rollback E");
		evidence.screenshots.E = await shot(page, "E_returned_to_issued");
		results.push({ test: "E_returned_to_issued", ok: e.ok && e.workflow_state === "Issued", e });

		// F: Cancelled → Issued
		await openPdc(page, prep.payable_cancelled);
		const f = await rollbackViaUi(page, "Issued", "E2E rollback F");
		evidence.screenshots.F = await shot(page, "F_cancelled_to_issued");
		results.push({ test: "F_cancelled_to_issued", ok: f.ok && f.workflow_state === "Issued", f });

		// I: history grid visible with rows on a doc that has rollbacks
		await openPdc(page, prep.payable_cleared);
		const i = await page.evaluate(() => {
			const section = document.querySelector('[data-fieldname="workflow_rollback_logs"]');
			const rows = section?.querySelectorAll(".grid-row")?.length || 0;
			return { has: !!section, rows };
		});
		evidence.screenshots.I = await shot(page, "I_rollback_history");
		results.push({ test: "I_rollback_history", ok: i.has && i.rows >= 3, i });

		// G: Permission
		await page.goto(`${BASE}/api/method/logout`, { waitUntil: "domcontentloaded" });
		await login(page, prep.accounts_user, process.env.FRAPPE_E2E_PASSWORD || "admin");
		await openPdc(page, prep.receivable_cleared);
		const gUi = await page.evaluate((findBtnSrc) => ({ has: !!eval(findBtnSrc)() }), FIND_ROLLBACK_BTN);
		const gServer = await page.evaluate(async (pdcName) => {
			try {
				await frappe.call({
					method:
						"erpnext_extensions.cheque_management.pdc_workflow_rollback.rollback_workflow_state",
					args: { pdc_name: pdcName, target_state: "Issued", reason: "should fail" },
				});
				return { rejected: false };
			} catch (e) {
				return { rejected: true, msg: e.message || String(e) };
			}
		}, prep.receivable_cleared);
		evidence.screenshots.G = await shot(page, "G_non_privileged_no_button");
		results.push({
			test: "G_permission_no_button_and_server_reject",
			ok: !gUi.has && gServer.rejected,
			gUi,
			gServer,
		});
	} finally {
		await browser.close();
	}

	const all_ok = results.every((r) => r.ok);
	console.log(JSON.stringify({ all_ok, results, evidence }, null, 2));
	process.exit(all_ok ? 0 : 1);
}

run().catch((e) => {
	console.error(e);
	process.exit(1);
});
