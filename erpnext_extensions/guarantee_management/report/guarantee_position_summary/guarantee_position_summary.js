// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.query_reports["Guarantee Position Summary"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "as_on_date",
			label: __("As On Date"),
			fieldtype: "Date",
			default: frappe.datetime.get_today(),
			reqd: 1,
		},
		{
			fieldname: "status",
			label: __("Status"),
			fieldtype: "Select",
			options: "\nDraft\nActive\nReturned\nReleased\nCancelled\nExpired\nLost",
		},
		{
			fieldname: "guarantee_direction",
			label: __("Direction"),
			fieldtype: "Select",
			options: "\nReceived\nIssued",
		},
		{
			fieldname: "held_by",
			label: __("Held By"),
			fieldtype: "Select",
			options: "\nHeld by Us\nHeld by Others\n—",
		},
		{
			fieldname: "party_type",
			label: __("Party Type"),
			fieldtype: "Select",
			options: "\nCustomer\nSupplier\nEmployee\nShareholder\nBank\nOther",
		},
		{
			fieldname: "party",
			label: __("Party"),
			fieldtype: "Dynamic Link",
			get_options() {
				return frappe.query_report.get_filter_value("party_type") || "";
			},
		},
		{
			fieldname: "guarantee_type",
			label: __("Guarantee Type"),
			fieldtype: "Select",
			options: "\nCheque\nPromissory Note\nBank Guarantee\nContract Guarantee\nOther",
		},
		{
			fieldname: "issuing_bank",
			label: __("Issuing Bank"),
			fieldtype: "Link",
			options: "Bank",
		},
		{
			fieldname: "currency",
			label: __("Currency"),
			fieldtype: "Link",
			options: "Currency",
		},
		{
			fieldname: "from_expiry_date",
			label: __("From Expiry Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_expiry_date",
			label: __("To Expiry Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "expiry_bucket",
			label: __("Expiry Bucket"),
			fieldtype: "Select",
			options:
				"\nActive but Expired\nDue 0–7 Days\nDue 8–30 Days\nDue 31–60 Days\nDue 61–90 Days\nDue 90+ Days\nNo Expiry Date",
		},
	],
};
