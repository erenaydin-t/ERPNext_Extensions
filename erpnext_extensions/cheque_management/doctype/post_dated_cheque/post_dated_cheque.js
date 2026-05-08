// Copyright (c) 2025, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

/** Cached DocField defaults from form meta (first run). */
let _pdc_meta = {
	bank_account_description: null,
	account_paid_from_description: null,
	account_paid_to_description: null,
	party_type_description: null,
};

/** Default party type when **cheque_direction** is Receivable (semantic mode). */
const PDC_RECEIVABLE_DEFAULT_PARTY_TYPE = "Customer";
/** Default party type when **cheque_direction** is Payable (semantic mode). */
const PDC_PAYABLE_DEFAULT_PARTY_TYPE = "Supplier";

/** Set `window.PDC_DEBUG_RECEIVABLE_INIT = true` before opening a new PDC to log initialization order in the console. */
function pdc_trace(...args) {
	if (typeof window !== "undefined" && window.PDC_DEBUG_RECEIVABLE_INIT) {
		console.log("[PDC]", ...args);
	}
}

/** Unsaved new document: `__islocal` is the reliable signal on first paint (`is_new()` can lag in some load orders). */
function pdc_is_new_unsaved(frm) {
	return !!(frm && frm.doc && (frm.doc.__islocal || (typeof frm.is_new === "function" && frm.is_new())));
}

/**
 * Keep **allocated_amount** / **unallocated_amount** in sync with child **allocations** (same math as
 * ``sync_pdc_allocation_summary_amounts`` on the server). Required because **new_doc** + prefilled rows
 * do not recompute read-only parent currency fields until save.
 */
function pdc_safe_flt(v) {
	if (frappe && frappe.utils && typeof frappe.utils.flt === "function") {
		return frappe.utils.flt(v);
	}
	const x = parseFloat(v);
	return Number.isFinite(x) ? x : 0;
}

/**
 * When opening PDC from Payment Request / invoice with a single prefilled allocation row, both
 * cheque_amount and allocated_amount default to full remaining capacity. If the user lowers
 * cheque_amount for a partial cheque, keep the one row in sync so validation does not fail.
 */
function pdc_sync_single_allocation_to_cheque_amount(frm) {
	if (!frm || !frm.doc || !pdc_is_new_unsaved(frm)) {
		return;
	}
	const rows = frm.doc.allocations || [];
	if (rows.length !== 1) {
		return;
	}
	const ch = pdc_safe_flt(frm.doc.cheque_amount);
	const row = rows[0];
	if (frm._pdc_sync_alloc_from_cheque) {
		return;
	}
	frm._pdc_sync_alloc_from_cheque = true;
	try {
		const cdt = row.doctype || "PDC Allocation";
		const cdn = row.name;
		if (cdn) {
			frappe.model.set_value(cdt, cdn, "amount", ch);
		} else {
			row.amount = ch;
		}
	} finally {
		frm._pdc_sync_alloc_from_cheque = false;
	}
}

function pdc_sync_allocation_summary_client(frm) {
	if (!frm || !frm.doc || frm._pdc_syncing_allocation_summary) {
		return;
	}
	let total = 0;
	(frm.doc.allocations || []).forEach(function (row) {
		total += pdc_safe_flt(row.amount);
	});
	const cheque_amt = pdc_safe_flt(frm.doc.cheque_amount);
	const allocated = pdc_safe_flt(total);
	const unallocated = pdc_safe_flt(cheque_amt - allocated);
	const eps = 1e-6;
	if (
		Math.abs(pdc_safe_flt(frm.doc.allocated_amount) - allocated) < eps &&
		Math.abs(pdc_safe_flt(frm.doc.unallocated_amount) - unallocated) < eps
	) {
		return;
	}
	frm._pdc_syncing_allocation_summary = true;
	try {
		// Avoid ``frm.set_value`` on read-only Currency fields — it can steal focus (blue outline) while syncing.
		frm.doc.allocated_amount = allocated;
		frm.doc.unallocated_amount = unallocated;
		["allocated_amount", "unallocated_amount"].forEach(function (fn) {
			if (frm.fields_dict[fn] && frm.fields_dict[fn].refresh) {
				frm.refresh_field(fn);
			}
		});
	} finally {
		frm._pdc_syncing_allocation_summary = false;
	}
}

/**
 * ``frappe.new_doc(..., prefill)`` assigns Table values directly from route options and does NOT
 * create proper child documents via ``frappe.model.get_new_doc`` / ``add_child``.
 *
 * That leaves rows without ``name`` / ``parenttype`` / ``parentfield`` which can crash
 * ``frappe.ui.form.check_mandatory`` (save.js) when a mandatory field is missing in any such row.
 *
 * Normalize prefilled ``allocations`` into real child docs before save.
 */
function pdc_normalize_prefilled_allocations(frm) {
	if (!frm || !frm.doc || frm._pdc_normalized_allocations) {
		return;
	}
	if (!pdc_is_new_unsaved(frm)) {
		return;
	}
	const rows = frm.doc.allocations || [];
	if (!rows.length) {
		frm._pdc_normalized_allocations = true;
		return;
	}
	const is_malformed = (r) =>
		r && r.doctype === "PDC Allocation" && (!r.name || !r.parenttype || !r.parentfield);
	if (!rows.some(is_malformed)) {
		frm._pdc_normalized_allocations = true;
		return;
	}
	// Rebuild rows as proper child docs.
	const incoming = rows.slice();
	frm.doc.allocations = [];
	incoming.forEach(function (r) {
		const child = frappe.model.add_child(frm.doc, "PDC Allocation", "allocations");
		[
			"allocation_mode",
			"reference_doctype",
			"reference_name",
			"amount",
			"company",
			"party_type",
			"party",
			"source_doctype",
			"source_name",
		].forEach(function (fn) {
			if (r && r[fn] !== undefined) {
				child[fn] = r[fn];
			}
		});
	});
	if (frm.fields_dict.allocations) {
		frm.refresh_field("allocations");
	}
	frm._pdc_normalized_allocations = true;
}

