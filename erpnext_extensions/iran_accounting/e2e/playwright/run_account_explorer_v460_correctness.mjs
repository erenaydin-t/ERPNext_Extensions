#!/usr/bin/env node
/**
 * v4.6.0 Account Explorer Final UI + Data Correctness Gate (scenarios A–E).
 *
 * Env:
 *   AE_BASE_URL   default http://restore-espad.localhost:8000
 *   AE_USER / AE_PASS
 *   AE_COMPANY    default اسپاد فارمد دارو
 *   AE_FISCAL_YEAR default 1405
 */
import { chromium } from "playwright";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const BASE = process.env.AE_BASE_URL || "http://restore-espad.localhost:8000";
const USER = process.env.AE_USER || "Administrator";
const PASS = process.env.AE_PASS || "admin";
const COMPANY = process.env.AE_COMPANY || "اسپاد فارمد دارو";
const FISCAL_YEAR = process.env.AE_FISCAL_YEAR || "1405";
const OUT = path.resolve(__dirname, "../screenshots/account-explorer-v460-correctness");

const checks = [];
const pass = (name, detail) => checks.push({ name, ok: true, detail });
const fail = (name, err) => checks.push({ name, ok: false, err: String(err) });

async function login(page) {
	await page.goto(`${BASE}/login?redirect-to=%2Fapp`);
	await page.fill("#login_email", USER);
	await page.fill("#login_password", PASS);
	await page.click(".btn-login");
	await page.waitForURL(/\/(app|desk)/, { timeout: 60000 });
}

async function shot(page, name) {
	fs.mkdirSync(OUT, { recursive: true });
	await page.screenshot({ path: path.join(OUT, `${name}.png`), fullPage: true });
}

async function get_ae(page) {
	return page.evaluate(() => {
		const page_obj = frappe?.pages?.["account-explorer"]?.page?.account_explorer
			|| cur_page?.account_explorer
			|| window.cur_ae
			|| null;
		if (!page_obj) {
			const wrapper = document.querySelector(".account-explorer-page");
			return wrapper ? { found_dom: true } : null;
		}
		return {
			found: true,
			loading: !!page_obj.store?.get?.("loading")?.summary,
			loading_banner_hidden: page_obj.$summary_loading?.hasClass?.("visually-hidden") ?? null,
			grid_loading_class: page_obj.$grid?.hasClass?.("ae-grid-wrap--loading") ?? null,
			rows: (page_obj.rows || []).length,
			total_rows: page_obj.pagination?.total_rows ?? null,
			totals: page_obj.totals || {},
			validation: page_obj._last_summary_validation || null,
			meta: page_obj._last_summary_response_meta || null,
			axis: page_obj.analysis_context?.view_axis,
			prepared: page_obj._last_summary_response_meta?.prepared_status,
		};
	});
}

async function resolve_ae_instance(page) {
	await page.waitForFunction(() => {
		const entry = frappe?.pages?.["account-explorer"];
		const ae =
			entry?.account_explorer ||
			entry?.wrapper?.account_explorer ||
			entry?.page?.main?.find?.(".ae-shell")?.parent?.()?.account_explorer;
		return !!(ae && ae.company_field && document.querySelector(".ae-shell, .ae-toolbar"));
	}, null, { timeout: 90000 });
	await page.evaluate(() => {
		const entry = frappe.pages["account-explorer"];
		const inst = entry?.account_explorer || entry?.wrapper?.account_explorer;
		if (!inst) {
			throw new Error("Account Explorer controller not attached");
		}
		window.cur_ae = inst;
	});
}

async function set_scope_and_apply(page, { company = COMPANY, fiscal_year = FISCAL_YEAR } = {}) {
	await page.evaluate(
		async ({ company, fiscal_year }) => {
			const ae = window.cur_ae;
			if (!ae) {
				throw new Error("Account Explorer instance missing");
			}
			ae.company_field.set_value(company);
			ae.document_scope.company = company;
			ae.fy_field.set_value(fiscal_year);
			ae.document_scope.fiscal_year = fiscal_year;
			if (typeof ae.sync_dates_from_fy === "function") {
				ae.sync_dates_from_fy();
			}
			await new Promise((r) => setTimeout(r, 600));
			ae.document_scope.from_date = ae.from_date_field.get_value();
			ae.document_scope.to_date = ae.to_date_field.get_value();
		},
		{ company, fiscal_year }
	);
	await page.locator("button.ae-btn-apply").click();
}

