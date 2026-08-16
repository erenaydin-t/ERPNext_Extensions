// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.ui.form.on("Asset Request", {
	setup(frm) {
		frm.set_query("requested_item_code", "items", () => ({
			filters: { is_fixed_asset: 1, disabled: 0, is_grouped_asset: 0 },
		}));
		frm.set_query("fulfilled_item_code", "items", () => ({
			filters: { is_fixed_asset: 1, disabled: 0, is_grouped_asset: 0 },
		}));
		frm.set_query("fulfilled_purchase_item", "items", () => ({
			filters: { is_fixed_asset: 1, disabled: 0, is_grouped_asset: 0 },
		}));
		frm.set_query("preferred_asset", "items", (doc, cdt, cdn) => {
			const row = locals[cdt][cdn] || {};
			return {
				filters: {
					company: doc.company,
					docstatus: 1,
					item_code: row.fulfilled_item_code || row.requested_item_code || undefined,
				},
			};
		});
		frm.set_query("cost_center", () => ({ filters: { company: frm.doc.company, is_group: 0 } }));
		frm.set_query("employee", () => ({ filters: { company: frm.doc.company, status: "Active" } }));
	},
	onload(frm) {
		if (frm.is_new() && !frm.doc.employee) {
			frappe.db.get_value("Employee", { user_id: frappe.session.user, status: "Active" }, "name", (r) => {
				if (r && r.name) {
					frm.set_value("employee", r.name);
				}
			});
		}
	},
	refresh(frm) {
		frm.trigger("toggle_fulfillment_buttons");
	},
	toggle_fulfillment_buttons(frm) {
		if (frm.doc.docstatus !== 1) {
			return;
		}
		const can_fulfill = frappe.user_roles.includes("Asset Manager") || frappe.user_roles.includes("System Manager");
		if (!can_fulfill) {
			return;
		}
		frm.add_custom_button(__("Re-evaluate Availability"), () => {
			frappe.call({
				method: "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.reevaluate_fulfillment",
				args: { name: frm.doc.name },
				freeze: true,
				callback(r) {
					frm.reload_doc();
					if (r.message) {
						frappe.show_alert({ message: __("Fulfillment updated"), indicator: "green" });
					}
				},
			});
		});
		frm.add_custom_button(__("Create Asset Movement"), () => {
			frappe.call({
				method: "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.create_asset_movement",
				args: { name: frm.doc.name },
				freeze: true,
				callback(r) {
					frm.reload_doc();
					if (r.message && r.message.asset_movement) {
						frappe.set_route("Form", "Asset Movement", r.message.asset_movement);
					}
				},
			});
		});
		frm.add_custom_button(__("Create Material Request"), () => {
			frappe.call({
				method: "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.create_material_request",
				args: { name: frm.doc.name },
				freeze: true,
				callback(r) {
					frm.reload_doc();
					if (r.message && r.message.material_request) {
						frappe.set_route("Form", "Material Request", r.message.material_request);
					}
				},
			});
		});
	},
});

frappe.ui.form.on("Asset Request Item", {
	requested_item_code(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (!row.fulfilled_item_code && row.requested_item_code) {
			frappe.model.set_value(cdt, cdn, "fulfilled_item_code", row.requested_item_code);
		}
		refresh_available_qty(frm, cdt, cdn);
	},
	fulfilled_item_code(frm, cdt, cdn) {
		refresh_available_qty(frm, cdt, cdn);
	},
	qty(frm, cdt, cdn) {
		const row = locals[cdt][cdn];
		if (flt(row.qty) < 1) {
			frappe.model.set_value(cdt, cdn, "qty", 1);
		}
	},
});

function refresh_available_qty(frm, cdt, cdn) {
	const row = locals[cdt][cdn];
	if (!frm.doc.company || !row.requested_item_code) {
		return;
	}
	frappe.call({
		method: "erpnext_extensions.asset_usage_depreciation.doctype.asset_request.asset_request.get_available_asset_count",
		args: {
			company: frm.doc.company,
			requested_item_code: row.requested_item_code,
			requested_asset_category: row.requested_asset_category,
			fulfilled_item_code: row.fulfilled_item_code,
			exclude_request: frm.doc.name,
		},
		callback(r) {
			frappe.model.set_value(cdt, cdn, "available_qty", r.message || 0);
		},
	});
}