function pdc_allocation_row_is_effectively_empty(row) {
	const amt = pdc_safe_flt(row && row.amount);
	const at = row && row.allocation_mode != null ? String(row.allocation_mode).trim() : "";
	const rdt = row && row.reference_doctype != null ? String(row.reference_doctype).trim() : "";
	const rnm = row && row.reference_name != null ? String(row.reference_name).trim() : "";
	return amt <= 0 && !at && !rdt && !rnm;
}

/** Prefill allocation from parent **reference_doctype** / **reference_name** when creating from SI/PI. */
function pdc_autofill_allocations_from_parent_source(frm) {
	if (!frm || !frm.doc) {
		return;
	}
	const pdt = (frm.doc.reference_doctype || "").trim();
	const pnm = (frm.doc.reference_name || "").trim();
	if ((pdt !== "Purchase Invoice" && pdt !== "Sales Invoice") || !pnm) {
		return;
	}
	const ch = pdc_safe_flt(frm.doc.cheque_amount);
	(frm.doc.allocations || []).forEach(function (row) {
		const hasRef =
			(row.reference_doctype || "").trim() && (row.reference_name || "").trim();
		if (hasRef) {
			return;
		}
		const prevAmt = pdc_safe_flt(row.amount);
		const cdt = row.doctype || "PDC Allocation";
		const cdn = row.name;
		if (!(row.allocation_mode || "").trim()) {
			// direct_settlement is the only valid mode when prefilled from invoice.
			if (cdn) frappe.model.set_value(cdt, cdn, "allocation_mode", "direct_settlement");
			else row.allocation_mode = "direct_settlement";
		}
		if (cdn) {
			frappe.model.set_value(cdt, cdn, "reference_doctype", pdt);
			frappe.model.set_value(cdt, cdn, "reference_name", pnm);
			if (ch > 0 && prevAmt <= 0) {
				frappe.model.set_value(cdt, cdn, "amount", ch);
			}
		} else {
			row.reference_doctype = pdt;
			row.reference_name = pnm;
			if (ch > 0 && prevAmt <= 0) {
				row.amount = ch;
			}
		}
	});
}

/** Remove blank grid rows so Frappe ``check_mandatory`` does not crash on half-filled children. */
function pdc_strip_empty_allocation_rows(frm) {
	if (!frm || !frm.doc || !frm.doc.allocations || !frm.doc.allocations.length) {
		return;
	}
	const rows = frm.doc.allocations;
	for (let i = rows.length - 1; i >= 0; i--) {
		const row = rows[i];
		if (!pdc_allocation_row_is_effectively_empty(row)) {
			continue;
		}
		if (row.name) {
			frappe.model.clear_doc(row.doctype || "PDC Allocation", row.name);
		} else {
			rows.splice(i, 1);
		}
	}
	if (frm.fields_dict.allocations) {
		frm.refresh_field("allocations");
	}
}

/** Client-side guard before ``check_mandatory`` (runs in ``validate``). */
function pdc_validate_allocations_client(frm) {
	// v1: authoritative validation is server-side (Task 2). Client-side guards here are intentionally minimal.
	return;
}

/**
 * Match Python ``_get_pdc_settings_for_company``: ``frappe.db.get_value("PDC Settings", {"company": company}, "name") or company``.
 * Client-only ``{ company: c }`` lookups can return no row when the stored **name** equals **company** but filters do not match.
 */
function pdc_resolve_pdc_settings_docname(company) {
	const c = (company || "").trim();
	if (!c) {
		return Promise.resolve(null);
	}
	return frappe.db.get_value("PDC Settings", { company: c }, "name").then((r) => {
		const msg = r && r.message;
		const n = msg && (msg.name !== undefined && msg.name !== null ? msg.name : msg);
		const name = n != null && String(n).trim() ? String(n).trim() : "";
		return name || c;
	});
}

