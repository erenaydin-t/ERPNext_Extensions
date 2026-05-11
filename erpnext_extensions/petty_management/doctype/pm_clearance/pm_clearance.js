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
		if (!can_mutate_derived_fields(frm)) {
			setup_settlement_buttons(frm);
			return;
		}
		if (!frm.doc.employee || !frm.doc.company) {
			set_form_value_if_changed(frm, "holder", "");
			set_form_value_if_changed(frm, "petty_cash_account", "");
			set_form_value_if_changed(frm, "pending_amount", 0);
			set_form_value_if_changed(frm, "current_petty_balance", 0);
			set_form_value_if_changed(frm, "total_cleared_amount", 0);
			set_form_value_if_changed(frm, "total_funded_amount", 0);
			frm._pm_clearance_prev_holder = undefined;
			frm.trigger("recalc_totals");
			setup_settlement_buttons(frm);
			return;
		}
		if (frm.doc.company) {
			frappe.db.get_value("Company", frm.doc.company, "default_currency", (cur) => {
				if (!can_mutate_derived_fields(frm)) {
					return;
				}
				if (cur && cur.default_currency) {
					set_form_value_if_changed(frm, "currency", cur.default_currency);
				}
			});
		}
		frappe.db.get_value(
			"PM Holder",
			{ employee: frm.doc.employee, company: frm.doc.company, is_blocked: 0 },
			["name", "petty_cash_account", "current_balance", "consumed_amount", "pending_clearance_amount"],
			(r) => {
				if (!can_mutate_derived_fields(frm)) {
					setup_settlement_buttons(frm);
					return;
				}
				const prev = frm._pm_clearance_prev_holder;
				if (!r || !r.name) {
					set_form_value_if_changed(frm, "holder", "");
					set_form_value_if_changed(frm, "petty_cash_account", "");
					set_form_value_if_changed(frm, "pending_amount", 0);
					set_form_value_if_changed(frm, "current_petty_balance", 0);
					set_form_value_if_changed(frm, "total_cleared_amount", 0);
					set_form_value_if_changed(frm, "total_funded_amount", 0);
					if (prev) {
						(frm.doc.request_allocations || []).forEach((row) => {
							if (!row.is_legacy_row && row.pm_request) {
								clear_allocation_row(row);
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
							clear_allocation_row(row);
						}
					});
				}
				frm._pm_clearance_prev_holder = r.name;
				set_form_value_if_changed(frm, "holder", r.name);
				set_form_value_if_changed(frm, "petty_cash_account", r.petty_cash_account);
				set_form_value_if_changed(frm, "pending_amount", r.current_balance);
				set_form_value_if_changed(frm, "current_petty_balance", r.current_balance);
				set_form_value_if_changed(frm, "total_cleared_amount", r.consumed_amount || 0);
				set_form_value_if_changed(frm, "total_funded_amount", flt(r.current_balance) + flt(r.consumed_amount));
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
		pm_clearance_debug(frm, "refresh fired");
		frappe.workflow.setup(frm.doctype);
		if (frm.doc.employee && frm.doc.company && can_mutate_derived_fields(frm)) {
			frm.trigger("refresh_holder_pending");
		} else if ((!frm.doc.employee || !frm.doc.company) && can_mutate_derived_fields(frm)) {
			set_form_value_if_changed(frm, "holder", "");
			set_form_value_if_changed(frm, "petty_cash_account", "");
			set_form_value_if_changed(frm, "pending_amount", 0);
			set_form_value_if_changed(frm, "current_petty_balance", 0);
			set_form_value_if_changed(frm, "total_cleared_amount", 0);
			set_form_value_if_changed(frm, "total_funded_amount", 0);
			frm._pm_clearance_prev_holder = undefined;
			frm.trigger("recalc_totals");
			setup_settlement_buttons(frm);
		} else {
			update_settlement_balance_intro(
				frm,
				settlement_lines_total(frm),
				request_allocations_total(frm)
			);
			setup_settlement_buttons(frm);
		}
	},
	recalc_totals(frm) {
		let settled = 0;
		(frm.doc.details || []).forEach((r) => {
			settled += flt(r.allocated_amount);
		});
		const req_total = request_allocations_total(frm);
		if (can_mutate_derived_fields(frm)) {
			(frm.doc.details || []).forEach((r) => {
				set_child_value_if_changed(r.doctype, r.name, "amount_plus_tax", flt(r.allocated_amount));
			});
			set_form_value_if_changed(frm, "total_expense_without_tax", 0);
			set_form_value_if_changed(frm, "total_tax_amount", 0);
			set_form_value_if_changed(frm, "total_expense_amount", settled);
			set_form_value_if_changed(frm, "total_petty_cash", settled);
			set_form_value_if_changed(frm, "remaining_amount", flt(frm.doc.pending_amount) - settled);
			frm.refresh_field("details");
			frm.refresh_field("request_allocations");
		}
		update_settlement_balance_intro(frm, settled, req_total);
		setup_settlement_buttons(frm);
	},
});

