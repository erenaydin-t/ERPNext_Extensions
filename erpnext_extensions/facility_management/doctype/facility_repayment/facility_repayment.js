// Copyright (c) 2026, ERPNext Extensions contributors

const REPAYMENT_ACCOUNTS_AND_DIMENSIONS = [
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
	"cost_center",
	"department",
	"bank_dimension",
	"bank_account_dimension",
];

frappe.ui.form.on("Facility Repayment", {
	onload(frm) {
		if (frm.doc.docstatus === 0) {
			erpnext_extensions.facility_management.defaults.init_form(frm);
		}
	},
	refresh(frm) {
		recalculate_total_payment(frm);
		frm.set_query("facility", () => ({
			filters: { repayment_select: 1 },
		}));
		sync_repayment_accounts_dimensions_read_only(frm);
		if (frm.doc.docstatus === 0) {
			erpnext_extensions.facility_management.defaults.init_form(frm);
		}
		if (can_preview_repayment(frm)) {
			frm.add_custom_button(__("Preview Journal Entry"), () => preview_repayment_je(frm), __("Actions"));
		}
	},
	facility(frm) {
		recalculate_total_payment(frm);
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

function sync_repayment_accounts_dimensions_read_only(frm) {
	const read_only = frm.doc.docstatus !== 0 ? 1 : 0;
	REPAYMENT_ACCOUNTS_AND_DIMENSIONS.forEach((fieldname) => {
		if (frm.fields_dict[fieldname]) {
			frm.set_df_property(fieldname, "read_only", read_only);
		}
	});
}

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
