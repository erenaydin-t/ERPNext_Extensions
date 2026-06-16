frappe.query_reports["Facility Ledger"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
			reqd: 1,
			default: frappe.defaults.get_user_default("Company"),
		},
		{
			fieldname: "facility",
			label: __("Facility"),
			fieldtype: "Link",
			options: "Facility",
		},
		{
			fieldname: "facility_name",
			label: __("Facility Name"),
			fieldtype: "Data",
		},
		{
			fieldname: "facility_type",
			label: __("Facility Type"),
			fieldtype: "Link",
			options: "Facility Type",
		},
		{
			fieldname: "from_date",
			label: __("From Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_date",
			label: __("To Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
		},
	],
};
