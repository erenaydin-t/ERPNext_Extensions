// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

/** Payment Request: Mode of Payment guidance + **Post Dated Cheque** placement live in
 * ``public/js/pdc_settlement_summary.js`` (`pdc_render_payment_request_path_ui`) so they run **after**
 * settlement summary / remaining capacity is known (avoids racing ERPNext **Create Payment Entry** vs PDC).
 */

/**
 * Fallback when desk boot did not list an active PR workflow (e.g. workflow added without full reload):
 * load Workflow into ``locals`` so ``has_workflow`` matches the database.
 * When ``boot.pdc_payment_request_has_active_workflow`` is true, ``pdc_settlement_summary.js`` patches
 * ``has_workflow`` and this fetch is skipped.
 */
function pdc_ensure_payment_request_workflow_in_locals(frm, done) {
	if (!frm || frm.doctype !== "Payment Request" || frm.is_new()) {
		if (typeof done === "function") done();
		return;
	}
	try {
		if (!frappe.meta.has_field("Payment Request", "workflow_state")) {
			if (typeof done === "function") done();
			return;
		}
	} catch (e) {
		if (typeof done === "function") done();
		return;
	}
	if (frappe.boot && frappe.boot.pdc_payment_request_has_active_workflow) {
		if (typeof done === "function") done();
		return;
	}
	if (frappe.model.has_workflow(frm.doctype)) {
		if (typeof done === "function") done();
		return;
	}
	frappe.call({
		method: "frappe.client.get_list",
		args: {
			doctype: "Workflow",
			filters: { document_type: frm.doctype, is_active: 1 },
			fields: ["name"],
			limit_page_length: 1,
		},
		callback: function (r) {
			const rows = (r && r.message) || [];
			if (!rows.length) {
				if (typeof done === "function") done();
				return;
			}
			frappe.model.with_doc("Workflow", rows[0].name, function () {
				try {
					if (
						frm &&
						frm.toolbar &&
						typeof frm.toolbar.set_primary_action === "function"
					) {
						frm.toolbar.set_primary_action();
					}
				} catch (e2) {
					// ignore
				}
				try {
					if (
						typeof erpnext_extensions !== "undefined" &&
						erpnext_extensions.cheque_management &&
						typeof erpnext_extensions.cheque_management
							.pdc_pr_after_toolbar_refresh === "function"
					) {
						setTimeout(
							() =>
								erpnext_extensions.cheque_management.pdc_pr_after_toolbar_refresh(
									frm
								),
							0
						);
					}
				} catch (e3) {
					// ignore
				}
				if (typeof done === "function") done();
			});
		},
	});
}

/**
 * After workflow renders, refresh settlement-driven toolbar (Create Post Dated Cheque / Payment Entry styling).
 *
 * **Do not** remove toolbar or menu rows by the label ``Submit`` on workflow-enabled forms. Workflow
 * transitions are added via ``frm.page.add_action_item`` (see ``frappe/form/workflow.js``) and can
 * legitimately be named ``Submit`` (e.g. Pending Finance Approval → Approved). Those rows live in the
 * **Actions** dropdown — indistinguishable from a duplicate by text alone.
 *
 * Frappe already suppresses the **standard** doc submit button when a workflow exists:
 * ``Toolbar.can_submit()`` requires ``!has_workflow()`` (``frappe/form/toolbar.js``), so the default
 * ``savesubmit`` primary is not shown for workflow PRs. Previous label-based stripping was redundant
 * and removed the real workflow action.
 */
function pdc_pr_schedule_settlement_toolbar_refresh(frm) {
	if (!frm || frm.doctype !== "Payment Request" || frm.is_new()) {
		return;
	}
	if (!frappe.model.has_workflow("Payment Request")) {
		return;
	}
	function refresh() {
		try {
			if (
				typeof erpnext_extensions !== "undefined" &&
				erpnext_extensions.cheque_management &&
				typeof erpnext_extensions.cheque_management.pdc_pr_after_toolbar_refresh ===
					"function"
			) {
				erpnext_extensions.cheque_management.pdc_pr_after_toolbar_refresh(frm);
			}
		} catch (e) {
			// ignore
		}
	}
	refresh();
	setTimeout(refresh, 120);
	setTimeout(refresh, 400);
	setTimeout(refresh, 650);
	setTimeout(refresh, 1100);
}