frappe.ui.form.on("Post Dated Cheque", {
	setup(frm) {
		// Align with prefilled **cheque_direction** so the first ``cheque_direction`` handler pass does not look
		// like a user mode switch (which would clear **party** / reset defaults — breaks create-from-source).
		frm._pdc_last_cheque_direction = frm.doc.cheque_direction;
		// Track last seen **party_type** so we only clear **party** on a real user edit (not first bind from prefill).
		frm._pdc_prev_party_type_str = (frm.doc.party_type || "").trim();
		frm._pdc_prev_bank_account = (frm.doc.bank_account || "").trim();
		pdc_normalize_prefilled_allocations(frm);
		pdc_trace("setup", { company: frm.doc && frm.doc.company, __islocal: frm.doc && frm.doc.__islocal });
	},

	onload_post_render(frm) {
		pdc_trace("onload_post_render", { company: frm.doc.company, __islocal: frm.doc.__islocal });
		pdc_normalize_prefilled_allocations(frm);
		pdc_autofill_allocations_from_parent_source(frm);
		pdc_schedule_initial_receivable_accounts(frm);
		pdc_apply_cheque_leaf_ui(frm);
		pdc_apply_cheque_leaf_behaviour(frm);
		pdc_schedule_cheque_leaf_ui_enforcement(frm);
		pdc_sync_allocation_summary_client(frm);
	},

	validate(frm) {
		pdc_normalize_prefilled_allocations(frm);
		pdc_autofill_allocations_from_parent_source(frm);
		pdc_strip_empty_allocation_rows(frm);
		pdc_validate_allocations_client(frm);
	},

	refresh(frm) {
		pdc_trace("refresh", { company: frm.doc.company, cheque_direction: frm.doc.cheque_direction, __islocal: frm.doc.__islocal });
		pdc_apply_direction_dependent_ui(frm);
		pdc_apply_cheque_direction_lock_ui(frm);
		pdc_apply_payable_bank_account_lock_ui(frm);
		pdc_apply_cheque_leaf_behaviour(frm);
		pdc_schedule_cheque_leaf_ui_enforcement(frm);
		pdc_normalize_prefilled_allocations(frm);
		pdc_sync_allocation_summary_client(frm);
		frm._pdc_last_cheque_direction = frm.doc.cheque_direction;
	},

	cheque_amount(frm) {
		pdc_sync_single_allocation_to_cheque_amount(frm);
		pdc_sync_allocation_summary_client(frm);
	},

	allocated_amount(frm) {
		pdc_sync_allocation_summary_client(frm);
	},

	allocations_add(frm, cdt, cdn) {
		pdc_sync_allocation_summary_client(frm);
	},

	allocations_remove(frm, cdt, cdn) {
		pdc_sync_allocation_summary_client(frm);
	},

	party(frm) {
		set_default_party_accounts(frm);
	},

	party_type(frm) {
		const cur_pt = (frm.doc.party_type || "").trim();
		if (frm._pdc_prev_party_type_str !== cur_pt) {
			pdc_clear_party_on_party_type_change(frm);
		}
		frm._pdc_prev_party_type_str = cur_pt;
		if (!frm._pdc_suppress_party_type_account_reresolve) {
			pdc_reresolve_accounts_after_party_type_change(frm);
		}
	},

	cheque_direction(frm) {
		const prev = frm._pdc_last_cheque_direction;
		const done = pdc_on_cheque_direction_changed(frm, prev);
		const finish = () => {
			// If switching to Receivable, clear any leaf-derived data immediately.
			pdc_cleanup_cheque_leaf_when_not_payable(frm);
			pdc_sync_holder_to_party_for_direction(frm, prev, frm.doc.cheque_direction);
			pdc_apply_direction_dependent_ui(frm);
			pdc_apply_cheque_direction_lock_ui(frm);
			pdc_apply_cheque_leaf_ui(frm);
			pdc_apply_cheque_leaf_behaviour(frm);
			pdc_schedule_cheque_leaf_ui_enforcement(frm);
			frm._pdc_last_cheque_direction = frm.doc.cheque_direction;
		};
		if (done && typeof done.then === "function") {
			done.then(finish).catch(() => finish());
		} else {
			finish();
		}
	},

	company(frm) {
		pdc_trace("company", { company: frm.doc.company });
		pdc_apply_direction_dependent_ui(frm);
		pdc_apply_cheque_leaf_behaviour(frm);
		pdc_schedule_cheque_leaf_ui_enforcement(frm);
		pdc_schedule_initial_receivable_accounts(frm);
		frm._pdc_last_cheque_direction = frm.doc.cheque_direction;
	},

	bank_account(frm) {
		pdc_handle_bank_account_change_for_cheque_leaf(frm);
		pdc_apply_cheque_leaf_behaviour(frm);
		pdc_schedule_cheque_leaf_ui_enforcement(frm);
	},

	cheque_leaf(frm) {
		pdc_apply_cheque_leaf_behaviour(frm);
		pdc_schedule_cheque_leaf_ui_enforcement(frm);
	},

	received_date(frm) {
		pdc_validate_lifecycle_dates(frm);
		pdc_warn_if_future_date(frm, "received_date", __("Received / Issued Date"));
	},

	handover_date(frm) {
		pdc_validate_lifecycle_dates(frm);
		pdc_warn_if_future_date(frm, "handover_date", __("Handover / Endorsement Date"));
	},

	sent_to_bank_date(frm) {
		pdc_validate_lifecycle_dates(frm);
	},

	cleared_date(frm) {
		pdc_validate_lifecycle_dates(frm);
		pdc_warn_if_future_date(frm, "cleared_date", __("Cleared Date"));
	},

	bounced_date(frm) {
		pdc_validate_lifecycle_dates(frm);
		pdc_warn_if_future_date(frm, "bounced_date", __("Bounced Date"));
	},

	returned_date(frm) {
		pdc_validate_lifecycle_dates(frm);
		pdc_warn_if_future_date(frm, "returned_date", __("Returned Date"));
	},

	/** Workflow / apply_workflow updates this Link; refresh dependent visibility + mandatory stars. */
	workflow_state(frm) {
		frm.refresh_field("handover_date");
		frm.refresh_field("cleared_date");
		frm.refresh_field("sent_to_bank_date");
		frm.refresh_field("bounced_date");
		frm.refresh_field("return_reason");
		frm.refresh_field("returned_date");
		frm.refresh_field("sayad_code");
		frm.refresh_field("sayad_registered");
	},
});

frappe.ui.form.on("PDC Allocation", {
	amount(frm, cdt, cdn) {
		pdc_sync_allocation_summary_client(frm);
	},
});

/** True if ``later`` is strictly before ``earlier`` (both YYYY-MM-DD strings); false if either side missing. */
function pdc_date_out_of_order(later, earlier) {
	if (!later || !earlier) {
		return false;
	}
	return frappe.datetime.get_diff(later, earlier) < 0;
}

/** Client hints when both dates in a pair are set; server lifecycle validators in ``post_dated_cheque.py`` are authoritative. */
function pdc_validate_lifecycle_dates(frm) {
	const d = frm.doc;
	if (pdc_date_out_of_order(d.handover_date, d.received_date)) {
		frappe.msgprint({
			title: __("Invalid Date Sequence"),
			message: __(
				"Handover / Endorsement Date cannot be earlier than Received / Issued Date.\n" +
					"A cheque cannot be handed over before it is issued or recorded."
			),
			indicator: "red",
		});
	}
	if (d.cheque_direction === "Receivable") {
		if (pdc_date_out_of_order(d.sent_to_bank_date, d.received_date)) {
			frappe.msgprint({
				title: __("Invalid Date Sequence"),
				message: __(
					"Sent to Bank Date cannot be earlier than Received / Issued Date.\n" +
						"A receivable cheque cannot be sent for collection before it was received or recorded."
				),
				indicator: "red",
			});
		}
		if (pdc_date_out_of_order(d.cleared_date, d.sent_to_bank_date)) {
			frappe.msgprint({
				title: __("Invalid Date Sequence"),
				message: __(
					"Cleared Date cannot be earlier than Sent to Bank Date.\n" +
						"Bank settlement cannot occur before the cheque was sent to the bank."
				),
				indicator: "red",
			});
		}
		if (pdc_date_out_of_order(d.bounced_date, d.sent_to_bank_date)) {
			frappe.msgprint({
				title: __("Invalid Date Sequence"),
				message: __(
					"Bounced Date cannot be earlier than Sent to Bank Date.\n" +
						"A bank rejection cannot be recorded before the cheque was sent to the bank."
				),
				indicator: "red",
			});
		}
	}
	if (pdc_date_out_of_order(d.returned_date, d.received_date)) {
		frappe.msgprint({
			title: __("Invalid Date Sequence"),
			message: __(
				"Returned Date cannot be earlier than Received / Issued Date.\n" +
					"A business return cannot be recorded before the cheque was received or issued."
			),
			indicator: "red",
		});
	}
	if (d.cheque_direction === "Payable" && pdc_date_out_of_order(d.cleared_date, d.handover_date)) {
		frappe.msgprint({
			title: __("Invalid Date Sequence"),
			message: __(
				"Cleared Date cannot be earlier than Handover / Endorsement Date.\n" +
					"Bank withdrawal or settlement cannot occur before the cheque was physically handed over."
			),
			indicator: "red",
		});
	}
}

