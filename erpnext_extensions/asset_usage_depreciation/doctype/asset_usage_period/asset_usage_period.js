# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

frappe.ui.form.on("Asset Usage Period", {
	depreciation_mode(frm) {
		if (frm.doc.depreciation_mode !== "Percentage") {
			frm.set_value("depreciation_percentage", null);
		}
	},
	depreciation_percentage(frm) {
		if (flt(frm.doc.depreciation_percentage) === 100) {
			frm.set_value("depreciation_mode", "Normal");
			frm.set_value("depreciation_percentage", null);
			frappe.show_alert({
				message: __("100% was normalized to Normal mode."),
				indicator: "blue",
			});
		}
	},
});