function pm_clearance_debug(frm, message, data) {
	if (frappe.boot && frappe.boot.developer_mode) {
		console.warn(
			"[PM Clearance]",
			message,
			Object.assign(
				{
					name: frm.doc && frm.doc.name,
					docstatus: frm.doc && frm.doc.docstatus,
					workflow_state: frm.doc && frm.doc.workflow_state,
					status: frm.doc && frm.doc.status,
					journal_entry: frm.doc && frm.doc.journal_entry,
				},
				data || {}
			)
		);
	}
}

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

function escape_html(value) {
	const raw = value === undefined || value === null ? "" : String(value);
	if (frappe.utils && frappe.utils.escape_html) {
		return frappe.utils.escape_html(raw);
	}
	return raw.replace(/[&<>"']/g, (ch) => {
		return {
			"&": "&amp;",
			"<": "&lt;",
			">": "&gt;",
			'"': "&quot;",
			"'": "&#39;",
		}[ch];
	});
}

function form_is_dirty(frm) {
	return typeof frm.is_dirty === "function" ? frm.is_dirty() : !!frm.doc.__unsaved;
}

function can_mutate_derived_fields(frm) {
	return frm.doc.docstatus === 0 && (frm.is_new() || form_is_dirty(frm));
}

const NUMERIC_FIELDS = new Set([
	"allocated_amount",
	"amount_plus_tax",
	"available_amount",
	"current_petty_balance",
	"paid_amount",
	"pending_amount",
	"previously_allocated_amount",
	"remaining_amount",
	"request_amount",
	"total_cleared_amount",
	"total_expense_amount",
	"total_expense_without_tax",
	"total_funded_amount",
	"total_petty_cash",
	"total_tax_amount",
]);

function values_match(fieldname, current, incoming) {
	const cur = current === undefined || current === null ? "" : current;
	const next = incoming === undefined || incoming === null ? "" : incoming;
	if (cur === "" || next === "") {
		return String(cur) === String(next);
	}
	if (NUMERIC_FIELDS.has(fieldname)) {
		return Math.abs(flt(cur) - flt(next)) < 0.005;
	}
	return String(cur) === String(next);
}

function set_form_value_if_changed(frm, fieldname, value) {
	if (!values_match(fieldname, frm.doc[fieldname], value)) {
		frm.set_value(fieldname, value);
	}
}

function set_child_value_if_changed(cdt, cdn, fieldname, value) {
	const row = locals[cdt] && locals[cdt][cdn];
	if (row && !values_match(fieldname, row[fieldname], value)) {
		frappe.model.set_value(cdt, cdn, fieldname, value);
	}
}

function clear_allocation_row(row) {
	set_child_value_if_changed(row.doctype, row.name, "pm_request", "");
	set_child_value_if_changed(row.doctype, row.name, "allocated_amount", 0);
	set_child_value_if_changed(row.doctype, row.name, "request_amount", 0);
	set_child_value_if_changed(row.doctype, row.name, "paid_amount", 0);
	set_child_value_if_changed(row.doctype, row.name, "previously_allocated_amount", 0);
	set_child_value_if_changed(row.doctype, row.name, "available_amount", 0);
}

