// Administrator-only: delete imported Post Dated Cheque from Cheque Opening Import rows.
(function () {
	"use strict";

	window.erpnext_extensions = window.erpnext_extensions || {};
	window.erpnext_extensions.cheque_opening_import =
		window.erpnext_extensions.cheque_opening_import || {};
	const ns = window.erpnext_extensions.cheque_opening_import;

	const PREVIEW_METHOD =
		"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.preview_delete_imported_pdc";
	const DELETE_METHOD =
		"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.delete_imported_pdc_from_ui";
	const MAY_DELETE_METHOD =
		"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.user_may_delete_imported_pdc_ui";

	ns._coi_may_delete_pdc = null;

	ns.ensure_may_delete_pdc = async function () {
		if (ns._coi_may_delete_pdc !== null) return ns._coi_may_delete_pdc;
		try {
			const r = await frappe.call({ method: MAY_DELETE_METHOD });
			ns._coi_may_delete_pdc = !!(r && r.message);
		} catch (e) {
			ns._coi_may_delete_pdc = false;
		}
		return ns._coi_may_delete_pdc;
	};

	function pdc_from_row(row) {
		return (row && (row.imported_pdc || row.post_dated_cheque)) || "";
	}

	function audit_html(preview) {
		const s = preview.audit_summary || {};
		const blockers = preview.blockers || [];
		const lines = [
			`<b>${__("PDC")}:</b> ${frappe.utils.escape_html(preview.pdc_name || "")}`,
			`<b>${__("Cheque Opening Import")}:</b> ${frappe.utils.escape_html(
				preview.cheque_opening_import || ""
			)}`,
			`<b>${__("Row number")}:</b> ${preview.row_number ?? ""}`,
			`<b>${__("Cheque number")}:</b> ${frappe.utils.escape_html(
				(preview.pdc && preview.pdc.cheque_no) || ""
			)}`,
			`<b>${__("Amount")}:</b> ${(preview.pdc && preview.pdc.cheque_amount) ?? ""}`,
			`<b>${__("Workflow state")}:</b> ${frappe.utils.escape_html(
				(preview.pdc && preview.pdc.workflow_state) || ""
			)}`,
			`<b>${__("Docstatus")}:</b> ${(preview.pdc && preview.pdc.docstatus) ?? ""}`,
			"<hr>",
			`<b>${__("Safety audit")}</b>`,
			`${__("PDC Journal References")}: ${s.journal_references_count ?? 0}`,
			`${__("Journal Entries")}: ${s.journal_entries_count ?? 0}`,
			`${__("GL Entries")}: ${s.gl_entry_count ?? 0}`,
			`${__("Payment Ledger Entries")}: ${s.payment_ledger_entry_count ?? 0}`,
			`${__("Other blockers")}: ${s.blockers_count ?? 0}`,
		];
		if (blockers.length) {
			lines.push("<hr>", `<b>${__("Blockers")}</b>`);
			blockers.forEach((b) => {
				lines.push(`• ${frappe.utils.escape_html(b)}`);
			});
		}
		return lines.join("<br>");
	}

	ns.open_delete_imported_pdc_dialog = async function (pdc_name, parent_frm) {
		if (!pdc_name) return;
		frappe.dom.freeze(__("Loading safety audit…"));
		let preview;
		try {
			const r = await frappe.call({
				method: PREVIEW_METHOD,
				args: { pdc_name },
			});
			preview = (r && r.message) || {};
		} catch (e) {
			frappe.dom.unfreeze();
			frappe.msgprint({
				title: __("Delete Imported PDC"),
				message: e?.message || __("Unable to load preview."),
				indicator: "red",
			});
			return;
		} finally {
			frappe.dom.unfreeze();
		}

		const safeToDelete = !!preview.allowed;
		const fields = [
			{
				fieldtype: "HTML",
				fieldname: "audit_html",
				options: audit_html(preview),
			},
		];
		if (safeToDelete) {
			fields.push({
				fieldtype: "Small Text",
				fieldname: "reason",
				label: __("Reason"),
				reqd: 1,
			});
		}

		const d = new frappe.ui.Dialog({
			title: __("Delete Imported PDC"),
			fields,
			primary_action_label: safeToDelete ? __("Confirm Delete") : __("Close"),
			primary_action: async function () {
				if (!safeToDelete) {
					d.hide();
					return;
				}
				const reason = (d.get_value("reason") || "").trim();
				if (!reason) {
					frappe.msgprint(__("Reason is required."));
					return;
				}
				d.get_primary_btn().prop("disabled", true);
				frappe.dom.freeze(__("Deleting imported PDC…"));
				try {
					await frappe.call({
						method: DELETE_METHOD,
						args: { pdc_name, reason },
					});
					d.hide();
					frappe.show_alert({
						message: __("Imported PDC deleted successfully."),
						indicator: "green",
					});
					if (parent_frm) {
						await parent_frm.reload_doc();
						parent_frm.refresh_field("items");
					} else if (
						window.cur_frm?.doc?.doctype === "Post Dated Cheque" &&
						window.cur_frm.doc.name === pdc_name
					) {
						const coi = preview.cheque_opening_import;
						if (coi) {
							frappe.set_route("Form", "Cheque Opening Import", coi);
						} else {
							frappe.set_route("List", "Post Dated Cheque");
						}
					}
				} catch (e) {
					frappe.msgprint({
						title: __("Delete failed"),
						message: e?.message || __("Delete failed."),
						indicator: "red",
					});
				} finally {
					frappe.dom.unfreeze();
					d.get_primary_btn().prop("disabled", false);
				}
			},
		});
		d.show();
	};

	ns.setup_delete_imported_pdc_actions = async function (frm) {
		if (frm.is_new()) return;
		const may = await ns.ensure_may_delete_pdc();
		if (!may) return;

		const rows_with_pdc = (frm.doc.items || [])
			.map((r) => ({ row: r, pdc: pdc_from_row(r) }))
			.filter((x) => x.pdc);

		if (!rows_with_pdc.length) return;

		frm.add_custom_button(__("Delete Imported PDC…"), () => {
				const options = rows_with_pdc.map((x) => ({
					label: `${__("Row")} ${x.row.row_number || "?"} — ${x.pdc}`,
					value: x.pdc,
				}));
				if (options.length === 1) {
					ns.open_delete_imported_pdc_dialog(options[0].value, frm);
					return;
				}
				const pick = new frappe.ui.Dialog({
					title: __("Delete Imported PDC"),
					fields: [
						{
							fieldtype: "Select",
							fieldname: "pdc_name",
							label: __("Imported Post Dated Cheque"),
							options: options.map((o) => o.value),
							reqd: 1,
						},
					],
					primary_action_label: __("Continue"),
					primary_action: function () {
						const pdc = pick.get_value("pdc_name");
						pick.hide();
						if (pdc) ns.open_delete_imported_pdc_dialog(pdc, frm);
					},
				});
				pick.show();
			}
		);
	};

	ns.setup_delete_imported_pdc_on_pdc_form = async function (frm) {
		if (!frm.doc.name || !cint(frm.doc.is_opening_import)) {
			return;
		}
		const may = await ns.ensure_may_delete_pdc();
		if (!may) {
			return;
		}
		frm.add_custom_button(__("Delete Imported PDC"), () => {
			ns.open_delete_imported_pdc_dialog(frm.doc.name, null);
		});
	};

	function cint(v) {
		return parseInt(v, 10) || 0;
	}

	frappe.ui.form.on("Cheque Opening Import Item", {
		form_render(frm) {
			(async () => {
				const may = await ns.ensure_may_delete_pdc();
				if (!may) return;
				const pdc = pdc_from_row(frm.doc);
				if (!pdc) return;
				frm.add_custom_button(__("Delete Imported PDC"), () => {
					const parent_frm = frm.parent_frm;
					ns.open_delete_imported_pdc_dialog(pdc, parent_frm);
				});
			})().catch((e) => console.error("COI delete PDC row action", e));
		},
	});
})();
