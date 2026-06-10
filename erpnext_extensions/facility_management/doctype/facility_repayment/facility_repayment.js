// Copyright (c) 2026, ERPNext Extensions contributors

frappe.ui.form.on("Facility Repayment", {
	refresh(frm) {
		recalculate_total_payment(frm);
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

function recalculate_total_payment(frm) {
	const total =
		flt(frm.doc.principal_amount) + flt(frm.doc.profit_amount) + flt(frm.doc.penalty_amount);
	// read_only Currency: do not use frm.set_value (triggers save/validation loop and stays 0 on desk)
	frm.doc.total_payment_amount = total;
	frm.refresh_field("total_payment_amount");
}
