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
	workflow_state(frm) {
		setup_settlement_buttons(frm);
	},
	status(frm) {
		setup_settlement_buttons(frm);
	},
	docstatus(frm) {
		setup_settlement_buttons(frm);
	},
	journal_entry(frm) {
		setup_settlement_buttons(frm);
	},
	refresh_holder_pending(frm) {
		if (frm.is_new() || !frm.doc.employee || !frm.doc.company) {
			setup_settlement_buttons(frm);
			return;
		}
		frappe.db.get_value(
			"PM Holder",
			{ employee: frm.doc.employee, company: frm.doc.company },
			["name", "petty_cash_account", "current_balance", "consumed_amount"],
			(r) => {
				if (!r || !r.name) {
					frm.trigger("recalc_totals");
					setup_settlement_buttons(frm);
					return;
				}
				frm.set_value("holder", r.name);
				frm.set_value("petty_cash_account", r.petty_cash_account);
				frm.set_value("pending_amount", r.current_balance);
				frm.set_value("current_petty_balance", r.current_balance);
				frm.set_value("total_cleared_amount", r.consumed_amount || 0);
				frm.set_value("total_funded_amount", flt(r.current_balance) + flt(r.consumed_amount));
				frm.trigger("recalc_totals");
				setup_settlement_buttons(frm);
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
		if (!frm.is_new() && frm.doc.employee && frm.doc.company) {
			frm.trigger("refresh_holder_pending");
		} else {
			frm.trigger("recalc_totals");
			setup_settlement_buttons(frm);
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

function setup_settlement_buttons(frm) {
	frm.page.remove_inner_button(__("Settle Petty Cash"));
	frm.page.remove_inner_button(__("Open Settlement Journal Entry"));

	const wf = frm.doc.workflow_state;
	const wfState = frappe.workflow.get_state ? frappe.workflow.get_state(frm.doc) : wf;
	const isApproved = wf === "Approved" || wfState === "Approved";

	const show_settle =
		!frm.is_new() && frm.doc.docstatus === 1 && isApproved && !frm.doc.journal_entry;

	if (show_settle) {
		const $btn = frm.page.add_inner_button(
			__("Settle Petty Cash"),
			() => {
				frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.settle_petty_cash",
					args: { pm_clearance: frm.doc.name },
					freeze: true,
					freeze_message: __("Settling petty cash…"),
					callback(r) {
						if (r.exc) return;
						frappe.show_alert({
							message: __("Settlement Journal Entry created"),
							indicator: "green",
						});
						frm.reload_doc();
					},
					error(r) {
						const msg =
							(r && r.message) ||
							(r && r._server_messages && frappe.utils.parse_json(r._server_messages)) ||
							__("Could not settle petty cash");
						frappe.msgprint({
							title: __("Settlement failed"),
							message: msg,
							indicator: "red",
						});
					},
				});
			},
			null,
			"primary"
		);
		if ($btn && $btn.addClass) {
			$btn.addClass("btn-primary");
		}
	}

	if (frm.doc.journal_entry) {
		frm.page.add_inner_button(
			__("Open Settlement Journal Entry"),
			() => frappe.set_route("Form", "Journal Entry", frm.doc.journal_entry)
		);
	}
}

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
