// Copyright (c) 2026, Farbod Siyahpoosh and contributors
frappe.query_reports["Voucher GL Print"] = {
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
			fieldname: "voucher_type",
			label: __("Voucher Type"),
			fieldtype: "Link",
			options: "DocType",
			reqd: 1,
		},
		{
			fieldname: "voucher_no",
			label: __("Voucher Number"),
			fieldtype: "Data",
			reqd: 1,
		},
		{
			fieldname: "finance_book",
			label: __("Finance Book"),
			fieldtype: "Link",
			options: "Finance Book",
		},
		{
			fieldname: "include_opening_entries",
			label: __("Include Opening Entries"),
			fieldtype: "Check",
			default: 1,
		},
		{
			fieldname: "include_cancelled_entries",
			label: __("Include Cancelled Entries"),
			fieldtype: "Check",
			default: 0,
		},
	],
	onload(report) {
		// Account Explorer one-click sets voucher filters via route_options —
		// hide intermediate editing when already locked.
		const locked = frappe.route_options || {};
		if (locked.voucher_type && locked.voucher_no) {
			["voucher_type", "voucher_no", "company"].forEach((field) => {
				const input = report.get_filter(field);
				if (input) {
					input.df.read_only = 1;
					input.refresh();
				}
			});
		}
		if (cint(locked.auto_print)) {
			report.page.add_inner_message(__("Preparing voucher GL print…"));
			frappe.after_ajax(() => {
				setTimeout(() => {
					report.print_report({
						orientation: report.message?.orientation || "Portrait",
						with_letter_head: 1,
					});
				}, 400);
			});
		}
	},
	get_datatable_options(options) {
		return Object.assign({}, options, {
			checkboxColumn: false,
		});
	},
};
