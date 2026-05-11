// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt
//
// PM Clearance: settlement lines (Purchase Invoice and/or Supplier Advance) + PM Request allocation.

const SETTLEMENT_PI = "Purchase Invoice";
const SETTLEMENT_SA = "Supplier Advance";

frappe.ui.form.on("PM Clearance", {
	employee(frm) {
		frm._pm_alloc_select_holder_shown = 0;
		frm._pm_no_holder_msg_done = 0;
		frm.trigger("refresh_holder_pending");
	},
	company(frm) {
		frm._pm_alloc_select_holder_shown = 0;
		frm._pm_no_holder_msg_done = 0;
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
	request_allocations_add(frm) {
		frm.trigger("recalc_totals");
	},
	request_allocations_remove(frm) {
		frm.trigger("recalc_totals");
	},
	setup(frm) {
		frm.set_query("pm_request", "request_allocations", () => {
			const ready =
				frm.doc.employee &&
				frm.doc.company &&
				frm.doc.holder &&
				(frm.doc.petty_cash_account || "").trim();
			if (!ready && !frm._pm_alloc_select_holder_shown) {
				frappe.show_alert({
					message: __("Select Employee/Holder first."),
					indicator: "orange",
				});
				frm._pm_alloc_select_holder_shown = 1;
			}
			if (ready) {
				frm._pm_alloc_select_holder_shown = 0;
			}
			return {
				query: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.pm_request_query_for_pm_clearance",
				filters: {
					employee: frm.doc.employee,
					company: frm.doc.company,
					holder: frm.doc.holder,
					petty_cash_account: frm.doc.petty_cash_account,
					pm_clearance: frm.doc.name || null,
				},
			};
		});
	},
	refresh_holder_pending(frm) {
		if (!frm.doc.employee || !frm.doc.company) {
			frm.set_value("holder", "");
			frm.set_value("petty_cash_account", "");
			frm.set_value("pending_amount", 0);
			frm.set_value("current_petty_balance", 0);
			frm.set_value("total_cleared_amount", 0);
			frm.set_value("total_funded_amount", 0);
			frm._pm_clearance_prev_holder = undefined;
			frm.trigger("recalc_totals");
			setup_settlement_buttons(frm);
			return;
		}
		if (frm.doc.company) {
			frappe.db.get_value("Company", frm.doc.company, "default_currency", (cur) => {
				if (cur && cur.default_currency) {
					frm.set_value("currency", cur.default_currency);
				}
			});
		}
		frappe.db.get_value(
			"PM Holder",
			{ employee: frm.doc.employee, company: frm.doc.company, is_blocked: 0 },
			["name", "petty_cash_account", "current_balance", "consumed_amount", "pending_clearance_amount"],
			(r) => {
				const prev = frm._pm_clearance_prev_holder;
				if (!r || !r.name) {
					frm.set_value("holder", "");
					frm.set_value("petty_cash_account", "");
					frm.set_value("pending_amount", 0);
					frm.set_value("current_petty_balance", 0);
					frm.set_value("total_cleared_amount", 0);
					frm.set_value("total_funded_amount", 0);
					if (prev) {
						(frm.doc.request_allocations || []).forEach((row) => {
							if (!row.is_legacy_row && row.pm_request) {
								frappe.model.set_value(row.doctype, row.name, "pm_request", "");
								frappe.model.set_value(row.doctype, row.name, "allocated_amount", 0);
								frappe.model.set_value(row.doctype, row.name, "request_amount", 0);
								frappe.model.set_value(row.doctype, row.name, "paid_amount", 0);
								frappe.model.set_value(row.doctype, row.name, "previously_allocated_amount", 0);
								frappe.model.set_value(row.doctype, row.name, "available_amount", 0);
							}
						});
					}
					frm._pm_clearance_prev_holder = "";
					if (!frm._pm_no_holder_msg_done) {
						frappe.msgprint({
							title: __("PM Holder"),
							message: __(
								"No PM Holder found for this employee and company. Please create PM Holder first."
							),
							indicator: "orange",
						});
						frm._pm_no_holder_msg_done = 1;
					}
					frm.trigger("recalc_totals");
					setup_settlement_buttons(frm);
					return;
				}
				frm._pm_no_holder_msg_done = 0;
				if (prev !== undefined && prev && prev !== r.name) {
					(frm.doc.request_allocations || []).forEach((row) => {
						if (!row.is_legacy_row && row.pm_request) {
							frappe.model.set_value(row.doctype, row.name, "pm_request", "");
							frappe.model.set_value(row.doctype, row.name, "allocated_amount", 0);
							frappe.model.set_value(row.doctype, row.name, "request_amount", 0);
							frappe.model.set_value(row.doctype, row.name, "paid_amount", 0);
							frappe.model.set_value(row.doctype, row.name, "previously_allocated_amount", 0);
							frappe.model.set_value(row.doctype, row.name, "available_amount", 0);
						}
					});
				}
				frm._pm_clearance_prev_holder = r.name;
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
		if (frm.doc.employee && frm.doc.company) {
			frm.trigger("refresh_holder_pending");
		} else {
			frm.set_value("holder", "");
			frm.set_value("petty_cash_account", "");
			frm.set_value("pending_amount", 0);
			frm.set_value("current_petty_balance", 0);
			frm.set_value("total_cleared_amount", 0);
			frm.set_value("total_funded_amount", 0);
			frm._pm_clearance_prev_holder = undefined;
			frm.trigger("recalc_totals");
			setup_settlement_buttons(frm);
		}
		frm.add_custom_button(
			__("Preview Settlement Entry"),
			() => preview_settlement_entry(frm),
			__("Actions")
		);
	},
	recalc_totals(frm) {
		let settled = 0;
		(frm.doc.details || []).forEach((r) => {
			settled += flt(r.allocated_amount);
			const row = locals[r.doctype][r.name];
			row.amount_plus_tax = flt(r.allocated_amount);
		});
		let req_total = 0;
		(frm.doc.request_allocations || []).forEach((r) => {
			req_total += flt(r.allocated_amount);
		});
		frm.set_value("total_expense_without_tax", 0);
		frm.set_value("total_tax_amount", 0);
		frm.set_value("total_expense_amount", settled);
		frm.set_value("total_petty_cash", settled);
		frm.set_value("remaining_amount", flt(frm.doc.pending_amount) - settled);
		frm.refresh_field("details");
		frm.refresh_field("request_allocations");
		update_settlement_balance_intro(frm, settled, req_total);
		setup_settlement_buttons(frm);
	},
});

function update_settlement_balance_intro(frm, settled_total, req_total) {
	frm.set_intro(null);
	const diff = settled_total - req_total;
	if (!frm.doc.request_allocations || frm.doc.request_allocations.length === 0) {
		frm.set_intro(
			__("Add PM Request allocation lines; total must match settlement lines (Purchase Invoice + Supplier Advance)."),
			"orange"
		);
		return;
	}
	if (Math.abs(diff) > 0.005) {
		frm.set_intro(
			__(
				"Settlement imbalance: settlement lines total {0} vs PM Request allocation total {1} (difference {2}).",
				[format_currency(settled_total), format_currency(req_total), format_currency(diff)]
			),
			"red"
		);
	} else {
		frm.set_intro(
			__(
				"Settlement lines and PM Request allocation totals match ({0}).",
				[format_currency(settled_total)]
			),
			"green"
		);
	}
}

function format_currency(v) {
	return frappe.format(flt(v), { fieldtype: "Currency" });
}

function preview_settlement_entry(frm) {
	const settled = (frm.doc.details || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
	if (!frm.doc.details || frm.doc.details.length === 0 || settled <= 0) {
		frappe.msgprint(__("Add at least one settlement line with amount to preview."));
		return;
	}
	const dirty = typeof frm.is_dirty === "function" ? frm.is_dirty() : false;
	const preview_args =
		frm.is_new() || dirty ? { doc: frm.doc } : { pm_clearance: frm.doc.name };
	frappe.call({
		method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.preview_pm_clearance_settlement",
		args: preview_args,
		freeze: true,
		freeze_message: __("Building preview…"),
		callback(r) {
			if (!r.message) return;
			const d = r.message;
			let html =
				"<p><strong>" +
				__("Company") +
				"</strong>: " +
				frappe.utils.escape_html(d.company) +
				" &nbsp;|&nbsp; <strong>" +
				__("Posting Date") +
				"</strong>: " +
				frappe.utils.escape_html(d.posting_date) +
				"</p>";
			html += '<table class="table table-bordered"><thead><tr>';
			html +=
				"<th>" +
				__("Account") +
				"</th><th>" +
				__("Party") +
				"</th><th>" +
				__("Reference") +
				"</th><th class='text-end'>" +
				__("Debit") +
				"</th><th class='text-end'>" +
				__("Credit") +
				"</th></tr></thead><tbody>";
			(d.accounts || []).forEach((a) => {
				const ref =
					(a.reference_type && a.reference_name
						? a.reference_type + " / " + a.reference_name
						: "") || "";
				html +=
					"<tr><td>" +
					frappe.utils.escape_html(a.account || "") +
					"</td><td>" +
					frappe.utils.escape_html((a.party_type ? a.party_type + ": " : "") + (a.party || "")) +
					"</td><td>" +
					frappe.utils.escape_html(ref) +
					"</td><td class='text-end'>" +
					format_currency(a.debit_in_account_currency) +
					"</td><td class='text-end'>" +
					format_currency(a.credit_in_account_currency) +
					"</td></tr>";
			});
			html += "</tbody></table>";
			html +=
				"<p class='text-muted'>" +
				__("This is a preview only; no Journal Entry was created.") +
				"</p>";
			frappe.msgprint({ title: __("Preview Settlement Entry"), message: html, wide: true });
		},
	});
}

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
	settlement_type(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.settlement_type === SETTLEMENT_PI) {
			frappe.model.set_value(cdt, cdn, "purchase_order", "");
			frappe.model.set_value(cdt, cdn, "supplier_advance_account", "");
		} else {
			frappe.model.set_value(cdt, cdn, "purchase_invoice", "");
			frappe.model.set_value(cdt, cdn, "outstanding_amount", 0);
		}
		frm.trigger("recalc_totals");
	},
	purchase_invoice(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if ((row.settlement_type || SETTLEMENT_PI) !== SETTLEMENT_PI) {
			return;
		}
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
	purchase_order(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if ((row.settlement_type || SETTLEMENT_PI) !== SETTLEMENT_SA) {
			return;
		}
		if (!row.purchase_order) {
			frappe.model.set_value(cdt, cdn, "supplier", "");
			frm.trigger("recalc_totals");
			return;
		}
		frappe.db.get_value("Purchase Order", row.purchase_order, "supplier", (r) => {
			if (r) {
				frappe.model.set_value(cdt, cdn, "supplier", r.supplier);
			}
			frm.trigger("recalc_totals");
		});
	},
	allocated_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function settlement_lines_total(frm) {
	return (frm.doc.details || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
}

function allocated_on_other_pm_request_rows(frm, cdn) {
	let s = 0;
	(frm.doc.request_allocations || []).forEach((r) => {
		if (r.name !== cdn) {
			s += flt(r.allocated_amount);
		}
	});
	return s;
}

frappe.ui.form.on("PM Clearance Request Allocation", {
	pm_request(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (row.is_legacy_row) {
			return;
		}
		if (!frm.doc.employee || !frm.doc.company || !frm.doc.holder || !frm.doc.petty_cash_account) {
			frappe.msgprint(__("Select Employee/Holder first."));
			frappe.model.set_value(cdt, cdn, "pm_request", "");
			return;
		}
		if (!row.pm_request) {
			frappe.model.set_value(cdt, cdn, "request_amount", 0);
			frappe.model.set_value(cdt, cdn, "paid_amount", 0);
			frappe.model.set_value(cdt, cdn, "previously_allocated_amount", 0);
			frappe.model.set_value(cdt, cdn, "available_amount", 0);
			frm.trigger("recalc_totals");
			return;
		}
		frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.get_pm_request_allocation_context",
			args: {
				pm_request: row.pm_request,
				pm_clearance: frm.doc.name || null,
				company: frm.doc.company,
				employee: frm.doc.employee,
				holder: frm.doc.holder,
				petty_cash_account: frm.doc.petty_cash_account,
			},
			callback(r) {
				if (!r.message) return;
				const m = r.message;
				frappe.model.set_value(cdt, cdn, "request_amount", m.request_amount);
				frappe.model.set_value(cdt, cdn, "paid_amount", m.paid_amount);
				frappe.model.set_value(cdt, cdn, "previously_allocated_amount", m.previously_allocated_amount);
				frappe.model.set_value(cdt, cdn, "available_amount", m.available_amount);
				const settled = settlement_lines_total(frm);
				const other = allocated_on_other_pm_request_rows(frm, cdn);
				const remaining = Math.max(0, settled - other);
				const avail = flt(m.available_amount);
				if (remaining > 0) {
					const suggested = Math.min(avail, remaining);
					if (!flt(row.allocated_amount)) {
						frappe.model.set_value(cdt, cdn, "allocated_amount", suggested);
					}
				} else {
					frappe.model.set_value(cdt, cdn, "allocated_amount", "");
					frappe.msgprint(__("Total settlement is already fully allocated."));
				}
				frm.refresh_field("request_allocations");
				frm.trigger("recalc_totals");
			},
		});
	},
	allocated_amount(frm) {
		frm.trigger("recalc_totals");
	},
});

function flt(v) {
	return frappe.utils.flt(v);
}
