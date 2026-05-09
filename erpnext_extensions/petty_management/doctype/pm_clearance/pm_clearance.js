// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Clearance", {
	employee(frm) {
		frm.trigger("refresh_holder_pending");
	},
	company(frm) {
		frm.trigger("refresh_holder_pending");
	},
	transaction_date(frm) {
		frm.trigger("refresh_holder_pending");
	},
	refresh_holder_pending(frm) {
		if (frm.is_new() || !frm.doc.employee || !frm.doc.company) {
			return;
		}
		frappe.db.get_value(
			"PM Holder",
			{ employee: frm.doc.employee, company: frm.doc.company },
			["name", "petty_cash_account", "current_balance"],
			(r) => {
				if (!r || !r.name) {
					return;
				}
				frm.set_value("holder", r.name);
				frm.set_value("petty_cash_account", r.petty_cash_account);
				frm.set_value("pending_amount", r.current_balance);
			}
		);
	},
	details_add(frm) {
		frm.trigger("recalc_totals");
	},
	details_remove(frm) {
		frm.trigger("recalc_totals");
	},
	refresh(frm) {
		frm.trigger("recalc_totals");
		if (!frm.is_new() && frm.doc.docstatus === 0 && !frm.doc.journal_entry) {
			frm.add_custom_button(__("Create Journal Entry"), () => {
				frappe.confirm(__("Submit clearance and generate Journal Entry?"), () => {
					frm.save("Submit");
				});
			});
		}

		if (frm.doc.journal_entry) {
			frm.add_custom_button(
				__("View Journal Entry"),
				() => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry),
				__("Accounting")
			);
		}
		if (frm.doc.purchase_invoice) {
			frm.add_custom_button(
				__("View Purchase Invoice"),
				() => frappe.set_route("Form", "Purchase Invoice", frm.doc.purchase_invoice),
				__("Accounting")
			);
		}
	},
	recalc_totals(frm) {
		let net = 0;
		let tax = 0;
		(frm.doc.details || []).forEach((r) => {
			net += flt(r.amount);
			tax += flt(r.tax_amount);
			const row = locals[r.doctype][r.name];
			row.amount_plus_tax = flt(r.amount) + flt(r.tax_amount);
		});
		frm.set_value("total_expense_without_tax", net);
		frm.set_value("total_tax_amount", tax);
		const total = net + tax;
		frm.set_value("total_expense_amount", total);
		frm.set_value("total_petty_cash", total);
		frm.set_value("remaining_amount", flt(frm.doc.pending_amount) - total);
		frm.refresh_field("details");
	},
});

frappe.ui.form.on("PM Clearance Detail", {
	expense_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.expense_type) {
			return;
		}
		frappe.db.get_value(
			"PM Expense Type",
			row.expense_type,
			[
				"is_tax_applicable",
				"is_non_stock_expense_type",
				"default_cost_center",
				"requires_supplier",
				"requires_attachment",
			],
			(r) => {
				if (!r) {
					return;
				}
				frappe.model.set_value(cdt, cdn, "is_tax_applicable", r.is_tax_applicable ? 1 : 0);
				frappe.model.set_value(cdt, cdn, "is_non_stock_expense_type", r.is_non_stock_expense_type ? 1 : 0);
				if (r.default_cost_center) {
					frappe.model.set_value(cdt, cdn, "cost_center", r.default_cost_center);
				}
			}
		);
	},
	amount(frm) {
		frm.trigger("recalc_totals");
	},
	tax_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function flt(v) {
	return frappe.utils.flt(v);
}