async function wait_summary_idle(page, { timeout = 180000 } = {}) {
	const started = Date.now();
	while (Date.now() - started < timeout) {
		const state = await page.evaluate(() => {
			const ae = window.cur_ae;
			if (!ae) {
				return { ready: false, reason: "no_ae" };
			}
			const loading = !!ae.store?.get?.("loading")?.summary;
			const banner_hidden =
				ae.$summary_loading?.hasClass?.("visually-hidden") ||
				ae.$summary_loading?.hasClass?.("is-hidden");
			const banner_display = ae.$summary_loading?.length
				? window.getComputedStyle(ae.$summary_loading.get(0)).display
				: "none";
			const wrap_loading = ae.$grid?.hasClass?.("ae-grid-wrap--loading");
			const preparing = !!ae._summary_preparing_state;
			const apply_disabled = !!ae.$toolbar?.find?.(".ae-btn-apply")?.prop?.("disabled");
			const toolbar_loading = !!ae.$toolbar?.hasClass?.("ae-toolbar--loading");
			const loading_owner = ae._summary_loading_generation;
			return {
				ready:
					!loading &&
					banner_hidden &&
					banner_display === "none" &&
					!wrap_loading &&
					!preparing &&
					loading_owner == null &&
					!apply_disabled &&
					!toolbar_loading,
				loading,
				banner_hidden,
				banner_display,
				wrap_loading,
				preparing,
				apply_disabled,
				toolbar_loading,
				loading_owner,
				rows: (ae.rows || []).length,
				validation: ae._last_summary_validation || null,
				meta: ae._last_summary_response_meta || null,
				totals: ae.totals || {},
				total_rows: ae.pagination?.total_rows ?? null,
				axis: ae.analysis_context?.view_axis,
				trace: ae._last_summary_loading_trace || null,
			};
		});
		if (state.ready) {
			return state;
		}
		await page.waitForTimeout(500);
	}
	throw new Error("Timed out waiting for Account Explorer summary idle");
}

async function assert_loading_cleared_after_rows(page, label) {
	await page.waitForSelector(
		".ae-grid-container--datatable .dt-row:not(.dt-row-header):not(.dt-row-filter), table.ae-grid tbody tr",
		{ timeout: 180000 }
	);
	// Hard requirement: computed display must be none (class alone is insufficient).
	await page.waitForFunction(() => {
		const banner = document.querySelector(".ae-summary-loading");
		if (!banner) {
			return true;
		}
		return window.getComputedStyle(banner).display === "none";
	}, null, { timeout: 15000 });

	const probe = await page.evaluate(() => {
		const banner = document.querySelector(".ae-summary-loading");
		const spinner = document.querySelector(".ae-summary-loading__spinner");
		const apply = document.querySelector("button.ae-btn-apply");
		const toolbar = document.querySelector(".ae-toolbar");
		const ae = window.cur_ae;
		const banner_style = banner ? window.getComputedStyle(banner) : null;
		const spinner_style = spinner ? window.getComputedStyle(spinner) : null;
		const banner_box = banner ? banner.getBoundingClientRect() : null;
		return {
			banner_display: banner_style?.display || null,
			banner_height: banner_box?.height || 0,
			banner_text: (banner?.innerText || "").trim(),
			spinner_display: spinner_style?.display || null,
			apply_disabled: !!apply?.disabled,
			toolbar_loading: !!toolbar?.classList.contains("ae-toolbar--loading"),
			store_loading: !!ae?.store?.get?.("loading")?.summary,
			loading_owner: ae?._summary_loading_generation ?? null,
			trace: ae?._last_summary_loading_trace || null,
		};
	});
	const ok =
		probe.banner_display === "none" &&
		probe.banner_height === 0 &&
		!probe.banner_text &&
		!probe.apply_disabled &&
		!probe.toolbar_loading &&
		!probe.store_loading &&
		probe.loading_owner == null;
	if (ok) {
		pass(`${label} loading banner/spinner hidden + toolbar enabled`);
	} else {
		fail(`${label} loading banner/spinner hidden + toolbar enabled`, JSON.stringify(probe));
	}
	return probe;
}

async function count_visible_rows(page) {
	return page.evaluate(() => {
		const dt = document.querySelectorAll(
			".ae-grid-container--datatable .dt-row:not(.dt-row-header):not(.dt-row-filter)"
		).length;
		if (dt > 0) {
			return dt;
		}
		return document.querySelectorAll("table.ae-grid tbody tr").length;
	});
}

