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
	workflow_state(frm) {
		frm.trigger("setup_payment_entry_buttons");
	},
	status(frm) {
		frm.trigger("setup_payment_entry_buttons");
	},
	payment_status(frm) {
		frm.trigger("setup_payment_entry_buttons");
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
		frappe.workflow.setup(frm.doctype);
		frm.trigger("recalc_totals");
		frm.trigger("setup_payment_entry_buttons");
	},
	setup_payment_entry_buttons(frm) {
		if (frm.is_new()) {
			return;
		}

		// status is synced from workflow on save; workflow_state is the Workflow State name (e.g. "Approved")
		const approved =
			frm.doc.status === "Approved" || frm.doc.workflow_state === "Approved";

		const show_create =
			frm.doc.docstatus === 1 &&
			approved &&
			(frm.doc.payment_status || "") !== "Paid" &&
			!frm.doc.payment_entry &&
			!frm.doc.journal_entry &&
			flt(frm.doc.total_requested_amount) > 0;

		if (show_create) {
			frm.add_custom_button(__("Create Payment Entry"), () => {
				frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.create_payment_entry",
					args: { pm_request: frm.doc.name },
					freeze: true,
					freeze_message: __("Creating Payment Entry…"),
					callback(r) {
						if (r.exc) {
							return;
						}
						if (r.message) {
							frappe.show_alert({
								message: __("Payment Entry {0} created", [r.message]),
								indicator: "green",
							});
							frm.reload_doc();
						}
					},
					error(r) {
						const msg =
							(r && r.message) ||
							(r && r._server_messages && frappe.utils.parse_json(r._server_messages)) ||
							__("Could not create Payment Entry");
						frappe.msgprint({ title: __("Payment Entry failed"), message: msg, indicator: "red" });
					},
				});
			}, __("Accounting"));
		}

		if (frm.doc.payment_entry) {
			frm.add_custom_button(
				__("Open Payment Entry"),
				() => frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry),
				__("Accounting")
			);
		}
	},
	recalc_totals(frm) {
		let t = 0;
		(frm.doc.details || []).forEach((r) => {
			t += flt(r.advance_amount);
		});
		if (frm.doc.docstatus === 0) {
			frm.set_value("total_requested_amount", t);
			(frm.doc.details || []).forEach((r) => {
				const row = locals[r.doctype][r.name];
				row.percent_of_total = t ? (flt(r.advance_amount) / t) * 100 : 0;
			});
			frm.refresh_field("details");
		}
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