function pdc_unlock_payment_request_amount_in_draft(frm) {
	// Root cause: ERPNext Payment Request has `grand_total.read_only_depends_on = eval:doc.payment_reference.length>0`.
	// This is re-evaluated after refresh and after payment_reference grid changes, and it re-locks the field.
	// Robust fix: in Draft only, neutralize the depends-on and force-enable the control.
	if (!frm || !frm.doc) return;
	if (frm.doc.docstatus !== 0) return;

	try {
		const f = frm.get_field && frm.get_field("grand_total");
		if (f && f.df) {
			const nrefs = (frm.doc.payment_reference || []).length;
			if (nrefs > 1) {
				// Multiple rows: do not allow ambiguous total edits.
				f.df.read_only_depends_on = "eval:doc.payment_reference.length>0";
				f.df.read_only = 1;
			} else {
				// Single (or zero) row: allow editing total, but we'll keep row amount in sync.
				f.df.read_only_depends_on = null;
				f.df.read_only = 0;
			}
		}
	} catch (e) {
		// ignore
	}

	try {
		const nrefs = (frm.doc.payment_reference || []).length;
		const allow = nrefs <= 1;
		frm.set_df_property("grand_total", "read_only", allow ? 0 : 1);
		frm.toggle_enable("grand_total", allow);
		frm.refresh_field("grand_total");
	} catch (e) {
		// ignore
	}
}

function pdc_sum_payment_reference_amounts(frm) {
	let total = 0;
	(frm.doc.payment_reference || []).forEach((r) => {
		const v = parseFloat(r.amount);
		if (Number.isFinite(v)) total += v;
	});
	return total;
}

function pdc_sync_single_payment_reference_to_total(frm) {
	if (!frm || !frm.doc || frm.doc.docstatus !== 0) return;
	if (frm._pdc_syncing_pr_amount) return;
	const refs = frm.doc.payment_reference || [];
	if (refs.length !== 1) return;

	const row = refs[0];
	const gt = parseFloat(frm.doc.grand_total);
	if (!Number.isFinite(gt)) return;

	const cur = parseFloat(row.amount);
	if (Number.isFinite(cur) && Math.abs(cur - gt) < 1e-9) return;

	frm._pdc_syncing_pr_amount = true;
	try {
		// Use model setter when row has a name; fallback to direct mutation otherwise.
		if (row.name) {
			frappe.model.set_value(
				row.doctype || "Payment Request Payment Reference",
				row.name,
				"amount",
				gt
			);
		} else {
			row.amount = gt;
			frm.refresh_field("payment_reference");
		}
	} finally {
		frm._pdc_syncing_pr_amount = false;
	}
}

function pdc_schedule_unlock_payment_request_amount(frm) {
	// Schedule twice to survive late depends-on evaluation and grid refreshes.
	setTimeout(() => pdc_unlock_payment_request_amount_in_draft(frm), 0);
	setTimeout(() => pdc_unlock_payment_request_amount_in_draft(frm), 200);
}

frappe.ui.form.on("Payment Request", {
	onload_post_render(frm) {
		pdc_ensure_payment_request_workflow_in_locals(frm, function () {
			pdc_schedule_unlock_payment_request_amount(frm);
			pdc_pr_schedule_settlement_toolbar_refresh(frm);
		});
	},
	refresh(frm) {
		pdc_ensure_payment_request_workflow_in_locals(frm, function () {
			pdc_schedule_unlock_payment_request_amount(frm);
			pdc_pr_schedule_settlement_toolbar_refresh(frm);
		});
	},
	grand_total(frm) {
		if (!frm || !frm.doc || frm.doc.docstatus !== 0) return;
		const refs = frm.doc.payment_reference || [];
		if (refs.length === 1) {
			pdc_sync_single_payment_reference_to_total(frm);
		} else if (refs.length > 1 && !frm._pdc_syncing_pr_amount) {
			// Multiple rows: revert to explicit sum and inform the user.
			const sum = pdc_sum_payment_reference_amounts(frm);
			frm._pdc_syncing_pr_amount = true;
			try {
				frm.set_value("grand_total", sum);
			} finally {
				frm._pdc_syncing_pr_amount = false;
			}
			frappe.msgprint(
				__(
					"Amount cannot be edited while multiple Payment References exist. Edit the reference rows to change the total."
				)
			);
			pdc_schedule_unlock_payment_request_amount(frm);
		}
	},
});

// payment_reference grid edits often re-trigger depends-on evaluation; re-apply the Draft unlock.
frappe.ui.form.on("Payment Request Payment Reference", {
	payment_reference_add(frm) {
		pdc_schedule_unlock_payment_request_amount(frm);
	},
	payment_reference_remove(frm) {
		pdc_schedule_unlock_payment_request_amount(frm);
	},
	amount(frm) {
		// If a single row exists, keep total aligned to it; otherwise total is row-driven.
		if (frm && frm.doc && frm.doc.docstatus === 0 && !frm._pdc_syncing_pr_amount) {
			const refs = frm.doc.payment_reference || [];
			if (refs.length === 1) {
				const v = parseFloat(refs[0].amount);
				if (Number.isFinite(v)) {
					frm._pdc_syncing_pr_amount = true;
					try {
						frm.set_value("grand_total", v);
					} finally {
						frm._pdc_syncing_pr_amount = false;
					}
				}
			}
		}
		pdc_schedule_unlock_payment_request_amount(frm);
	},
});
