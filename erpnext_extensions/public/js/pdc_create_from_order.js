// Copyright (c) 2026
// Create Advance Mode Post Dated Cheque from Purchase Order / Sales Order (Task 4).

frappe.provide("erpnext_extensions.cheque_management");

const PDC_CREATE_MENU_LABEL = __("Post Dated Cheque");
const PDC_CREATE_FROM_ORDER_GROUP = __("Create");
const PDC_ORDER_DOCTYPES = ["Purchase Order", "Sales Order"];

erpnext_extensions.cheque_management.open_advance_pdc_from_order_form = function (frm) {
	if (!frm || !frm.doc || frm.doc.__islocal || !frm.doc.name) {
		return;
	}
	frappe.call({
		method: "erpnext_extensions.cheque_management.pdc_create_from_source.prepare_post_dated_cheque_from_order",
		args: {
			order_doctype: frm.doctype,
			order_name: frm.doc.name,
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
			frappe.model.with_doctype("Post Dated Cheque", () => {
				frappe.model.with_doctype("PDC Allocation", () => {
					frappe.new_doc("Post Dated Cheque", payload.prefill);
				});
			});
		},
	});
};

function ensure_po_so_pdc_create_button(frm) {
	if (!frm || (frm.doctype !== "Purchase Order" && frm.doctype !== "Sales Order")) {
		return;
	}
	frm.remove_custom_button(PDC_CREATE_MENU_LABEL, PDC_CREATE_FROM_ORDER_GROUP);
	frm.remove_custom_button(PDC_CREATE_MENU_LABEL);
	if (frm.is_new() || !frm.doc || !frm.doc.name) {
		return;
	}
	if ((parseInt(frm.doc.docstatus, 10) || 0) !== 1) {
		return;
	}
	frm.add_custom_button(
		PDC_CREATE_MENU_LABEL,
		() => erpnext_extensions.cheque_management.open_advance_pdc_from_order_form(frm),
		PDC_CREATE_FROM_ORDER_GROUP
	);
}

PDC_ORDER_DOCTYPES.forEach((dt) => {
	frappe.ui.form.on(dt, {
		refresh(frm) {
			setTimeout(() => ensure_po_so_pdc_create_button(frm), 0);
		},
	});
});