function pdc_warn_if_future_date(frm, fieldname, label) {
	try {
		if (!frm || !frm.doc) return;
		const v = frm.doc[fieldname];
		if (!v) return;
		const today = frappe.datetime.get_today();
		// Both are YYYY-MM-DD strings.
		if (frappe.datetime.get_diff(v, today) > 0) {
			frappe.show_alert(
				{
					message: __("{0} cannot be in the future.", [label]),
					indicator: "orange",
				},
				6
			);
		}
	} catch (e) {
		// ignore
	}
}

/**
 * **Cheque direction change** = semantic mode switch: normalize **party_type**, clear **party**, reset
 * stale GL links, then apply PDC Settings + RPC defaults for the new mode.
 *
 * @returns {Promise|void} Resolves when async settings/account application finishes (if any).
 */
function pdc_on_cheque_direction_changed(frm, previous_direction) {
	if (previous_direction === frm.doc.cheque_direction) {
		return;
	}

	const cur = frm.doc.cheque_direction;

	frm.set_value("party", "");

	if (cur === "Payable") {
		frm.set_value("party_type", PDC_PAYABLE_DEFAULT_PARTY_TYPE);
		if (previous_direction === "Receivable" && frm.doc.drawer_bank_name) {
			frm.set_value("drawer_bank_name", "");
		}
		return pdc_apply_accounts_for_payable_direction(frm);
	}

	if (cur === "Receivable") {
		frm.set_value("party_type", PDC_RECEIVABLE_DEFAULT_PARTY_TYPE);
		return pdc_apply_accounts_for_receivable_direction(frm, { soft_initial_fill: false });
	}

	return Promise.resolve();
}

/**
 * **Payable:** pool on **account_paid_from**; clear party-facing side until party is chosen.
 * **Receivable:** **account_paid_to** (CIH), clearing + endorsement from settings; **account_paid_from** cleared until party.
 */
function pdc_apply_accounts_for_payable_direction(frm) {
	if (!frm.doc.company) {
		frm.set_value("account_paid_from", "");
		frm.set_value("account_paid_to", "");
		frm.set_value("cheques_in_clearing_account", "");
		frm.set_value("endorsement_settlement_account", "");
		pdc_refresh_account_like_fields(frm);
		return Promise.resolve();
	}
	frm.set_value("account_paid_to", "");
	frm.set_value("cheques_in_clearing_account", "");
	frm.set_value("endorsement_settlement_account", "");
	return pdc_resolve_pdc_settings_docname(frm.doc.company).then((docname) => {
		if (!docname) {
			frm.set_value("account_paid_from", "");
			pdc_refresh_account_like_fields(frm);
			set_default_party_accounts(frm);
			return;
		}
		return frappe.db.get_value("PDC Settings", docname, "default_payable_cheque_account").then((r) => {
			const pool = r && r.message && r.message.default_payable_cheque_account;
			frm.set_value("account_paid_from", pool || "");
			pdc_refresh_account_like_fields(frm);
			set_default_party_accounts(frm);
		});
	});
}

/**
 * @param {object} [opts]
 * @param {boolean} [opts.soft_initial_fill] If true (new-doc first paint): only set link fields when PDC Settings
 *   returns a value — never write `""`, so a slower/failed fetch does not wipe a later good value (fixes duplicate
 *   async). If false (direction / party_type change): clear stale links when setting is missing.
 */
function pdc_apply_accounts_for_receivable_direction(frm, opts) {
	const soft = opts && opts.soft_initial_fill;
	if (!frm.doc.company) {
		frm.set_value("account_paid_from", "");
		frm.set_value("account_paid_to", "");
		frm.set_value("cheques_in_clearing_account", "");
		frm.set_value("endorsement_settlement_account", "");
		pdc_refresh_account_like_fields(frm);
		return Promise.resolve();
	}
	return pdc_fetch_pdc_settings_receivable_accounts(frm.doc.company).then((m) => {
			m = m || {};
			pdc_trace("pdc_apply_accounts_for_receivable_direction resolved", { soft, keys: Object.keys(m), m });
			frm.set_value("account_paid_from", "");
			const setLink = (fieldname, key) => {
				const v = m[key];
				if (!v) {
					if (!soft) {
						frm.set_value(fieldname, "");
					}
					return;
				}
				if (soft && (frm.doc[fieldname] || "").trim()) {
					return;
				}
				frm.set_value(fieldname, v);
			};
			setLink("account_paid_to", "default_cheques_in_hand_account");
			setLink("cheques_in_clearing_account", "default_cheques_in_clearing_account");
			setLink("endorsement_settlement_account", "default_endorsement_account");
			pdc_refresh_account_like_fields(frm);
			set_default_party_accounts(frm);
		});
}

function pdc_fetch_pdc_settings_receivable_accounts(company) {
	return pdc_resolve_pdc_settings_docname(company).then((docname) => {
		if (!docname) {
			return {};
		}
		return frappe.db
			.get_value("PDC Settings", docname, [
				"default_cheques_in_hand_account",
				"default_cheques_in_clearing_account",
				"default_endorsement_account",
			])
			.then((r) => (r && r.message) || {});
	});
}

function pdc_refresh_account_like_fields(frm) {
	["account_paid_from", "account_paid_to", "cheques_in_clearing_account", "endorsement_settlement_account"].forEach(
		(fn) => {
			if (frm.fields_dict[fn]) {
				frm.refresh_field(fn);
			}
		}
	);
}

/**
 * After **party_type** change (same **cheque_direction**): **party** is already cleared; re-apply
 * direction-appropriate settings + RPC so GL fields match the new type and empty party.
 */