function preview_settlement_entry(frm) {
	pm_clearance_debug(frm, "preview clicked");
	const settled = (frm.doc.details || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
	if (!frm.doc.details || frm.doc.details.length === 0 || settled <= 0) {
		frappe.msgprint(__("Add at least one settlement line with amount to preview."));
		return;
	}
	const preview_args =
		frm.is_new() || form_is_dirty(frm) ? { doc: frm.doc } : { pm_clearance: frm.doc.name };
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
				escape_html(d.company) +
				" &nbsp;|&nbsp; <strong>" +
				__("Posting Date") +
				"</strong>: " +
				escape_html(d.posting_date) +
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
					escape_html(a.account || "") +
					"</td><td>" +
					escape_html((a.party_type ? a.party_type + ": " : "") + (a.party || "")) +
					"</td><td>" +
					escape_html(ref) +
					"</td><td class='text-end'>" +
					format_currency(a.debit_in_account_currency) +
					"</td><td class='text-end'>" +
					format_currency(a.credit_in_account_currency) +
					"</td></tr>";
			});
			html +=
				"<tr><td colspan='3' class='text-end'><strong>" +
				__("Totals") +
				"</strong></td><td class='text-end'><strong>" +
				format_currency(d.total_debit) +
				"</strong></td><td class='text-end'><strong>" +
				format_currency(d.total_credit) +
				"</strong></td></tr>";
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
	pm_clearance_debug(frm, "setup_settlement_buttons fired");
	frm.page.remove_inner_button(__("Preview Settlement Entry"));
	frm.page.remove_inner_button(__("Settle Petty Cash"));
	frm.page.remove_inner_button(__("Open Settlement Journal Entry"));

	const wf = frm.doc.workflow_state;
	const wfState = frappe.workflow.get_state ? frappe.workflow.get_state(frm.doc) : wf;
	const isApproved = wf === "Approved" || wfState === "Approved" || frm.doc.status === "Approved";
	const settlementTotal = settlement_lines_total(frm);
	const allocationTotal = request_allocations_total(frm);
	const hasSettlementLines = (frm.doc.details || []).length > 0 && settlementTotal > 0;
	const hasAllocationLines = (frm.doc.request_allocations || []).length > 0 && allocationTotal > 0;
	const totalsMatch = Math.abs(settlementTotal - allocationTotal) <= 0.005;

	if (hasSettlementLines && hasAllocationLines && totalsMatch) {
		pm_clearance_debug(frm, "button added", { button: "Preview Settlement Entry" });
		frm.page.add_inner_button(
			__("Preview Settlement Entry"),
			() => preview_settlement_entry(frm)
		);
	}
	const show_settle =
		!frm.is_new() && frm.doc.docstatus === 1 && isApproved && !frm.doc.journal_entry;

	if (frappe.boot.developer_mode && isApproved && !show_settle && !frm.doc.journal_entry) {
		console.warn("PM Clearance Settle Petty Cash button hidden", {
			docstatus: frm.doc.docstatus,
			workflow_state: frm.doc.workflow_state,
			status: frm.doc.status,
			journal_entry: frm.doc.journal_entry,
			total_expense_amount: frm.doc.total_expense_amount,
		});
	}

	if (show_settle) {
		pm_clearance_debug(frm, "button added", { button: "Settle Petty Cash" });
		const $btn = frm.page.add_inner_button(
			__("Settle Petty Cash"),
			() => {
				pm_clearance_debug(frm, "settle clicked");
				frappe.call({
					method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.settle_petty_cash",
					args: { pm_clearance: frm.doc.name },
					freeze: true,
					freeze_message: __("Settling petty cash…"),
					callback(r) {
						if (r.exc) return;
						const je = r.message && r.message.journal_entry;
						frappe.show_alert({
							message: je
								? __("Settlement Journal Entry {0} created", [je])
								: __("Settlement Journal Entry created"),
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
		pm_clearance_debug(frm, "button added", { button: "Open Settlement Journal Entry" });
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

function request_allocations_total(frm) {
	return (frm.doc.request_allocations || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
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
			set_child_value_if_changed(cdt, cdn, "request_amount", 0);
			set_child_value_if_changed(cdt, cdn, "paid_amount", 0);
			set_child_value_if_changed(cdt, cdn, "previously_allocated_amount", 0);
			set_child_value_if_changed(cdt, cdn, "available_amount", 0);
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
				set_child_value_if_changed(cdt, cdn, "request_amount", m.request_amount);
				set_child_value_if_changed(cdt, cdn, "paid_amount", m.paid_amount);
				set_child_value_if_changed(cdt, cdn, "previously_allocated_amount", m.previously_allocated_amount);
				set_child_value_if_changed(cdt, cdn, "available_amount", m.available_amount);
				const settled = settlement_lines_total(frm);
				const other = allocated_on_other_pm_request_rows(frm, cdn);
				const remaining = Math.max(0, settled - other);
				const avail = flt(m.available_amount);
				if (remaining > 0) {
					const suggested = Math.min(avail, remaining);
					if (!flt(row.allocated_amount)) {
						set_child_value_if_changed(cdt, cdn, "allocated_amount", suggested);
					}
				} else {
					set_child_value_if_changed(cdt, cdn, "allocated_amount", "");
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
