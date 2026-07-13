frappe.query_reports["Cheque Maturity Report"] = {
	filters: [
		{
			fieldname: "company",
			label: __("Company"),
			fieldtype: "Link",
			options: "Company",
		},
		{
			fieldname: "cheque_direction",
			label: __("Cheque Direction"),
			fieldtype: "Select",
			options: "\nReceivable\nPayable",
		},
		{
			fieldname: "from_due_date",
			label: __("From Due Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "to_due_date",
			label: __("To Due Date"),
			fieldtype: "Date",
		},
		{
			fieldname: "cheque_status",
			label: __("Cheque Status"),
			fieldtype: "Select",
			options:
				"\nDraft\nRegistered\nIn Hand\nIn Clearing\nCleared\nBounced\nEndorsed\nReturned to Customer\nReturned from Payee\nReplaced\nUnder Legal Action\nCancelled\nIssued",
		},
		{
			fieldname: "workflow_state",
			label: __("Workflow State"),
			fieldtype: "Link",
			options: "Workflow State",
		},
		{ fieldname: "break_maturity", fieldtype: "Break" },
		{
			fieldname: "days_to_due_exact",
			label: __("Days To Due"),
			fieldtype: "Int",
		},
		{
			fieldname: "overdue_only",
			label: __("Overdue Only"),
			fieldtype: "Check",
		},
		{
			fieldname: "due_today",
			label: __("Due Today"),
			fieldtype: "Check",
		},
		{
			fieldname: "near_due_days",
			label: __("Near Due Days"),
			fieldtype: "Int",
			default: 7,
		},
	],
};
