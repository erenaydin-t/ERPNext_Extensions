// Copyright (c) 2026, ERPNext Extensions contributors

frappe.ui.form.on("Facility Repayment", {
	refresh(frm) {
		recalculate_total_payment(frm);
		frm.set_query("facility", () => ({
			filters: { repayment_select: 1 },
		}));
		if (can_preview_repayment(frm)) {
			frm.add_custom_button(__("Preview Journal Entry"), () => preview_repayment_je(frm), __("Actions"));
		}
	},
	facility(frm) {
		recalculate_total_payment(frm);
		if (!frm.doc.facility) {
			return;
		}
		const fac = frm.doc.facility;
		frappe.flags._facility_repayment_interest_user_set = frappe.flags._facility_repayment_interest_user_set || {};
		delete frappe.flags._facility_repayment_interest_user_set[frm.doc.name || frm.doc.localname];
		frappe.db.get_value("Facility", fac, "interest_expense_account").then((r) => {
			if (frm.doc.facility !== fac) {
				return;
			}
			const key = frm.doc.name || frm.doc.localname;
			if (frappe.flags._facility_repayment_interest_user_set[key]) {
				return;
			}
			const account = r?.message?.interest_expense_account;
			if (account) {
				frm.set_value("interest_expense_account", account);
			}
		});
	},
	interest_expense_account(frm) {
		const key = frm.doc.name || frm.doc.localname;
		frappe.flags._facility_repayment_interest_user_set =
			frappe.flags._facility_repayment_interest_user_set || {};
		frappe.flags._facility_repayment_interest_user_set[key] = 1;
	},
	principal_amount(frm) {
		recalculate_total_payment(frm);
	},
	profit_amount(frm) {
		recalculate_total_payment(frm);
	},
	penalty_amount(frm) {
		recalculate_total_payment(frm);
	},
});

function can_preview_repayment(frm) {
	if (frm.doc.docstatus !== 0 || !frm.doc.facility) {
		return false;
	}
	const total =
		flt(frm.doc.principal_amount) + flt(frm.doc.profit_amount) + flt(frm.doc.penalty_amount);
	return total > 0;
}

function recalculate_total_payment(frm) {
	const total =
		flt(frm.doc.principal_amount) + flt(frm.doc.profit_amount) + flt(frm.doc.penalty_amount);
	frm.doc.total_payment_amount = total;
	frm.refresh_field("total_payment_amount");
}

function preview_repayment_je(frm) {
	frappe.call({
		method:
			"erpnext_extensions.facility_management.doctype.facility_repayment.facility_repayment.preview_repayment_journal_entry",
		args: { doc: frm.doc },
		freeze: true,
		callback(r) {
			erpnext_extensions.facility_management.je_preview.show_facility_je_preview_dialog(
				r.message,
				__("Repayment Journal Entry Preview")
			);
		},
	});
}
