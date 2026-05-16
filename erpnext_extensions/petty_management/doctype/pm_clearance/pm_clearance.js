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
		frappe.call({
			method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.get_pm_clearance_holder_context",
			args: {
				employee: frm.doc.employee,
				company: frm.doc.company,
				posting_date: frm.doc.transaction_date,
			},
			callback(resp) {
				const r = resp.message || {};
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
				set_form_value_if_changed(frm, "total_funded_amount", r.total_funded_amount || 0);
				frm.trigger("recalc_totals");
				setup_settlement_buttons(frm);
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
		setup_settlement_buttons(frm);
		setTimeout(() => setup_settlement_buttons(frm), 120);
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
		const amt = flt(settled_total);
		const msg =
			amt > 0
				? __("Settlement lines and PM Request allocation totals match ({0}).", [format_currency(amt)])
				: __("Settlement lines and PM Request allocation totals match.");
		frm.set_intro(msg, "green");
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
	const settled = (frm.doc.details || []).reduce((s, r) => s + flt(r.allocated_amount), 0);
	if (!frm.doc.details || frm.doc.details.length === 0 || settled <= 0) {
		frappe.msgprint(__("Add at least one settlement line with amount to preview."));
		return;
	}
	const preview_args =
		frm.is_new() || form_is_dirty(frm)
			? { doc: JSON.stringify(frm.doc) }
			: { pm_clearance: frm.doc.name };
	frappe.call({
		method: "erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.preview_pm_clearance_settlement",
		args: preview_args,
		freeze: true,
		freeze_message: __("Building preview…"),
		callback(r) {
			if (!r.message) return;
			const d = r.message;
			const auto = d.auto_submit_journal_entry;
			const jeNote = auto
				? __("If you run Settle now, the Journal Entry will be created and submitted (per PM Settings).")
				: __(
						"If you run Settle now, the Journal Entry will be created as Draft until it is submitted manually."
				  );

			let html = '<div class="small">';
			html +=
				"<p><strong>" +
				__("Company") +
				"</strong>: " +
				escape_html(d.company) +
				"</p>";
			html +=
				"<p><strong>" +
				__("Posting Date") +
				"</strong>: " +
				escape_html(d.posting_date) +
				"</p>";
			html +=
				"<p><strong>" +
				__("PM Clearance") +
				"</strong>: " +
				escape_html(d.pm_clearance || frm.doc.name || "") +
				"</p>";
			html +=
				"<p><strong>" +
				__("Total Debit") +
				"</strong>: " +
				format_currency(d.total_debit) +
				" &nbsp;|&nbsp; <strong>" +
				__("Total Credit") +
				"</strong>: " +
				format_currency(d.total_credit) +
				"</p>";
			if (d.is_balanced === false) {
				html +=
					'<div class="alert alert-danger small">' +
					__("Debit and credit totals do not match (difference {0}).").format(
						format_currency(d.debit_credit_difference || 0)
					) +
					"</div>";
			}
			html += '<p class="alert alert-warning small mb-0">' + escape_html(jeNote) + "</p>";
			html += "</div>";

			const rows = d.accounts || [];
			const show_cc = rows.some((a) => (a.cost_center || "").trim());
			const show_proj = rows.some((a) => (a.project || "").trim());
			const show_party = rows.some((a) => (a.party_type || "").trim() || (a.party || "").trim());
			const show_ref = rows.some((a) => (a.reference_type || "").trim() || (a.reference_name || "").trim());

			html +=
				'<div class="table-responsive" style="max-width:100%;overflow-x:auto;">' +
				'<table class="table table-bordered table-sm table-hover mb-0" style="min-width:640px;font-size:12px;">' +
				"<thead><tr>" +
				"<th>" +
				__("Type") +
				"</th><th>" +
				__("Account") +
				"</th>";
			if (show_party) {
				html += "<th>" + __("Party Type") + "</th><th>" + __("Party") + "</th>";
			}
			if (show_ref) {
				html += "<th>" + __("Reference Type") + "</th><th>" + __("Reference") + "</th>";
			}
			html +=
				"<th class='text-end'>" +
				__("Debit") +
				"</th><th class='text-end'>" +
				__("Credit") +
				"</th>";
			if (show_cc) {
				html += "<th>" + __("Cost Center") + "</th>";
			}
			if (show_proj) {
				html += "<th>" + __("Project") + "</th>";
			}
			html += "</tr></thead><tbody>";
			rows.forEach((a) => {
				html += "<tr><td>" + escape_html(a.line_type || "") + "</td><td>" + escape_html(a.account || "") + "</td>";
				if (show_party) {
					html +=
						"<td>" +
						escape_html(a.party_type || "") +
						"</td><td>" +
						escape_html(a.party || "") +
						"</td>";
				}
				if (show_ref) {
					html +=
						"<td>" +
						escape_html(a.reference_type || "") +
						"</td><td>" +
						escape_html(a.reference_name || "") +
						"</td>";
				}
				html +=
					"<td class='text-end'>" +
					format_currency(a.debit_in_account_currency) +
					"</td><td class='text-end'>" +
					format_currency(a.credit_in_account_currency) +
					"</td>";
				if (show_cc) {
					html += "<td>" + escape_html(a.cost_center || "") + "</td>";
				}
				if (show_proj) {
					html += "<td>" + escape_html(a.project || "") + "</td>";
				}
				html += "</tr>";
			});
			let colSpan = 2 + (show_party ? 2 : 0) + (show_ref ? 2 : 0);
			html +=
				"<tr class='table-light'><td colspan='" +
				colSpan +
				"' class='text-end'><strong>" +
				__("Totals") +
				"</strong></td><td class='text-end'><strong>" +
				format_currency(d.total_debit) +
				"</strong></td><td class='text-end'><strong>" +
				format_currency(d.total_credit) +
				"</strong></td>";
			if (show_cc) {
				html += "<td></td>";
			}
			if (show_proj) {
				html += "<td></td>";
			}
			html += "</tr></tbody></table></div>";
			html +=
				"<p class='text-muted'>" +
				__("This is a preview only; no Journal Entry was created.") +
				"</p>";

			frappe.msgprint({
				title: __("Settlement Journal Entry Preview"),
				message: html,
				wide: true,
			});
		},
	});
}

function remove_pm_clearance_toolbar_buttons(frm) {
	const labels = ["Preview Settlement Entry", "Settle Petty Cash", "Open Settlement Journal Entry"];
	labels.forEach((raw) => {
		const L = __(raw);
		frm.remove_custom_button(L);
		frm.page.remove_inner_button(L);
		frm.page.remove_inner_button(raw);
	});
}
function sync_lifecycle_display_from_flags(frm, flags) {
	if (!flags) {
		return;
	}
	if (flags.lifecycle_state && frm.doc.status !== flags.lifecycle_state) {
		frm.doc.status = flags.lifecycle_state;
		frm.refresh_field("status");
	}
	if (flags.workflow_state && frm.doc.workflow_state !== flags.workflow_state) {
		frm.doc.workflow_state = flags.workflow_state;
		frm.refresh_field("workflow_state");
	}
}

function hide_workflow_reject_when_locked(frm, flags) {
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

function setup_settlement_buttons(frm) {
	remove_pm_clearance_toolbar_buttons(frm);

	if (frm.is_new()) {
		const run_preview = () => preview_settlement_entry(frm);
		frm.add_custom_button(__("Preview Settlement Entry"), run_preview);
		return;
	}

	frappe.call({
		method:
			"erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.get_pm_clearance_action_flags",
		args: { pm_clearance: frm.doc.name },
		callback(r) {
			const flags = r.message || {};
			sync_lifecycle_display_from_flags(frm, flags);
			hide_workflow_reject_when_locked(frm, flags);

			if (flags.can_preview) {
				frm.add_custom_button(__("Preview Settlement Entry"), () => preview_settlement_entry(frm));
			}
			if (flags.can_settle) {
				frm.add_custom_button(
					__("Settle Petty Cash"),
					() => {
						frappe.call({
							method:
								"erpnext_extensions.petty_management.doctype.pm_clearance.pm_clearance.settle_petty_cash",
							args: { pm_clearance: frm.doc.name },
							freeze: true,
							freeze_message: __("Settling petty cash…"),
							callback(res) {
								if (res.exc) return;
								const je = res.message && res.message.journal_entry;
								frappe.show_alert({
									message: je
										? __("Settlement Journal Entry {0} created", [je])
										: __("Settlement Journal Entry created"),
									indicator: "green",
								});
								frm.reload_doc();
							},
							error(res) {
								const msg =
									(res && res.message) ||
									(res &&
										res._server_messages &&
										frappe.utils.parse_json(res._server_messages)) ||
									__("Could not settle petty cash");
								frappe.msgprint({
									title: __("Settlement failed"),
									message: msg,
									indicator: "red",
								});
							},
						});
					},
					null
				);
				if (frm.change_custom_button_type) {
					frm.change_custom_button_type(__("Settle Petty Cash"), null, "primary");
				}
			}
			if (flags.can_open_je && flags.journal_entry) {
				frm.add_custom_button(__("Open Settlement Journal Entry"), () =>
					frappe.set_route("Form", "Journal Entry", flags.journal_entry)
				);
			}
		},
	});
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
					if (suggested <= 0) {
						frappe.msgprint(
							__(
								"No PM Request balance available for allocation (paid {0}, already reserved {1}).",
								[format_currency(m.paid_amount), format_currency(m.previously_allocated_amount)]
							)
						);
					} else if (!flt(row.allocated_amount)) {
						set_child_value_if_changed(cdt, cdn, "allocated_amount", suggested);
					}
				} else {
					set_child_value_if_changed(cdt, cdn, "allocated_amount", "");
					frappe.msgprint(__("Total settlement is already fully allocated on this clearance."));
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
	const parsed = parseFloat(v);
	return Number.isFinite(parsed) ? parsed : 0;
}
