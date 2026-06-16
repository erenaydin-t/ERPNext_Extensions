// Copyright (c) 2026, ERPNext Extensions contributors

frappe.provide("erpnext_extensions.facility_management.dimension_queries");

frappe.ui.form.on("Facility", {
	refresh(frm) {
		erpnext_extensions.facility_management.dimension_queries.setup?.(frm);
		if (frm.is_new() || frm.doc.status === "Closed") {
			return;
		}
		if (can_preview_or_create_receipt(frm)) {
			frm.add_custom_button(__("Preview Receipt Journal Entry"), () => preview_receipt_je(frm));
			frm.add_custom_button(__("Create Receipt Journal Entry"), () => {
				frappe.call({
					method:
						"erpnext_extensions.facility_management.doctype.facility.facility.create_receipt_journal_entry",
					args: { name: frm.doc.name },
					freeze: true,
					callback() {
						frm.reload_doc();
					},
				});
			});
		}
		if (frm.doc.status === "Active") {
			frm.add_custom_button(__("Close Facility"), () => {
				frappe.call({
					method: "erpnext_extensions.facility_management.doctype.facility.facility.close_facility",
					args: { name: frm.doc.name },
					freeze: true,
					callback() {
						frm.reload_doc();
					},
				});
			});
		}
	},
});

function can_preview_or_create_receipt(frm) {
	return (
		!cint(frm.doc.is_opening_facility) &&
		!frm.doc.receipt_journal_entry &&
		flt(frm.doc.principal_amount) > 0 &&
		!!frm.doc.company
	);
}

function preview_receipt_je(frm) {
	frappe.call({
		method:
			"erpnext_extensions.facility_management.doctype.facility.facility.preview_receipt_journal_entry",
		args: { name: frm.doc.name },
		freeze: true,
		callback(r) {
			erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog(
				r.message,
				__("Receipt Journal Entry Preview")
			);
		},
	});
}

function cint(v) {
	return parseInt(v, 10) || 0;
}