function pdc_reresolve_accounts_after_party_type_change(frm) {
	if (!frm.doc.cheque_direction) {
		return;
	}
	if (!frm.doc.company) {
		frm.set_value("account_paid_from", "");
		frm.set_value("account_paid_to", "");
		frm.set_value("cheques_in_clearing_account", "");
		frm.set_value("endorsement_settlement_account", "");
		pdc_refresh_account_like_fields(frm);
		return;
	}
	if (frm.doc.cheque_direction === "Payable") {
		pdc_apply_accounts_for_payable_direction(frm);
	} else if (frm.doc.cheque_direction === "Receivable") {
		pdc_apply_accounts_for_receivable_direction(frm, { soft_initial_fill: false });
	}
}

/**
 * Same reactive pattern as DocType **mandatory_depends_on** on **bank_account** / **drawer_bank_name**:
 * update docfield via **toggle_reqd** / **toggle_display** / **toggle_enable** / **set_df_property** /
 * **set_query**, which trigger **refresh_field** where applicable so stars and visibility update immediately.
 */
function pdc_apply_direction_dependent_ui(frm) {
	pdc_cache_meta_once(frm);
	pdc_apply_initial_party_type_for_new_doc(frm);
	pdc_apply_bank_account_ui(frm);
	pdc_apply_received_date_ui(frm);
	pdc_apply_receivable_only_fields_ui(frm);
	pdc_apply_cheque_leaf_ui(frm);
	pdc_apply_cheque_direction_lock_ui(frm);
	pdc_apply_payable_bank_account_lock_ui(frm);
	pdc_apply_sayad_code_ui(frm);
	pdc_apply_party_type_ui(frm);
	pdc_apply_account_fields_ui(frm);
	set_default_party_accounts(frm);
	/** Root-cause fix: company/session defaults often bind after first **refresh**; single **onload_post_render** was too early. */
	pdc_schedule_initial_receivable_accounts(frm);
	pdc_schedule_initial_payable_accounts(frm);
	frm.refresh_field("drawer_bank_name");
	frm.refresh_field("bank_account");
	frm.refresh_field("handover_date");
}

function pdc_receivable_sent_to_bank_or_later(doc) {
	if (!doc) return false;
	const ws = (doc.workflow_state || "").trim();
	const cheque_status = (doc.cheque_status || "").trim();

	const ws_locked = ["Sent to Bank", "In Clearing", "Cleared", "Bounced", "Returned", "Cancelled", "Replaced"].includes(ws);
	const status_locked = ["In Clearing", "Cleared", "Bounced", "Returned"].includes(cheque_status);

	// Registered is NOT sent-to-bank-or-later from sent_to_bank_date alone (it may be prefilled early).
	const sent_to_bank_date_set = !!doc.sent_to_bank_date;
	const sent_to_bank_signal = sent_to_bank_date_set && ws !== "Registered";

	return ws_locked || status_locked || sent_to_bank_signal;
}

function pdc_apply_payable_bank_account_lock_ui(frm) {
	if (!frm || !frm.doc) return;
	if (pdc_is_new_unsaved(frm)) {
		return;
	}
	const dir = (frm.doc.cheque_direction || "").trim();
	const bank_account = (frm.doc.bank_account || "").trim();
	const ws = (frm.doc.workflow_state || "").trim();

	// Keep existing Payable rule unchanged.
	const payable_locked = dir === "Payable" && ws && ws !== "Draft";

	// Receivable: lock bank_account only after true sent-to-bank-or-later (not merely Registered).
	// IMPORTANT: if bank_account is still empty, keep it editable so user can set it (it becomes required).
	const receivable_locked = dir === "Receivable" && bank_account && pdc_receivable_sent_to_bank_or_later(frm.doc);

	if (payable_locked || receivable_locked) {
		frm.set_df_property("bank_account", "read_only", 1);
		frm.toggle_enable("bank_account", false);
		// cheque_leaf: lock only for Payable (Receivable is manual and leaf is hidden anyway).
		if (payable_locked) {
			frm.set_df_property("cheque_leaf", "read_only", 1);
			frm.toggle_enable("cheque_leaf", false);
		}
	} else {
		// Do not override receivable behavior here; only relax payable draft.
		if (dir === "Payable" && (ws || "Draft") === "Draft") {
			frm.set_df_property("bank_account", "read_only", 0);
			frm.toggle_enable("bank_account", true);
			// cheque_leaf enablement is controlled by pdc_apply_cheque_leaf_ui.
		}
		// Receivable: if not locked, keep bank_account editable (before sent-to-bank, or sent-to-bank but empty).
		if (dir === "Receivable") {
			frm.set_df_property("bank_account", "read_only", 0);
			frm.toggle_enable("bank_account", true);
		}
	}

	frm.refresh_field("bank_account");
	frm.refresh_field("cheque_leaf");
}

function pdc_apply_cheque_direction_lock_ui(frm) {
	if (!frm || !frm.doc) return;
	// New unsaved docs: editable
	if (pdc_is_new_unsaved(frm)) {
		frm.set_df_property("cheque_direction", "read_only", 0);
		frm.toggle_enable("cheque_direction", true);
		return;
	}

	const dir = (frm.doc.cheque_direction || "").trim();
	const docstatus = parseInt(frm.doc.docstatus, 10) || 0;

	let locked = false;
	if (dir === "Payable") {
		locked = true;
	} else if (dir === "Receivable") {
		locked = pdc_receivable_sent_to_bank_or_later(frm.doc);
	}

	// Only lock in draft/submitted contexts; if doc is cancelled, it is inherently non-editable.
	if (docstatus === 2) {
		locked = true;
	}

	frm.set_df_property("cheque_direction", "read_only", locked ? 1 : 0);
	frm.toggle_enable("cheque_direction", !locked);
	frm.refresh_field("cheque_direction");
}

