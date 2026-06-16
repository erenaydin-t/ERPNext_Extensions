// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.query_reports["PM Opening Advance Availability Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "employee",
			label: __("Employee"),
			fieldtype: "Link",
			options: "Employee",
		},
		{
			fieldname: "holder",
			label: __("PM Holder"),
			fieldtype: "Link",
			options: "PM Holder",
		},
		{
			fieldname: "only_available",
			label: __("Only With Available Balance"),
			fieldtype: "Check",
		},
	],
};
