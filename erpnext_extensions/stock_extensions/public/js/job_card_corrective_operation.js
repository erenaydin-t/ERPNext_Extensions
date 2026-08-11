// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT
//
// Job Card · Corrective Job Card, restored for the semi-finished-goods flow
//
// v16 did not remove corrective operations. The doctype, the fields and
// erpnext…job_card.make_corrective_job_card are all still there and all still
// work. The stock form script simply stops offering the button:
//
//     if (doc.docstatus == 1 && !doc.is_corrective_job_card && !doc.finished_good)
//
// Every Job Card here declares a finished_good — that is what per-operation
// semi-finished tracking means — so the button never appears on any of them.
// This puts it back, without touching the stock script.
//
// Two things the stock dialog gets wrong for this flow, corrected here:
//   * for_quantity is copied from the original card, and ERPNext then refuses
//     the insert because the corrective operation has no quantity on the Work
//     Order. The operator is asked how many units are being reworked instead.
//   * the material list is copied wholesale (33 rows on a real product). A
//     rework is not a re-issue of the whole formulation, so it starts empty
//     and the operator adds only what the rework actually consumes.

frappe.ui.form.on("Job Card", {
	refresh(frm) {
		const doc = frm.doc;
		if (doc.docstatus !== 1) return;
		if (doc.is_corrective_job_card) return;
		if (!doc.finished_good) return; // stock script already offers it

		// Idempotent: a site Client Script may already have added this button
		// while the app version was being rolled out, and two identical
		// buttons under Make is worse than none.
		frm.remove_custom_button(__("Corrective Job Card"), __("Make"));

		frm.add_custom_button(
			__("Corrective Job Card"),
			() => {
				const operations = (doc.sub_operations || [])
					.map((d) => d.sub_operation)
					.concat(doc.operation);

				frappe.prompt(
					[
						{
							fieldtype: "Link",
							label: __("Corrective Operation"),
							options: "Operation",
							fieldname: "operation",
							reqd: 1,
							get_query: () => ({
								filters: { is_corrective_operation: 1 },
							}),
						},
						{
							fieldtype: "Link",
							label: __("For Operation"),
							options: "Operation",
							fieldname: "for_operation",
							reqd: 1,
							default: doc.operation,
							get_query: () => ({
								filters: { name: ["in", operations] },
							}),
						},
						{
							fieldtype: "Float",
							label: __("Quantity To Rework"),
							fieldname: "qty",
							reqd: 1,
							description: __(
								"How many units are being reworked — not the batch size."
							),
						},
					],
					(d) => {
						frappe.call({
							method: "erpnext.manufacturing.doctype.job_card.job_card.make_corrective_job_card",
							args: {
								source_name: doc.name,
								operation: d.operation,
								for_operation: d.for_operation,
							},
							freeze: true,
							callback(r) {
								if (!r.message) return;
								const cjc = r.message;
								cjc.for_quantity = d.qty;
								// Rework consumes what the operator adds, not
								// the whole formulation again.
								cjc.items = [];
								frappe.model.sync(cjc);
								frappe.set_route("Form", cjc.doctype, cjc.name);
							},
						});
					},
					__("Corrective Job Card"),
					__("Create")
				);
			},
			__("Make")
		);
	},
});