function pdc_apply_cheque_leaf_ui(frm) {
	const payable = frm.doc.cheque_direction === "Payable";
	const has_company = !!(frm.doc.company || "").trim();
	const has_bank = !!(frm.doc.bank_account || "").trim();
	const leaf_editable = payable && has_company && has_bank && (frm.doc.docstatus || 0) === 0;

	// Force visibility/read-only state every time; avoids stale meta flags.
	if (!payable) {
		frm.set_df_property("cheque_leaf", "hidden", 1);
		frm.set_df_property("cheque_leaf", "read_only", 1);
		frm.toggle_enable("cheque_leaf", false);
		frm.set_df_property("cheque_leaf", "description", "");
	} else {
		frm.set_df_property("cheque_leaf", "hidden", 0);
		frm.set_df_property("cheque_leaf", "read_only", leaf_editable ? 0 : 1);
		frm.toggle_enable("cheque_leaf", !!leaf_editable);
		frm.set_df_property(
			"cheque_leaf",
			"description",
			leaf_editable ? "" : __("Select Bank Account first.")
		);
	}

	frm.set_query("cheque_leaf", function () {
		// Only allow leaf selection for Payable cheques, same company/bank, and Available leaves.
		if (!payable) {
			return { filters: { name: ["in", []] } };
		}
		const company = (frm.doc.company || "").trim();
		const bank_account = (frm.doc.bank_account || "").trim();
		if (!company || !bank_account) {
			return { filters: { name: ["in", []] } };
		}
		// Server-side query: dropdown **description** = cheque_number | status | bank_account | cheque_book (sorted by cheque_number).
		return {
			query:
				"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.pdc_cheque_leaf_link_query",
			filters: {
				company: company,
				bank_account: bank_account,
			},
		};
	});

	// Extra hard-enable in case widget kept disabled by stale state.
	const fld = frm.fields_dict.cheque_leaf;
	pdc_force_cheque_leaf_widget_state(frm, leaf_editable);

	frm.refresh_field("cheque_leaf");
	pdc_debug_cheque_leaf_state(frm, leaf_editable);
}

function pdc_apply_cheque_leaf_behaviour(frm) {
	if (!frm || !frm.doc) {
		return;
	}

	const payable = frm.doc.cheque_direction === "Payable";
	const has_company = !!(frm.doc.company || "").trim();
	const has_bank = !!(frm.doc.bank_account || "").trim();
	const leaf = (frm.doc.cheque_leaf || "").trim();

	// Guard: receivable PDCs must not use cheque leaf.
	if (!payable) {
		pdc_cleanup_cheque_leaf_when_not_payable(frm);
		frm.set_df_property("cheque_no", "read_only", 0);
		frm.refresh_field("cheque_no");
		return;
	}
	if (payable && (!has_company || !has_bank) && leaf) {
		frm.set_value("cheque_leaf", "");
		return;
	}

	// Toggle Cheque Number editability based on leaf selection.
	frm.set_df_property("cheque_no", "read_only", leaf ? 1 : 0);
	frm.refresh_field("cheque_no");

	// If leaf is set, fetch cheque_number and sync cheque_no.
	if (leaf) {
		frappe.db.get_value("Cheque Leaf", leaf, ["cheque_number", "sayad_number", "company", "bank_account", "status"]).then((r) => {
			const m = (r && r.message) || {};
			// If company/bank mismatch (or missing), clear leaf to avoid bad link.
			if (
				(m.company && frm.doc.company && m.company !== frm.doc.company) ||
				(m.bank_account && frm.doc.bank_account && m.bank_account !== frm.doc.bank_account)
			) {
				frm.set_value("cheque_leaf", "");
				return;
			}
			if (m.cheque_number && frm.doc.cheque_no !== m.cheque_number) {
				frm.set_value("cheque_no", m.cheque_number);
			}
			// Optional convenience: copy Sayad Number into PDC Sayad Code if present.
			if (Object.prototype.hasOwnProperty.call(frm.doc || {}, "sayad_code") && (m.sayad_number || "").trim()) {
				frm.set_value("sayad_code", m.sayad_number);
			}
		});
		return;
	}

	// Leaf cleared: cheque_no becomes user-editable again (no further action).
}

function pdc_cleanup_cheque_leaf_when_not_payable(frm) {
	if (!frm || !frm.doc) return;
	const payable = frm.doc.cheque_direction === "Payable";
	if (payable) return;

	const leaf = (frm.doc.cheque_leaf || "").trim();
	if (!leaf) {
		frm.set_df_property("cheque_no", "read_only", 0);
		return;
	}
	const current_no = (frm.doc.cheque_no || "").trim();
	frappe.db.get_value("Cheque Leaf", leaf, "cheque_number").then((r) => {
		const leaf_no = (((r || {}).message || {}).cheque_number || "").trim();
		frm.set_value("cheque_leaf", "");
		if (!current_no || !leaf_no || current_no === leaf_no) {
			frm.set_value("cheque_no", "");
		}
		frm.set_df_property("cheque_no", "read_only", 0);
		frm.refresh_field("cheque_leaf");
		frm.refresh_field("cheque_no");
	});
}

function pdc_sync_holder_to_party_for_direction(frm, prev_direction, new_direction) {
	if (!frm || !frm.doc) return;
	const prev = (prev_direction || "").trim();
	const cur = (new_direction || frm.doc.cheque_direction || "").trim();
	if (prev === cur) return;

	// When switching Payable -> Receivable, holder should not keep old payee values.
	if (cur === "Receivable") {
		const pt = (frm.doc.party_type || "").trim();
		const p = (frm.doc.party || "").trim();
		if (pt && p) {
			frm.set_value("holder_party_type", pt);
			frm.set_value("holder_party", p);
		} else {
			frm.set_value("holder_party_type", "");
			frm.set_value("holder_party", "");
		}
	}
}

function pdc_handle_bank_account_change_for_cheque_leaf(frm) {
	if (!frm || !frm.doc || frm.doc.cheque_direction !== "Payable") {
		frm._pdc_prev_bank_account = (frm && frm.doc && frm.doc.bank_account ? frm.doc.bank_account : "").trim();
		return;
	}
	const prev_bank = (frm._pdc_prev_bank_account || "").trim();
	const cur_bank = (frm.doc.bank_account || "").trim();
	const leaf = (frm.doc.cheque_leaf || "").trim();

	if (!prev_bank) {
		frm._pdc_prev_bank_account = cur_bank;
		return;
	}
	if (prev_bank === cur_bank) {
		return;
	}

	if (leaf) {
		frappe.db.get_value("Cheque Leaf", leaf, "cheque_number").then((r) => {
			const old_leaf_number = (((r || {}).message || {}).cheque_number || "").trim();
			if (old_leaf_number && (frm.doc.cheque_no || "").trim() === old_leaf_number) {
				frm.set_value("cheque_no", "");
			}
			frm.set_value("cheque_leaf", "");
		});
	} else if (!cur_bank) {
		// No selected leaf and bank cleared: keep cheque number manual/editable.
	}

	frm._pdc_prev_bank_account = cur_bank;
}

