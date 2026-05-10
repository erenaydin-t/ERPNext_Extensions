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
			[
				"name",
				"petty_cash_account",
				"max_balance",
				"current_balance",
				"default_employee_bank_account",
			],
			(r) => {
				if (!r || !r.name) {
					return;
				}
				frm.set_value("holder", r.name);
				frm.set_value("petty_cash_account", r.petty_cash_account);
				frm.set_value("max_balance_for_petty_cash", r.max_balance);
				frm.set_value("previous_balance", r.current_balance);
				if (r.default_employee_bank_account) {
					frm.set_value("employee_bank_account", r.default_employee_bank_account);
				}
			}
		);
		frappe.db.get_single_value("PM Settings", "default_bank_account").then((bank) => {
			if (bank && !frm.doc.paid_from_account) {
				frm.set_value("paid_from_account", bank);
			}
		});
	},
	paid_from_account(frm) {
		frm.trigger("setup_payment_entry_buttons");
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
		// Avoid duplicate inner buttons when refresh / workflow fires repeatedly
		frm.remove_custom_button(__("Create Payment Entry"), __("Accounting"));
		frm.remove_custom_button(__("Open Payment Entry"), __("Accounting"));

		if (frm.is_new()) {
			return;
		}

		// status is synced from workflow on save; workflow_state is the Workflow State doc name
		// (often same string as the state's title, e.g. "Approved" — both are accepted below).
		const approved =
			frm.doc.status === "Approved" || frm.doc.workflow_state === "Approved";

		// Visibility (Create): intentionally not gated on docstatus — draft/submitted both show
		// the button when approved; server responds with "Please submit PM Request..." if still draft.
		// Gates: not paid, no PE yet, positive amount, bank funding account set, no stray JE on doc.
		const show_create =
			approved &&
			(frm.doc.payment_status || "") !== "Paid" &&
			!frm.doc.payment_entry &&
			!frm.doc.journal_entry &&
			flt(frm.doc.total_requested_amount) > 0 &&
			!!frm.doc.paid_from_account;

		if (frappe.boot.developer_mode) {
			// Debug: if a gate fails, the Create button is hidden. Check workflow_state vs status if "Approved" mismatch.
			console.debug("[PM Request] Create Payment Entry visibility", {
				approved,
				payment_status: frm.doc.payment_status,
				has_payment_entry: !!frm.doc.payment_entry,
				has_journal_entry: !!frm.doc.journal_entry,
				total_requested_amount: frm.doc.total_requested_amount,
				has_paid_from: !!frm.doc.paid_from_account,
				docstatus: frm.doc.docstatus,
				status: frm.doc.status,
				workflow_state: frm.doc.workflow_state,
				show_create,
			});
		}

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
