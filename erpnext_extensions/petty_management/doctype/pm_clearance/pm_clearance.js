// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt
//
// PM Request vs PM Clearance (no direct DocType link):
// - PM Request funds the holder’s Petty Cash Account (Payment Entry).
// - PM Clearance settles Purchase Invoices from that same account (Journal Entry).
// - Connection: PM Holder + Petty Cash Account balance, not a linked PM Request field.
// - Optional future: reference one or more PM Requests on clearance; not implemented now.

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
					frm.trigger("recalc_totals");
					return;
				}
				frm.set_value("holder", r.name);
				frm.set_value("petty_cash_account", r.petty_cash_account);
				// Pending Amount = petty cash available (holder snapshot); server recalculates from GL on save.
				frm.set_value("pending_amount", r.current_balance);
				frm.trigger("recalc_totals");
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
		if (!frm.is_new() && frm.doc.employee && frm.doc.company) {
			frm.trigger("refresh_holder_pending");
		} else {
			frm.trigger("recalc_totals");
		}
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
	},
	recalc_totals(frm) {
		let total = 0;
		(frm.doc.details || []).forEach((r) => {
			total += flt(r.allocated_amount);
			const row = locals[r.doctype][r.name];
			row.amount_plus_tax = flt(r.allocated_amount);
		});
		frm.set_value("total_expense_without_tax", 0);
		frm.set_value("total_tax_amount", 0);
		frm.set_value("total_expense_amount", total);
		frm.set_value("total_petty_cash", total);
		frm.set_value("remaining_amount", flt(frm.doc.pending_amount) - total);
		frm.refresh_field("details");
	},
});

frappe.ui.form.on("PM Clearance Detail", {
	purchase_invoice(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.purchase_invoice) {
			frappe.model.set_value(cdt, cdn, "supplier", "");
			frappe.model.set_value(cdt, cdn, "outstanding_amount", 0);
			frappe.model.set_value(cdt, cdn, "allocated_amount", 0);
			frm.trigger("recalc_totals");
			return;
		}
		frappe.db.get_doc("Purchase Invoice", row.purchase_invoice).then((pi) => {
			frappe.model.set_value(cdt, cdn, "supplier", pi.supplier);
			frappe.model.set_value(cdt, cdn, "outstanding_amount", pi.outstanding_amount || 0);
			const cur = flt(row.allocated_amount);
			if (!cur) {
				frappe.model.set_value(cdt, cdn, "allocated_amount", pi.outstanding_amount || 0);
			}
			frm.trigger("recalc_totals");
		});
	},
	allocated_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function flt(v) {
	return frappe.utils.flt(v);
}