function pdc_force_cheque_leaf_widget_state(frm, leaf_editable) {
	const fld = frm && frm.fields_dict ? frm.fields_dict.cheque_leaf : null;
	if (!fld) return;
	const wrapper = fld.$wrapper;
	if (wrapper) {
		wrapper.toggleClass("disabled", !leaf_editable);
		wrapper.find("input, .awesomplete input, textarea").prop("disabled", !leaf_editable);
	}
	if (fld.$input) {
		fld.$input.prop("disabled", !leaf_editable);
	}
}

function pdc_schedule_cheque_leaf_ui_enforcement(frm) {
	frappe.after_ajax(() => {
		[100, 500].forEach((ms) => {
			setTimeout(() => {
				if (!frm || !frm.doc) return;
				pdc_apply_cheque_leaf_ui(frm);
				const payable = frm.doc.cheque_direction === "Payable";
				const has_company = !!(frm.doc.company || "").trim();
				const has_bank = !!(frm.doc.bank_account || "").trim();
				const leaf_editable = payable && has_company && has_bank && (frm.doc.docstatus || 0) === 0;
				pdc_force_cheque_leaf_widget_state(frm, leaf_editable);
				pdc_debug_cheque_leaf_state(frm, leaf_editable);
			}, ms);
		});
	});
}

function pdc_debug_cheque_leaf_state(frm, should_be_editable) {
	try {
		const fld = frm && frm.fields_dict ? frm.fields_dict.cheque_leaf : null;
		const df = frm && frm.get_docfield ? frm.get_docfield("cheque_leaf") : null;
		const inputDisabled =
			!!(fld && fld.$wrapper && fld.$wrapper.find("input:disabled, .awesomplete input:disabled").length);
		if (should_be_editable && (df && df.read_only || inputDisabled)) {
			// temporary runtime diagnostic
			// eslint-disable-next-line no-console
			console.warn("[PDC cheque_leaf disabled unexpectedly]", {
				cheque_direction: frm.doc.cheque_direction,
				company: frm.doc.company,
				bank_account: frm.doc.bank_account,
				docstatus: frm.doc.docstatus,
				df_read_only: df ? df.read_only : undefined,
				input_disabled: inputDisabled,
			});
			frappe.show_alert(
				{
					message: __(
						"Debug: cheque_leaf remained disabled unexpectedly. Check console for state payload."
					),
					indicator: "orange",
				},
				5
			);
		}
	} catch (e) {
		// ignore diagnostics failures
	}
}

/**
 * Retries soft receivable account fill: **company** may be unset on first **refresh** then filled by session default
 * a few ms later; **PDC Settings** row must be loaded by resolved docname (see **pdc_resolve_pdc_settings_docname**).
 */
function pdc_schedule_initial_receivable_accounts(frm) {
	if (!pdc_is_new_unsaved(frm) || frm.doc.cheque_direction !== "Receivable") {
		return;
	}
	const delays = [0, 50, 200];
	const tick = (ms) => {
		pdc_trace("pdc_schedule_initial_receivable_accounts tick", ms, {
			company: frm.doc && frm.doc.company,
			__islocal: frm.doc && frm.doc.__islocal,
		});
		if (!frm.doc || frm.doc.cheque_direction !== "Receivable" || !pdc_is_new_unsaved(frm)) {
			return;
		}
		if (!frm.doc.company) {
			return;
		}
		pdc_apply_accounts_for_receivable_direction(frm, { soft_initial_fill: true });
	};
	frappe.after_ajax(() => {
		delays.forEach((ms) => setTimeout(() => tick(ms), ms));
	});
}

/**
 * Payable pool (**account_paid_from**) is loaded via ``pdc_apply_accounts_for_payable_direction`` — same timing issue as
 * receivable CIH: direction/party_type change runs it, but first paint from **new_doc** prefills did not — schedule retries.
 */
function pdc_schedule_initial_payable_accounts(frm) {
	if (!pdc_is_new_unsaved(frm) || frm.doc.cheque_direction !== "Payable") {
		return;
	}
	const delays = [0, 50, 200];
	const tick = () => {
		if (!frm.doc || frm.doc.cheque_direction !== "Payable" || !pdc_is_new_unsaved(frm)) {
			return;
		}
		if (!frm.doc.company) {
			return;
		}
		pdc_apply_accounts_for_payable_direction(frm);
	};
	frappe.after_ajax(() => {
		delays.forEach((ms) => setTimeout(() => tick(), ms));
	});
}

/** New unsaved docs only: default **party_type** if still unset (does not run on every open of saved docs). */
function pdc_apply_initial_party_type_for_new_doc(frm) {
	if (!frm.is_new()) {
		return;
	}
	const pt = (frm.doc.party_type || "").trim();
	if (pt) {
		return;
	}
	frm._pdc_suppress_party_type_account_reresolve = true;
	try {
		if (frm.doc.cheque_direction === "Payable") {
			frm.set_value("party_type", PDC_PAYABLE_DEFAULT_PARTY_TYPE);
		} else if (frm.doc.cheque_direction === "Receivable") {
			frm.set_value("party_type", PDC_RECEIVABLE_DEFAULT_PARTY_TYPE);
		}
	} finally {
		frm._pdc_suppress_party_type_account_reresolve = false;
	}
}

/**
 * When **party_type** changes, drop **party** so Dynamic Link cannot show a stale name from the prior type.
 */
function pdc_clear_party_on_party_type_change(frm) {
	if (frm.doc.party) {
		frm.set_value("party", "");
	}
	frm.refresh_field("party");
}

/**
 * DocField for a parent form field — use **frm.get_docfield** / **frappe.meta.get_docfield**, not **frm.meta.get_field**
 * (that API does not exist on Frappe Form **meta** and throws at runtime).
 */
