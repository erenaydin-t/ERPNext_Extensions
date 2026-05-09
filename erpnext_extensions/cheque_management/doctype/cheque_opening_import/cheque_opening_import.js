frappe.ui.form.on("Cheque Opening Import", {
	onload(frm) {
		frm._coi_prev_import_file = frm.doc.import_file || "";
	},

	import_file(frm) {
		// Clear stale preview/import results when file is cleared or replaced.
		const prev = frm._coi_prev_import_file || "";
		const cur = frm.doc.import_file || "";
		if (cur === prev) return;

		frm._coi_prev_import_file = cur;

		frm.clear_table("items");
		frm.set_value("summary", "");
		frm.set_value("import_status", "Draft");

		frm.refresh_field("items");
		frm.refresh_field("summary");
		frm.refresh_field("import_status");
	},

	refresh(frm) {
		// Inline template button is rendered via `hooks.py` asset:
		// `public/js/cheque_opening_import_inline_template.js`.
		// This file is auto-loaded by Frappe from the doctype folder; keep it minimal
		// and never declare top-level const/let to avoid double-load issues.
		try {
			const render =
				window?.erpnext_extensions?.cheque_opening_import?.render_inline_template_actions;
			if (typeof render === "function") render(frm);
		} catch (e) {
			console.error("Cheque Opening Import: refresh failed", e);
		}

		// Desk shells `.custom-actions` with `hidden-xs hidden-md` for Preview/Execute.
		if (frm.page?.custom_actions?.length) {
			frm.page.custom_actions.removeClass("hide hidden-xs hidden-md");
		}

		if (frm.is_new()) {
			frm.dashboard.set_headline(
				__(
					"Use **Download Template** for the exact column layout and guidance. Save with your filled file, then **Preview** and **Execute Import**."
				)
			);
			return;
		}
		frm.dashboard.clear_headline();

		const status = (frm.doc.import_status || "Draft").trim();
		const is_completed = ["Completed", "Completed With Errors"].includes(status);

		// Read-only UX after completion
		frm.set_df_property("import_file", "read_only", is_completed ? 1 : 0);
		frm.set_df_property("items", "read_only", is_completed ? 1 : 0);

		const has_valid_row = (frm.doc.items || []).some((r) => (r.row_status || "") === "Valid");

		// Buttons:
		// - Draft/Previewed: show Preview
		// - Previewed + at least one Valid row: show Execute Import
		// - Completed/Completed With Errors: hide both
		if (!is_completed) {
			frm.add_custom_button(__("Preview"), async () => {
				frappe.show_alert({ message: __("Preview started"), indicator: "blue" });
				frappe.dom.freeze(__("Parsing file…"));
				try {
					const r = await frm.call("preview");
					const m = (r && r.message) || {};

					await frm.reload_doc();
					frm.refresh_field("items");
					frm.refresh_field("summary");
					frm.refresh_field("import_status");

					frappe.show_alert(
						{
							message: __("Preview completed: {0} row(s)", [m.total ?? 0]),
							indicator: (m.failed || 0) > 0 ? "orange" : "green",
						},
						8
					);
				} catch (e) {
					console.error("Cheque Opening Import: Preview failed", e);
					frappe.show_alert({ message: __("Preview failed"), indicator: "red" }, 10);
					frappe.msgprint({
						title: __("Preview failed"),
						message: e?.message ? __(e.message) : __("Check console for details."),
						indicator: "red",
					});
				} finally {
					frappe.dom.unfreeze();
				}
			});
		}

		if (status === "Previewed" && has_valid_row) {
			frm.add_custom_button(
				__("Execute Import"),
				async () => {
					const confirmed = await new Promise((resolve) => {
						frappe.confirm(
							__(
								"Create Post Dated Cheque documents from the attached file? Each row runs in its own database transaction; failures roll back that row only."
							),
							() => resolve(true),
							() => resolve(false)
						);
					});
					if (!confirmed) return;

					frappe.dom.freeze(__("Importing…"));
					try {
						const r = await frm.call("execute_import");
						const m = (r && r.message) || {};
						await frm.reload_doc();
						frm.refresh_field("items");
						frm.refresh_field("summary");
						frm.refresh_field("import_status");

						frappe.msgprint({
							title: __("Import finished"),
							message: __("Imported: {0} · Failed: {1} · Total: {2}", [
								m.imported ?? 0,
								m.failed ?? 0,
								m.total ?? 0,
							]),
							indicator: (m.failed || 0) > 0 ? "orange" : "green",
						});
						frappe.show_alert(
							{
								message: __("Import finished: {0} imported, {1} failed", [
									m.imported ?? 0,
									m.failed ?? 0,
								]),
								indicator: (m.failed || 0) > 0 ? "orange" : "green",
							},
							10
						);
					} catch (e) {
						console.error("Cheque Opening Import: Execute Import failed", e);
						frappe.msgprint({
							title: __("Import failed"),
							message: e?.message ? __(e.message) : __("Check console for details."),
							indicator: "red",
						});
					} finally {
						frappe.dom.unfreeze();
					}
				},
				__("Actions")
			);
		}
	},
});
