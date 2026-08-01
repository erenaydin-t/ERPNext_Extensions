// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.ui.form.on("Stock Entry Type", {
	purpose(frm) {
		if (frm.doc.purpose !== "Material Receipt") {
			frm.set_value("custom_is_consignment_receipt", 0);
		}
		if (frm.doc.purpose !== "Material Issue") {
			frm.set_value("custom_is_consignment_return", 0);
		}
	},
	custom_is_consignment_receipt(frm) {
		if (frm.doc.custom_is_consignment_receipt) {
			frm.set_value("custom_is_consignment_return", 0);
		}
	},
	custom_is_consignment_return(frm) {
		if (frm.doc.custom_is_consignment_return) {
			frm.set_value("custom_is_consignment_receipt", 0);
		}
	},
});
