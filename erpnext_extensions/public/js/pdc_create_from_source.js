// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// Create Post Dated Cheque from Sales Invoice / Purchase Invoice / Payment Request (Step 4).

frappe.provide("erpnext_extensions.cheque_management");

/** Label when the action sits under the standard **Create** menu (avoid redundant “Create …”). */
const PDC_CREATE_MENU_LABEL = __("Post Dated Cheque");
/** Legacy / top-level label (kept for ``remove_custom_button`` on older sessions). */
const PDC_CREATE_FROM_SOURCE_LABEL_LEGACY = __("Create Post Dated Cheque");
/** Same group as ERPNext ``add_custom_button(..., __("Create"))`` — Sales / Purchase Invoice **Create** menu. */
const PDC_CREATE_FROM_SOURCE_GROUP = __("Create");

erpnext_extensions.cheque_management.open_pdc_from_form = function (frm) {
	if (!frm || !frm.doc || frm.doc.__islocal || !frm.doc.name) {
		return;
	}
	frappe.call({
		method: "erpnext_extensions.cheque_management.pdc_create_from_source.prepare_post_dated_cheque_from_source",
		args: {
			source_doctype: frm.doctype,
			source_name: frm.doc.name,
		},
		freeze: true,
		freeze_message: __("Preparing Post Dated Cheque"),
		callback: (r) => {
			const payload = r.message || {};
			if (!payload.can_create) {
				frappe.msgprint({
					title: __("Cannot create Post Dated Cheque"),
					message: payload.message || __("Not available."),
					indicator: "orange",
				});
				return;
			}
			// Ensure meta is loaded so new child fieldnames (amount/allocation_mode) are applied.
			frappe.model.with_doctype("Post Dated Cheque", () => {
				frappe.model.with_doctype("PDC Allocation", () => {
					frappe.new_doc("Post Dated Cheque", payload.prefill);
				});
			});
		},
	});
};

/** SI / PI only — Payment Request actions are wired in ``pdc_settlement_summary.js`` after capacity is known. */
const PDC_CREATE_SOURCE_DOCTYPES = ["Sales Invoice", "Purchase Invoice"];

/** Same epsilon as ``pdc_settlement_summary.js`` / server capacity checks. */
const PDC_SI_PI_CAPACITY_EPS = 1e-6;

/**
 * Add **Create → Post Dated Cheque** only when settlement capacity may exist (re-run after async summary).
 */
erpnext_extensions.cheque_management.ensure_si_pi_pdc_create_button = function (frm) {
	if (!frm || (frm.doctype !== "Sales Invoice" && frm.doctype !== "Purchase Invoice")) {
		return;
	}
	frm.remove_custom_button(PDC_CREATE_MENU_LABEL, PDC_CREATE_FROM_SOURCE_GROUP);
	frm.remove_custom_button(PDC_CREATE_FROM_SOURCE_LABEL_LEGACY, PDC_CREATE_FROM_SOURCE_GROUP);
	frm.remove_custom_button(PDC_CREATE_MENU_LABEL);
	frm.remove_custom_button(PDC_CREATE_FROM_SOURCE_LABEL_LEGACY);

	if (frm.is_new() || !frm.doc || !frm.doc.name) {
		return;
	}
	// Desk builds vary; `frappe.utils.cint` is not always present.
	if ((parseInt(frm.doc.docstatus, 10) || 0) !== 1) {
		return;
	}
	if (
		frm._pdc_settlement_ready &&
		(parseFloat(
			frm._pdc_settlement_summary && frm._pdc_settlement_summary.remaining_balance
		) || 0) <= PDC_SI_PI_CAPACITY_EPS
	) {
		return;
	}
	frm.add_custom_button(
		PDC_CREATE_MENU_LABEL,
		() => erpnext_extensions.cheque_management.open_pdc_from_form(frm),
		PDC_CREATE_FROM_SOURCE_GROUP
	);
};

PDC_CREATE_SOURCE_DOCTYPES.forEach((dt) => {
	frappe.ui.form.on(dt, {
		refresh(frm) {
			// Defer: never interfere with ERPNext's own Create menu build.
			setTimeout(
				() => erpnext_extensions.cheque_management.ensure_si_pi_pdc_create_button(frm),
				0
			);
		},
	});
});
