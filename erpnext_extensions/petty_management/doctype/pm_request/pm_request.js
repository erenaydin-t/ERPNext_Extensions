// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Request", {
	setup(frm) {
		frm.set_query("employee_bank_account", () => {
			if (!frm.doc.employee) {
				return {
					query: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_employee_bank_account_query",
					filters: { employee: "", company: frm.doc.company || "" },
				};
			}
			return {
				query: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_employee_bank_account_query",
				filters: { employee: frm.doc.employee, company: frm.doc.company || "" },
			};
		});
	},
	employee(frm) {
		frm.set_value("employee_bank_account", null);
		frm.trigger("refresh_holder_balances");
	},
	company(frm) {
		frm.set_value("employee_bank_account", null);
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
	docstatus(frm) {
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

				const setBankFromList = () => {
					frappe.db
						.get_list("Bank Account", {
							filters: {
								party_type: "Employee",
								party: frm.doc.employee,
								company: frm.doc.company,
								disabled: 0,
							},
							fields: ["name"],
							limit: 2,
						})
						.then((rows) => {
							if (r.default_employee_bank_account) {
								frm.set_value("employee_bank_account", r.default_employee_bank_account);
							} else if (rows.length === 1) {
								frm.set_value("employee_bank_account", rows[0].name);
							}
							frm.trigger("setup_payment_entry_buttons");
						});
				};

				if (r.default_employee_bank_account) {
					frm.set_value("employee_bank_account", r.default_employee_bank_account);
					frm.trigger("setup_payment_entry_buttons");
				} else {
					setBankFromList();
				}
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
	/*
		Create Payment Entry — visible when ALL of:
		- !frm.is_new()
		- frm.doc.workflow_state === "Approved" OR frappe.workflow.get_state(frm.doc) === "Approved"
		  (Link value is normally "Approved"; get_state covers odd workflow field setups)
		- (frm.doc.payment_status || "") !== "Paid"
		- !frm.doc.payment_entry
		- flt(frm.doc.total_requested_amount) > 0
		Not gated on status or docstatus for display; server enforces submit.
		Button: inner toolbar primary (not Accounting dropdown).
	*/
	setup_payment_entry_buttons(frm) {
		frm.page.remove_inner_button(__("Create Payment Entry"));
		frm.page.remove_inner_button(__("Open Payment Entry"));

		const wfRaw = frm.doc.workflow_state;
		const wfResolved = frappe.workflow.get_state
			? frappe.workflow.get_state(frm.doc)
			: wfRaw;
		const workflowApproved = wfRaw === "Approved" || wfResolved === "Approved";

		const hiddenBecause = [];
		if (frm.is_new()) {
			hiddenBecause.push("is_new");
		}
		if (!workflowApproved) {
			hiddenBecause.push(
				`workflow_not_Approved(workflow_state=${JSON.stringify(wfRaw)}, get_state=${JSON.stringify(
					wfResolved
				)})`
			);
		}
		if (!(flt(frm.doc.total_requested_amount) > 0)) {
			hiddenBecause.push("total_requested_amount_not_positive");
		}
		if (frm.doc.payment_entry) {
			hiddenBecause.push("payment_entry_already_set");
		}
		if ((frm.doc.payment_status || "") === "Paid") {
			hiddenBecause.push("payment_status_is_paid");
		}

		const showCreate = hiddenBecause.length === 0;

		if (!showCreate) {
			console.warn("[PM Request] Create Payment Entry hidden:", hiddenBecause, {
				workflow_state: wfRaw,
				workflow_get_state: wfResolved,
				payment_status: frm.doc.payment_status,
				payment_entry: frm.doc.payment_entry,
				total_requested_amount: frm.doc.total_requested_amount,
			});
		}

		const runCreate = () => {
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
		};

		if (showCreate) {
			frm.page.add_inner_button(__("Create Payment Entry"), runCreate, null, "primary");
		}

		if (frm.doc.payment_entry) {
			frm.page.add_inner_button(__("Open Payment Entry"), () =>
				frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry)
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
		frm.trigger("setup_payment_entry_buttons");
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
