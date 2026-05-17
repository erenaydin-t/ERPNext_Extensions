// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.query_reports["PM Pending Clearance Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			default: frappe.defaults.get_user_default("Company"),
		},
	],
};
