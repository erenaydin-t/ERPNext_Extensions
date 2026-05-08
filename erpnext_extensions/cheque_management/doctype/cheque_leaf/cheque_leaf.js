frappe.ui.form.on("Cheque Leaf", {
	_apply_master_lock_ui(frm) {
		const locked = !!(frm.doc && frm.doc.name) && !frm.is_new();
		const locked_fields = ["company", "bank_account", "cheque_book", "cheque_number", "sequence_no"];
		locked_fields.forEach((fn) => frm.set_df_property(fn, "read_only", locked ? 1 : 0));

		// Status is lifecycle-driven; keep it read-only in the UI.
		frm.set_df_property("status", "read_only", locked ? 1 : 0);
	},

	refresh(frm) {
		frm.trigger("_apply_master_lock_ui");
	},
});

