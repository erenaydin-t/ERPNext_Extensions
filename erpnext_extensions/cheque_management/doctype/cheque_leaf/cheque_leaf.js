function can_show_void_cheque_leaf_button(frm) {
	if (!frm.doc || frm.is_new()) {
		return false;
	}
	const st = (frm.doc.status || "").trim();
	if (st !== "Available") {
		return false;
	}
	if ((frm.doc.linked_post_dated_cheque || "").trim()) {
		return false;
	}
	if ((frm.doc.reserved_by_pdc || "").trim()) {
		return false;
	}
	return true;
}

frappe.ui.form.on("Cheque Leaf", {
	_apply_master_lock_ui(frm) {
		const locked = !!(frm.doc && frm.doc.name) && !frm.is_new();
		const locked_fields = ["company", "bank_account", "cheque_book", "cheque_number", "sequence_no"];
		locked_fields.forEach((fn) => frm.set_df_property(fn, "read_only", locked ? 1 : 0));

		// Status is lifecycle-driven; keep it read-only in the UI.
		frm.set_df_property("status", "read_only", locked ? 1 : 0);

		const is_void = frm.doc.status === "Void";
		frm.set_df_property("void_reason", "read_only", is_void ? 1 : 0);
		frm.set_df_property("void_attachment", "read_only", is_void ? 1 : 0);
	},

	_void_cheque_leaf(frm) {
		const d = new frappe.ui.Dialog({
			title: "Void Cheque Leaf",
			fields: [
				{
					fieldname: "void_reason",
					fieldtype: "Small Text",
					label: __("Void Reason / دلیل مخدوش شدن"),
					reqd: 1,
				},
				{
					fieldname: "void_attachment",
					fieldtype: "Attach",
					label: __("Void Attachment"),
				},
			],
			primary_action_label: __("Confirm Void"),
			primary_action(values) {
				const reason = (values.void_reason || "").trim();
				if (!reason) {
					frappe.msgprint(__("Void reason is required."));
					return;
				}
				d.hide();
				frappe.call({
					method:
						"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.void_cheque_leaf",
					args: {
						leaf_name: frm.doc.name,
						reason: reason,
						void_attachment: values.void_attachment || null,
					},
					freeze: true,
					callback(r) {
						if (r.message) {
							frm.reload_doc().then(() => frm.refresh());
							frappe.show_alert({ message: __("Cheque leaf voided."), indicator: "green" });
						}
					},
				});
			},
		});
		d.show();
	},

	refresh(frm) {
		frm.trigger("_apply_master_lock_ui");
		frm.clear_custom_buttons();
		if (can_show_void_cheque_leaf_button(frm)) {
			frm.add_custom_button("Void Cheque Leaf", () => {
				frm.trigger("_void_cheque_leaf");
			});
		}
	},
});

frappe.listview_settings["Cheque Leaf"] = {
	get_indicator(doc) {
		const status = (doc.status || "").trim();
		const color_map = {
			Available: "green",
			Reserved: "orange",
			Used: "blue",
			Void: "red",
		};
		return [__(status), color_map[status] || "gray", `status,=,${status}`];
	},
};
