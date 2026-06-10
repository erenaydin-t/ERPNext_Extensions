// Copyright (c) 2026, ERPNext Extensions contributors

frappe.ui.form.on("Facility", {
	refresh(frm) {
		if (frm.is_new() || frm.doc.status === "Closed") {
			return;
		}
		if (!cint(frm.doc.is_opening_facility) && !frm.doc.receipt_journal_entry) {
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

function cint(v) {
	return parseInt(v, 10) || 0;
}
