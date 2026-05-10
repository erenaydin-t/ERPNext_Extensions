// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Request", {
	employee(frm) {
		frm.trigger("refresh_holder_balances");
	},
	company(frm) {
		frm.trigger("refresh_holder_balances");
	},
	transaction_date(frm) {
		frm.trigger("refresh_holder_balances");
	},
	refresh_holder_balances(frm) {
		if (frm.is_new() || !frm.doc.employee || !frm.doc.company) {
			return;
		}
		frappe.db.get_value(
			"PM Holder",
			{ employee: frm.doc.employee, company: frm.doc.company },
			["name", "petty_cash_account", "max_balance", "current_balance"],
			(r) => {
				if (!r || !r.name) {
					return;
				}
				frm.set_value("holder", r.name);
				frm.set_value("petty_cash_account", r.petty_cash_account);
				frm.set_value("max_balance_for_petty_cash", r.max_balance);
				frm.set_value("previous_balance", r.current_balance);
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
		const show_pay =
			!frm.is_new() &&
			frm.doc.docstatus === 1 &&
			frm.doc.status === "Approved" &&
			!frm.doc.payment_entry &&
			!frm.doc.journal_entry;

		if (show_pay) {
			frm.add_custom_button(__("Create Payment Entry"), () => {
				frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.create_payment_entry",
					args: { pm_request: frm.doc.name },
					freeze: true,
					callback(r) {
						if (r.message) {
							frappe.show_alert({ message: __("Accounting document created"), indicator: "green" });
							frm.reload_doc();
						}
					},
				});
			});
		}

		if (frm.doc.payment_entry) {
			frm.add_custom_button(
				__("View Payment Entry"),
				() => frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry),
				__("Accounting")
			);
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
		let t = 0;
		(frm.doc.details || []).forEach((r) => {
			t += flt(r.advance_amount);
		});
		frm.set_value("total_requested_amount", t);
		(frm.doc.details || []).forEach((r) => {
			const row = locals[r.doctype][r.name];
			row.percent_of_total = t ? (flt(r.advance_amount) / t) * 100 : 0;
		});
		frm.refresh_field("details");
	},
});

frappe.ui.form.on("PM Request Detail", {
	advance_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function flt(v) {
	return frappe.utils.flt(v);
}
