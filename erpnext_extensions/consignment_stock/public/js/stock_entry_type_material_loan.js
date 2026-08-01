// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.ui.form.on("Stock Entry Type", {
	purpose(frm) {
		if (frm.doc.purpose !== "Material Issue") {
			frm.set_value("custom_is_material_loan_issue", 0);
		}
		if (frm.doc.purpose !== "Material Receipt") {
			frm.set_value("custom_is_material_loan_return", 0);
		}
	},
	custom_is_material_loan_issue(frm) {
		if (cint(frm.doc.custom_is_material_loan_issue)) {
			frm.set_value("custom_is_material_loan_return", 0);
			frm.set_value("custom_is_consignment_receipt", 0);
			frm.set_value("custom_is_consignment_return", 0);
		}
	},
	custom_is_material_loan_return(frm) {
		if (cint(frm.doc.custom_is_material_loan_return)) {
			frm.set_value("custom_is_material_loan_issue", 0);
			frm.set_value("custom_is_consignment_receipt", 0);
			frm.set_value("custom_is_consignment_return", 0);
		}
	},
});
