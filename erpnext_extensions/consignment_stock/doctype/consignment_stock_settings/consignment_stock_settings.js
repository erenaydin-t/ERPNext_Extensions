# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

frappe.ui.form.on("Consignment Stock Settings", {
	setup(frm) {
		frm.set_query("consignment_inventory_account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				disabled: 0,
			},
		}));
		frm.set_query("consignment_temporary_clearing_account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				disabled: 0,
			},
		}));
		frm.set_query("consignment_valuation_difference_account", () => ({
			filters: {
				company: frm.doc.company,
				is_group: 0,
				disabled: 0,
			},
		}));
		frm.set_query("default_cost_center", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
		frm.set_query("default_consignment_warehouse", () => ({
			filters: { company: frm.doc.company, is_group: 0 },
		}));
	},
});