async function amount_cells_ok(page) {
	return page.evaluate(() => {
		const headers = [
			...document.querySelectorAll(
				".ae-grid-container--datatable .dt-cell--header.ae-dt-amount-col, table.ae-grid th.amount"
			),
		];
		const cells = [
			...document.querySelectorAll(
				".dt-cell.ae-dt-amount-col, .ae-dt-amount-cell, table.ae-grid td.amount"
			),
		];
		if (!headers.length && !cells.length) {
			return { ok: false, reason: "no_amount_cells" };
		}
		const measure = (el) => {
			const style = window.getComputedStyle(el);
			const rect = el.getBoundingClientRect();
			return {
				width: rect.width,
				minWidth: style.minWidth,
				whiteSpace: style.whiteSpace,
				textAlign: style.textAlign,
				text: (el.innerText || "").trim().slice(0, 40),
			};
		};
		const header_sample = headers.slice(0, 4).map(measure);
		const cell_sample = cells.slice(0, 8).map(measure);
		const narrow_headers = header_sample.filter((s) => s.width > 0 && s.width < 175);
		const bad_align = [...header_sample, ...cell_sample].filter(
			(s) => s.textAlign !== "end" && s.textAlign !== "right"
		);
		const non_nowrap = [...header_sample, ...cell_sample].filter(
			(s) => s.whiteSpace !== "nowrap" && s.whiteSpace !== "pre"
		);
		return {
			ok: narrow_headers.length === 0 && bad_align.length === 0 && non_nowrap.length === 0,
			header_sample,
			cell_sample,
			narrow_headers: narrow_headers.length,
			bad_align: bad_align.length,
			non_nowrap: non_nowrap.length,
		};
	});
}

async function switch_axis(page, axis_id) {
	await page.evaluate(async (axis) => {
		const ae = window.cur_ae;
		ae.prepared_mode = null;
		ae.analysis_context.view_axis = axis;
		ae.analysis_context.page = 1;
		ae.analysis_context.detail_mode = "summary";
		if (axis === "voucher") {
			ae.analysis_context.voucher_scope = ae.analysis_context.voucher_scope || {
				voucher_type: null,
				voucher_no: null,
			};
			ae.analysis_context.sort_field = "posting_date";
		} else if (axis === "account_level") {
			ae.analysis_context.sort_field = "display_code";
		}
		try {
			if (typeof ae.render_navigator === "function") {
				ae.render_navigator();
			}
		} catch (e) {
			console.warn("render_navigator", e);
		}
		await ae.refresh_summary();
	}, axis_id);
}

async function call_summary_api(page, { view_axis = "account_level", prepared_mode = null, tweak = null } = {}) {
	return page.evaluate(
		async ({ view_axis, prepared_mode, tweak }) => {
			const ae = window.cur_ae;
			const payload = ae.build_payload();
			payload.analysis_context.view_axis = view_axis;
			payload.analysis_context.detail_mode = "summary";
			if (prepared_mode) {
				payload.prepared_mode = prepared_mode;
			}
			if (tweak === "shift_from_date") {
				const d = new Date(payload.document_scope.from_date);
				d.setDate(d.getDate() + 1);
				payload.document_scope.from_date = d.toISOString().slice(0, 10);
			}
			const method = ae.get_summary_method();
			const r = await frappe.call({ method, args: { payload: JSON.stringify(payload) } });
			return r.message || {};
		},
		{ view_axis, prepared_mode, tweak }
	);
}

