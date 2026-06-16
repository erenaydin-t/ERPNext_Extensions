// Copyright (c) 2026, ERPNext Extensions contributors

frappe.provide("erpnext_extensions.facility_management.dimension_queries");

erpnext_extensions.facility_management.dimension_queries.setup = function (frm, field_map) {
	const company = () => frm.doc.company;
	field_map = field_map || {
		department: "department",
		bank_dimension: "bank_dimension",
		bank_account_dimension: "bank_account_dimension",
	};

	if (field_map.department) {
		frm.set_query(field_map.department, () => {
			const c = company();
			const filters = { disabled: 0, is_group: 0 };
			if (c) {
				filters.company = c;
			}
			return { filters };
		});
	}

	if (field_map.bank_account_dimension) {
		frm.set_query(field_map.bank_account_dimension, () => {
			const c = company();
			const filters = { disabled: 0 };
			if (c) {
				filters.company = c;
			}
			return { filters };
		});
	}
};

frappe.ui.form.on("Facility Settings", {
	refresh(frm) {
		erpnext_extensions.facility_management.dimension_queries.setup(frm, {
			department: "default_department",
			bank_dimension: "default_bank_dimension",
			bank_account_dimension: "default_bank_account_dimension",
		});
	},
});
