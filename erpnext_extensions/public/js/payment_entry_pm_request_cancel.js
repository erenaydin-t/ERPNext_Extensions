// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt
//
// v4.6.7 — Desk Cancel must not treat PM Request as a cancel-all linked doc.
// Server-side PE cancel already recalculates funding without cancelling the Request.
// Append only; never replace ERPNext's ignore_doctypes_on_cancel_all list.

frappe.provide("erpnext_extensions.petty_management");

erpnext_extensions.petty_management.ensure_pe_ignore_pm_request_on_cancel = function (frm) {
	if (!frm) {
		return;
	}
	frm.ignore_doctypes_on_cancel_all = frm.ignore_doctypes_on_cancel_all || [];
	if (!frm.ignore_doctypes_on_cancel_all.includes("PM Request")) {
		frm.ignore_doctypes_on_cancel_all.push("PM Request");
	}
};

frappe.ui.form.on("Payment Entry", {
	onload(frm) {
		erpnext_extensions.petty_management.ensure_pe_ignore_pm_request_on_cancel(frm);
	},
	refresh(frm) {
		// refresh: ERPNext onload may run after app hooks; keep list additive.
		erpnext_extensions.petty_management.ensure_pe_ignore_pm_request_on_cancel(frm);
	},
});