function pdc_get_parent_docfield(frm, fieldname) {
	if (!frm || !fieldname) {
		return null;
	}
	try {
		if (typeof frm.get_docfield === "function") {
			return frm.get_docfield(fieldname);
		}
		if (frappe.meta && typeof frappe.meta.get_docfield === "function" && frm.doctype) {
			return frappe.meta.get_docfield(frm.doctype, fieldname, frm.docname);
		}
	} catch (e) {
		if (window.PDC_DEBUG_RECEIVABLE_INIT) {
			console.warn("[PDC] pdc_get_parent_docfield", fieldname, e);
		}
	}
	return null;
}

function pdc_cache_meta_once(frm) {
	if (_pdc_meta.bank_account_description !== null) {
		return;
	}
	try {
		const b = pdc_get_parent_docfield(frm, "bank_account");
		const af = pdc_get_parent_docfield(frm, "account_paid_from");
		const at = pdc_get_parent_docfield(frm, "account_paid_to");
		const pt = pdc_get_parent_docfield(frm, "party_type");
		_pdc_meta.bank_account_description = (b && b.description) || "";
		_pdc_meta.account_paid_from_description = (af && af.description) || "";
		_pdc_meta.account_paid_to_description = (at && at.description) || "";
		_pdc_meta.party_type_description = (pt && pt.description) || "";
	} catch (e) {
		if (window.PDC_DEBUG_RECEIVABLE_INIT) {
			console.warn("[PDC] pdc_cache_meta_once", e);
		}
		_pdc_meta.bank_account_description = "";
		_pdc_meta.account_paid_from_description = "";
		_pdc_meta.account_paid_to_description = "";
		_pdc_meta.party_type_description = "";
	}
}

function pdc_apply_bank_account_ui(frm) {
	frm.set_query("bank_account", function () {
		const direction = frm.doc.cheque_direction;
		if (direction === "Receivable" || direction === "Payable") {
			const company = frm.doc.company;
			if (!company) {
				return { filters: { name: ["in", []] } };
			}
			return {
				filters: {
					is_company_account: 1,
					company: company,
				},
			};
		}
		return {};
	});
	const is_receivable = frm.doc.cheque_direction === "Receivable";
	frm.set_df_property(
		"bank_account",
		"description",
		is_receivable ? "Only company bank accounts are allowed" : _pdc_meta.bank_account_description
	);
}

function pdc_apply_received_date_ui(frm) {
	frm.set_df_property("received_date", "label", "Received / Issued Date");
	const payable = frm.doc.cheque_direction === "Payable";
	frm.set_df_property(
		"received_date",
		"description",
		payable
			? "Payable: preparation (recorded / issued internally). Physical handover: Handover / Endorsement Date."
			: "Receivable: intake (received by company)."
	);
	frm.refresh_field("received_date");
}

function pdc_apply_receivable_only_fields_ui(frm) {
	const show = frm.doc.cheque_direction === "Receivable";
	frm.toggle_display(["cheques_in_clearing_account", "endorsement_settlement_account"], show);
	if (!show) {
		frm.toggle_enable(["cheques_in_clearing_account", "endorsement_settlement_account"], false);
	} else {
		frm.toggle_enable(["cheques_in_clearing_account", "endorsement_settlement_account"], true);
	}
}

function pdc_apply_sayad_code_ui(frm) {
	const company = frm.doc.company;
	if (!company) {
		frm.toggle_reqd("sayad_code", false);
		return;
	}
	frappe.db.get_value("PDC Settings", { company: company }, "require_sayad_registration").then((r) => {
		const v = !!(r && r.message && r.message.require_sayad_registration);
		frm.toggle_reqd("sayad_code", v);
	});
}

function pdc_apply_party_type_ui(frm) {
	const payable = frm.doc.cheque_direction === "Payable";
	frm.set_df_property(
		"party_type",
		"description",
		payable
			? "Payable (Paid To): mode default is Supplier; you may change to Employee or Shareholder. " +
					(_pdc_meta.party_type_description || "")
			: "Receivable (Received From): mode default is Customer; you may change to Employee or Shareholder. " +
					(_pdc_meta.party_type_description || "")
	);
	frm.refresh_field("party_type");
}

function pdc_apply_account_fields_ui(frm) {
	const payable = frm.doc.cheque_direction === "Payable";
	const rec = frm.doc.cheque_direction === "Receivable";

	frm.set_df_property(
		"account_paid_from",
		"description",
		payable
			? "Payable: typically the notes-payable / cheque pool account from PDC Settings when empty."
			: "Receivable: party receivable (e.g. customer AR). " + (_pdc_meta.account_paid_from_description || "")
	);
	frm.set_df_property(
		"account_paid_to",
		"description",
		rec
			? "Receivable: Cheques in Hand (from PDC Settings) or as defaulted. " +
					(_pdc_meta.account_paid_to_description || "")
			: "Payable: party payable (e.g. supplier AP). " + (_pdc_meta.account_paid_to_description || "")
	);

	const company = frm.doc.company;
	const account_filters = company
		? { company: company, is_group: 0, disabled: 0 }
		: { name: ["in", []] };

	frm.set_query("account_paid_from", function () {
		return { filters: account_filters };
	});
	frm.set_query("account_paid_to", function () {
		return { filters: account_filters };
	});

	frm.refresh_field("account_paid_from");
	frm.refresh_field("account_paid_to");
}

function set_default_party_accounts(frm) {
	if (!frm.doc.company || !frm.doc.cheque_direction) {
		return;
	}
	frappe.call({
		method: "erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque.get_default_party_accounts",
		args: {
			party_type: frm.doc.party_type || "",
			party: frm.doc.party || "",
			company: frm.doc.company,
			cheque_direction: frm.doc.cheque_direction,
		},
		callback: function (r) {
			if (!r.message || r.exc) {
				return;
			}
			if (r.message.account_paid_from && !frm.doc.account_paid_from) {
				frm.set_value("account_paid_from", r.message.account_paid_from);
			}
			if (r.message.account_paid_to && !frm.doc.account_paid_to) {
				frm.set_value("account_paid_to", r.message.account_paid_to);
			}
		},
	});
}
