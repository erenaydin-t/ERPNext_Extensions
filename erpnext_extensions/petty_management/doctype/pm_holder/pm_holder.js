// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Holder", {
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh balances"), () => {
				frm.reload_doc();
			});
		}
	},
});