async function main() {
	fs.mkdirSync(OUT, { recursive: true });
	const browser = await chromium.launch({ headless: true });
	const page = await (
		await browser.newContext({ locale: "en-US", viewport: { width: 1440, height: 900 } })
	).newPage();
	page.setDefaultTimeout(60000);
	const evidence = { scenarios: {}, validations: [] };

	try {
		await login(page);
		pass("login");

		await page.goto(`${BASE}/app/account-explorer`);
		await page.waitForSelector(".account-explorer-page, .ae-shell", { timeout: 60000 });
		await resolve_ae_instance(page);
		pass("page loads");

		// ---------- Scenario A: Live Account Explorer ----------
		await page.evaluate(() => {
			window.cur_ae.prepared_mode = "live";
		});
		await set_scope_and_apply(page);
		let state = await wait_summary_idle(page);
		await shot(page, "01-before-a-live");
		const visible_a = await count_visible_rows(page);
		evidence.scenarios.A = { state, visible_a };
		if ((state.rows || 0) > 0 && visible_a > 0) pass("A rows > 0 and visible");
		else fail("A rows > 0 and visible", JSON.stringify({ rows: state.rows, visible_a }));
		const amounts_a = await amount_cells_ok(page);
		evidence.scenarios.A.amounts = amounts_a;
		if (amounts_a.ok) pass("A debit/credit cells visible & wide");
		else fail("A debit/credit cells visible & wide", JSON.stringify(amounts_a));
		evidence.scenarios.A.loading = await assert_loading_cleared_after_rows(page, "A");
		await shot(page, "02-after-a-live-no-banner");

		// ---------- Scenario B: Prepared miss → preparing → completed ----------
		await page.evaluate(() => {
			window.cur_ae.prepared_mode = null;
			window.__AE_TRACE_LOADING__ = true;
		});
		const miss = await call_summary_api(page, {
			view_axis: "account_level",
			tweak: "shift_from_date",
		});
		evidence.scenarios.B_miss_api = {
			status: miss.status,
			fingerprint: miss.fingerprint,
			prepared: miss.prepared,
			total_rows: miss.pagination?.total_rows,
		};
		// Force UI refresh with shifted from_date to exercise preparing path
		await page.evaluate(() => {
			const ae = window.cur_ae;
			ae.prepared_mode = null;
			const from = ae.from_date_field.get_value();
			const d = new Date(from);
			d.setDate(d.getDate() + 1);
			const next = d.toISOString().slice(0, 10);
			ae.from_date_field.set_value(next);
			ae.document_scope.from_date = next;
			ae.refresh_summary();
		});
		state = await wait_summary_idle(page, { timeout: 300000 });
		const visible_b = await count_visible_rows(page);
		evidence.scenarios.B = { state, visible_b, miss_status: miss.status };
		if ((state.rows || 0) > 0 && visible_b > 0) pass("B rows appear after prepare");
		else fail("B rows appear after prepare", JSON.stringify({ rows: state.rows, visible_b }));
		if (state.totals && (state.totals.period_debit != null || state.totals.scoped_debit != null)) {
			pass("B totals appear");
		} else {
			fail("B totals appear", JSON.stringify(state.totals));
		}
		evidence.scenarios.B.loading = await assert_loading_cleared_after_rows(page, "B");
		await shot(page, "03-after-b-prepared-miss-no-banner");

		// ---------- Scenario C: Prepared hit ----------
		const before_hit = {
			rows: state.rows,
			totals: { ...state.totals },
			total_rows: state.total_rows,
		};
		await page.evaluate(() => {
			window.cur_ae.prepared_mode = null;
			window.cur_ae.refresh_summary();
		});
		state = await wait_summary_idle(page);
		const hit_meta = state.meta || {};
		const hit_api = await call_summary_api(page, { view_axis: "account_level" });
		evidence.scenarios.C = {
			state,
			before_hit,
			hit_api: {
				prepared: hit_api.prepared,
				fingerprint: hit_api.fingerprint,
				status: hit_api.status,
			},
		};
		if (cint_like(hit_api.prepared) || cint_like(hit_meta.prepared_status) || hit_meta.source === "prepared") {
			pass("C response from prepared artifact");
		} else {
			fail(
				"C response from prepared artifact",
				JSON.stringify({
					prepared: hit_api.prepared,
					fingerprint: hit_api.fingerprint,
					status: hit_api.status,
					hit_meta,
				})
			);
		}
		if (state.rows === before_hit.rows && Number(state.total_rows) === Number(before_hit.total_rows)) {
			pass("C rows count unchanged");
		} else {
			fail("C rows count unchanged", JSON.stringify({ before_hit, after: state }));
		}
		const tot_ok =
			nearly_eq(state.totals?.period_debit, before_hit.totals?.period_debit) &&
			nearly_eq(state.totals?.period_credit, before_hit.totals?.period_credit);
		if (tot_ok) pass("C totals unchanged");
		else fail("C totals unchanged", JSON.stringify({ before: before_hit.totals, after: state.totals }));
		evidence.scenarios.C.loading = await assert_loading_cleared_after_rows(page, "C");
		await shot(page, "04-after-c-prepared-hit-no-banner");

		// ---------- Refresh / filter apply / rapid double Apply ----------
		await page.evaluate(() => window.cur_ae.refresh_summary());
		state = await wait_summary_idle(page);
		evidence.scenarios.refresh = { state };
		evidence.scenarios.refresh.loading = await assert_loading_cleared_after_rows(page, "Refresh");
		await shot(page, "05-after-refresh-no-banner");

		await page.locator("button.ae-btn-apply").click();
		state = await wait_summary_idle(page);
		evidence.scenarios.filter_apply = { state };
		evidence.scenarios.filter_apply.loading = await assert_loading_cleared_after_rows(page, "Filter Apply");

		await page.locator("button.ae-btn-apply").click();
		await page.locator("button.ae-btn-apply").click();
		state = await wait_summary_idle(page);
		evidence.scenarios.double_apply = { state };
		evidence.scenarios.double_apply.loading = await assert_loading_cleared_after_rows(page, "Double Apply");
		await shot(page, "06-after-double-apply-no-banner");

		// ---------- Scenario D: Voucher axis ----------
		await switch_axis(page, "voucher");
		state = await wait_summary_idle(page, { timeout: 300000 });
		const visible_d = await count_visible_rows(page);
		const voucher_api = await call_summary_api(page, { view_axis: "voucher" });
		evidence.scenarios.D = {
			state,
			visible_d,
			api_total: voucher_api.pagination?.total_rows,
			api_totals: voucher_api.totals,
		};
		if ((state.total_rows || state.rows || 0) > 0 && visible_d > 0) pass("D document count > 0");
		else fail("D document count > 0", JSON.stringify(evidence.scenarios.D));
		const voucher_tot_ok =
			nearly_eq(state.totals?.scoped_debit, voucher_api.totals?.scoped_debit) &&
			nearly_eq(state.totals?.scoped_credit, voucher_api.totals?.scoped_credit);
		if (voucher_tot_ok) pass("D voucher totals match API");
		else fail("D voucher totals match API", JSON.stringify({ ui: state.totals, api: voucher_api.totals }));
		evidence.scenarios.D.loading = await assert_loading_cleared_after_rows(page, "D");
		if (state.validation) evidence.validations.push({ scenario: "D", ...state.validation });
		await shot(page, "07-after-d-voucher-no-banner");

		// ---------- Scenario E: Account axis ----------
		await switch_axis(page, "account_level");
		state = await wait_summary_idle(page, { timeout: 300000 });
		const visible_e = await count_visible_rows(page);
		const account_api = await call_summary_api(page, { view_axis: "account_level" });
		evidence.scenarios.E = {
			state,
			visible_e,
			api_accounts: account_api.pagination?.total_rows,
			api_totals: account_api.totals,
			returned: (account_api.rows || []).length,
		};
		if ((account_api.pagination?.total_rows || 0) > 0 && visible_e > 0) {
			pass("E accounts returned and visible", { total_rows: account_api.pagination?.total_rows });
		} else {
			fail("E accounts returned and visible", JSON.stringify(evidence.scenarios.E));
		}
		const account_tot_ok =
			nearly_eq(state.totals?.period_debit, account_api.totals?.period_debit) &&
			nearly_eq(state.totals?.period_credit, account_api.totals?.period_credit) &&
			nearly_eq(state.totals?.debit_balance, account_api.totals?.debit_balance) &&
			nearly_eq(state.totals?.credit_balance, account_api.totals?.credit_balance);
		if (account_tot_ok) pass("E displayed debit/credit equals backend totals");
		else fail("E displayed debit/credit equals backend totals", JSON.stringify({ ui: state.totals, api: account_api.totals }));
		evidence.scenarios.E.loading = await assert_loading_cleared_after_rows(page, "E");
		if (state.validation) evidence.validations.push({ scenario: "E", ...state.validation });
		await shot(page, "08-after-e-account-no-banner");
	} catch (e) {
		const err = e && typeof e === "object" ? e.message || e.stack || JSON.stringify(e, Object.getOwnPropertyNames(e)) : String(e);
		fail("unexpected", err);
		await shot(page, "99-error").catch(() => {});
	} finally {
		await browser.close();
	}

	const failed = checks.filter((c) => !c.ok);
	const report = {
		gate: "v4.6.0-ui-data-correctness",
		base: BASE,
		company: COMPANY,
		fiscal_year: FISCAL_YEAR,
		checks,
		failed: failed.length,
		screenshot_dir: OUT,
		evidence,
		verdict: failed.length ? "NOT READY" : "READY",
	};
	fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
	console.log(JSON.stringify(report, null, 2));
	process.exit(failed.length ? 1 : 0);
}

function nearly_eq(a, b, eps = 0.05) {
	const na = Number(a || 0);
	const nb = Number(b || 0);
	return Math.abs(na - nb) <= eps;
}

function cint_like(v) {
	return v === 1 || v === "1" || v === true;
}

main();
