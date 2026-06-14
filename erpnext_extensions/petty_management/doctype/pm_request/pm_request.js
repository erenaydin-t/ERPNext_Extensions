// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt
//
// PM Request vs PM Clearance:
// - PM Request funds the holder’s Petty Cash Account (Payment Entry: Dr petty cash, Cr bank).
// - PM Request funding is later consumed by PM Clearance through PM Clearance Request Allocation rows.
// - Settlement posting (Journal Entry) uses Purchase Invoice lines; allocation rows are control / traceability.

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
		if (!frm.doc.employee || !frm.doc.company) {
			return;
		}
		frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_holder_context",
			args: {
				employee: frm.doc.employee,
				company: frm.doc.company,
				posting_date: frm.doc.transaction_date,
			},
			callback(resp) {
				const r = resp.message || {};
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
			},
		});
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
		setTimeout(() => frm.trigger("setup_payment_entry_buttons"), 120);
	},
	/* Toolbar: server-side flags = source of truth (workflow + PE state). */
	setup_payment_entry_buttons(frm) {
		remove_pm_request_toolbar_buttons(frm);
		if (frm.is_new() || !frm.doc.name) {
			return;
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
					frappe.show_alert({
						message: __("Payment Entry created"),
						indicator: "green",
					});
					frm.reload_doc();
				},
				error(r) {
					frappe.msgprint({
						title: __("Payment Entry failed"),
						message: parse_pm_request_server_error(r),
						indicator: "red",
					});
				},
			});
		};

		frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_pm_request_action_flags",
			args: { pm_request: frm.doc.name },
			callback(r) {
				const f = r.message || {};
				hide_pm_request_reject_when_not_allowed(frm, f);
				if (f.can_create_payment_entry) {
					frm.add_custom_button(__("Create Payment Entry"), runCreate, null);
					if (frm.change_custom_button_type) {
						frm.change_custom_button_type(__("Create Payment Entry"), null, "primary");
					}
				}
				if (f.can_open_payment_entry && frm.doc.payment_entry) {
					frm.add_custom_button(__("Open Payment Entry"), () =>
						frappe.set_route("Form", "Payment Entry", frm.doc.payment_entry)
					);
				}
			},
		});
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

function remove_pm_request_toolbar_buttons(frm) {
	["Create Payment Entry", "Open Payment Entry"].forEach((raw) => {
		const L = __(raw);
		frm.remove_custom_button(L);
		frm.page.remove_inner_button(L);
		frm.page.remove_inner_button(raw);
	});
}

function hide_pm_request_reject_when_not_allowed(frm, flags) {
	if (!flags || flags.can_reject) {
		return;
	}
	const rejectLabels = [__("PM Reject"), "PM Reject", __("Reject")];
	if (frm.page && frm.page.actions_menu_items) {
		frm.page.actions_menu_items = frm.page.actions_menu_items.filter((item) => {
			const label = (item.label || item.action || "").toString();
			return !rejectLabels.some((r) => label.indexOf(r) >= 0 || label === r);
		});
	}
}

frappe.ui.form.on("PM Request Detail", {
	advance_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function parse_pm_request_server_error(r) {
	if (r && r.message && typeof r.message === "string") {
		return r.message;
	}
	if (r && r.exc && typeof r.exc === "string") {
		const lockMatch = r.exc.match(/Lock wait timeout|QueryTimeoutError/i);
		if (lockMatch) {
			return __(
				"This PM Request is currently being processed. Please refresh and try again."
			);
		}
	}
	if (r && r._server_messages) {
		try {
			const raw = frappe.utils.parse_json(r._server_messages);
			const list = Array.isArray(raw) ? raw : [raw];
			const parts = list
				.map((item) => {
					const row = typeof item === "string" ? frappe.utils.parse_json(item) : item;
					return (row && row.message) || "";
				})
				.filter(Boolean);
			if (parts.length) {
				return parts.join("\n");
			}
		} catch (e) {
			/* use fallback */
		}
	}
	return __("Could not create Payment Entry");
}

function flt(v) {
	const parsed = parseFloat(v);
	return Number.isFinite(parsed) ? parsed : 0;
}
