# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

function is_consignment(frm) {
	return cint(frm.doc.custom_is_consignment_receipt) || cint(frm.doc.custom_is_consignment_return);
}

frappe.ui.form.on("Stock Entry", {
	setup(frm) {
		frm.set_query("custom_consignment_receipt_reference", () => ({
			query: "erpnext_extensions.consignment_stock.queries.consignment_receipt_query",
			filters: {
				company: frm.doc.company,
				party_type: frm.doc.custom_consignment_party_type,
				party: frm.doc.custom_consignment_party,
			},
		}));
		frm.set_query("custom_consignment_receipt_stock_entry", "items", () => ({
			query: "erpnext_extensions.consignment_stock.queries.consignment_receipt_query",
			filters: {
				company: frm.doc.company,
				party_type: frm.doc.custom_consignment_party_type,
				party: frm.doc.custom_consignment_party,
			},
		}));
	},

	refresh(frm) {
		if (!is_consignment(frm)) {
			return;
		}

		// Block additional costs UI
		if (frm.fields_dict.additional_costs) {
			frm.set_df_property("additional_costs", "cannot_add_rows", true);
		}

		if (cint(frm.doc.custom_is_consignment_return)) {
			frm.doc.items.forEach((row) => {
				frm.set_df_property("basic_rate", "read_only", 1, frm.docname, "items", row.name);
			});
			frm.set_value("custom_has_consignment_receipt_reference", 1);
		}

		if (frm.doc.docstatus !== 1) {
			return;
		}

		if (cint(frm.doc.custom_is_consignment_receipt)) {
			if (!frm.doc.custom_consignment_recognition_je) {
				frm.add_custom_button(
					__("Create Consignment Recognition Entry"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.consignment_stock.api.create_consignment_recognition_entry",
							args: { stock_entry: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frm.reload_doc();
								frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
							},
						});
					},
					__("Consignment")
				);
			} else {
				frm.add_custom_button(
					__("View Recognition Journal Entry"),
					() => frappe.set_route("Form", "Journal Entry", frm.doc.custom_consignment_recognition_je),
					__("Consignment")
				);
			}

			frm.add_custom_button(
				__("Create Consignment Return"),
				() => {
					frappe.call({
						method:
							"erpnext_extensions.consignment_stock.api.make_consignment_return_from_receipt",
						args: { source_name: frm.doc.name },
						freeze: true,
						callback(r) {
							if (!r.message) return;
							frappe.set_route("Form", "Stock Entry", r.message.name);
						},
					});
				},
				__("Consignment")
			);
		}

		if (cint(frm.doc.custom_is_consignment_return)) {
			if (!frm.doc.custom_consignment_settlement_je) {
				frm.add_custom_button(
					__("Create Consignment Return Settlement"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.consignment_stock.api.create_consignment_return_settlement",
							args: { stock_entry: frm.doc.name },
							freeze: true,
							callback(r) {
								if (!r.message) return;
								frm.reload_doc();
								frappe.set_route("Form", "Journal Entry", r.message.journal_entry);
							},
						});
					},
					__("Consignment")
				);
			} else {
				frm.add_custom_button(
					__("View Return Settlement"),
					() => frappe.set_route("Form", "Journal Entry", frm.doc.custom_consignment_settlement_je),
					__("Consignment")
				);
			}
		}
	},

	custom_consignment_receipt_reference(frm) {
		if (!frm.doc.custom_consignment_receipt_reference) return;
		(frm.doc.items || []).forEach((row) => {
			if (!row.custom_consignment_receipt_stock_entry) {
				frappe.model.set_value(
					row.doctype,
					row.name,
					"custom_consignment_receipt_stock_entry",
					frm.doc.custom_consignment_receipt_reference
				);
			}
		});
	},
});

frappe.ui.form.on("Stock Entry Detail", {
	custom_consignment_receipt_stock_entry(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.custom_consignment_receipt_stock_entry || !row.item_code) return;
		frappe.db
			.get_list("Stock Entry Detail", {
				filters: {
					parent: row.custom_consignment_receipt_stock_entry,
					item_code: row.item_code,
				},
				fields: ["name"],
				limit: 2,
			})
			.then((rows) => {
				if (rows && rows.length === 1) {
					frappe.model.set_value(cdt, cdn, "custom_consignment_receipt_detail", rows[0].name);
				}
			});
	},
});
