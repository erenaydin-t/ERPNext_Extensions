// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

function is_material_loan(frm) {
	return (
		cint(frm.doc.custom_is_material_loan_issue) || cint(frm.doc.custom_is_material_loan_return)
	);
}

frappe.ui.form.on("Stock Entry", {
	setup(frm) {
		frm.set_query("custom_material_loan_issue_reference", () => ({
			query: "erpnext_extensions.consignment_stock.material_loan.queries.material_loan_issue_query",
			filters: {
				company: frm.doc.company,
				party_type: frm.doc.custom_material_loan_party_type,
				party: frm.doc.custom_material_loan_party,
			},
		}));
		frm.set_query("custom_material_loan_issue", "items", () => ({
			query: "erpnext_extensions.consignment_stock.material_loan.queries.material_loan_issue_query",
			filters: {
				company: frm.doc.company,
				party_type: frm.doc.custom_material_loan_party_type,
				party: frm.doc.custom_material_loan_party,
			},
		}));
	},

	refresh(frm) {
		if (!is_material_loan(frm)) {
			return;
		}

		if (frm.fields_dict.additional_costs) {
			frm.set_df_property("additional_costs", "cannot_add_rows", true);
		}

		if (cint(frm.doc.custom_is_material_loan_return)) {
			(frm.doc.items || []).forEach((row) => {
				frm.set_df_property("basic_rate", "read_only", 1, frm.docname, "items", row.name);
			});
		}

		if (frm.doc.docstatus !== 1) {
			return;
		}

		if (cint(frm.doc.custom_is_material_loan_issue)) {
			if (!frm.doc.custom_material_loan_recognition_je) {
				frm.add_custom_button(
					__("Create Material Loan Recognition Entry"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.consignment_stock.material_loan.api.create_material_loan_recognition_entry",
							args: { stock_entry: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frm.reload_doc();
								frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
							},
						});
					},
					__("Material Loan")
				);
			} else {
				frm.add_custom_button(
					__("View Recognition Journal Entry"),
					() =>
						frappe.set_route(
							"Form",
							"Journal Entry",
							frm.doc.custom_material_loan_recognition_je
						),
					__("Material Loan")
				);
			}

			if (frm.doc.custom_material_loan_recognition_status === "Submitted") {
				frm.add_custom_button(
					__("Create Material Loan Return"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.consignment_stock.material_loan.api.make_material_loan_return_from_issue",
							args: { source_name: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frappe.set_route("Form", r.message.doctype, r.message.name);
							},
						});
					},
					__("Material Loan")
				);
			}
		}

		if (cint(frm.doc.custom_is_material_loan_return)) {
			if (!frm.doc.custom_material_loan_settlement_je) {
				frm.add_custom_button(
					__("Create Material Loan Return Settlement"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.consignment_stock.material_loan.api.create_material_loan_return_settlement",
							args: { stock_entry: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frm.reload_doc();
								frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
							},
						});
					},
					__("Material Loan")
				);
			} else {
				frm.add_custom_button(
					__("View Settlement Journal Entry"),
					() =>
						frappe.set_route(
							"Form",
							"Journal Entry",
							frm.doc.custom_material_loan_settlement_je
						),
					__("Material Loan")
				);
			}

			const issue =
				frm.doc.custom_material_loan_issue_reference ||
				(frm.doc.items && frm.doc.items[0] && frm.doc.items[0].custom_material_loan_issue);
			if (issue) {
				frm.add_custom_button(
					__("View Original Material Loan Issue"),
					() => frappe.set_route("Form", "Stock Entry", issue),
					__("Material Loan")
				);
			}
		}
	},
});
