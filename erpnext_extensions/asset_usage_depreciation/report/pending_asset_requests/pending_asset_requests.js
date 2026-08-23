// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.query_reports["Pending Asset Requests"] = {
	filters: [
		{ fieldname: "company", label: __("Company"), fieldtype: "Link", options: "Company", default: frappe.defaults.get_user_default("Company") },
		{ fieldname: "employee", label: __("Employee"), fieldtype: "Link", options: "Employee" },
		{ fieldname: "cost_center", label: __("Cost Center"), fieldtype: "Link", options: "Cost Center" },
		{ fieldname: "project", label: __("Project"), fieldtype: "Link", options: "Project" },
	],
};

if (erpnext.utils && erpnext.utils.add_dimensions) {
	erpnext.utils.add_dimensions("Pending Asset Requests", 2);
}
