frappe.ui.form.on("Cheque Book", {
	async _has_any_leaves(frm) {
		if (!frm.doc || frm.is_new()) {
			return false;
		}
		// Use a stable cache per docname to avoid repeated calls on refresh.
		frm._cheque_book_has_leaves_cache = frm._cheque_book_has_leaves_cache || {};
		if (frm._cheque_book_has_leaves_cache[frm.doc.name] !== undefined) {
			return frm._cheque_book_has_leaves_cache[frm.doc.name];
		}
		const exists = await frappe.db.exists("Cheque Leaf", { cheque_book: frm.doc.name });
		frm._cheque_book_has_leaves_cache[frm.doc.name] = !!exists;
		return !!exists;
	},
	_apply_generation_lock_ui(frm) {
		const locked =
			(frm.doc.generated_leaves_count || 0) > 0 || !!frm._cheque_book_has_any_leaves;
		const locked_fields = [
			"company",
			"bank_account",
			"generation_mode",
			"prefix",
			"start_number",
			"end_number",
			"number_width",
		];
		locked_fields.forEach((fn) => {
			frm.set_df_property(fn, "read_only", locked ? 1 : 0);
		});
	},
	company(frm) {
		// Keep bank_account consistent with selected company.
		if (frm.doc.bank_account) {
			frappe.db
				.get_value("Bank Account", frm.doc.bank_account, ["company", "is_company_account"])
				.then((r) => {
					const m = (r && r.message) || {};
					if (m.company && frm.doc.company && m.company !== frm.doc.company) {
						frm.set_value("bank_account", "");
					}
				});
		}
	},
	setup(frm) {
		frm.set_query("bank_account", function () {
			const company = frm.doc.company;
			const filters = {};
			if (company) {
				filters.company = company;
			}
			// If the field exists in this ERPNext version, it will be applied; otherwise ignored by link query.
			filters.is_company_account = 1;
			return { filters };
		});
	},
	refresh(frm) {
		if (!frm.doc || frm.is_new()) {
			return;
		}
		// Apply lock immediately (Generated / count), then refine based on leaf existence.
		frm._cheque_book_has_any_leaves = false;
		frm.trigger("_apply_generation_lock_ui");
		frm.trigger("_has_any_leaves").then((has_leaves) => {
			frm._cheque_book_has_any_leaves = !!has_leaves;
			frm.trigger("_apply_generation_lock_ui");
			// One headline only: **show_message** appends unless we clear first.
			frm.dashboard.clear_headline();
			const g = frm.doc.generated_leaves_count || 0;
			const a = frm.doc.available_leaves_count || 0;
			const u = frm.doc.used_leaves_count || 0;
			const r = frm.doc.reserved_leaves_count || 0;
			const v = frm.doc.void_leaves_count || 0;
			const badge = (label, val, color) =>
				`<span class="indicator-pill whitespace-nowrap ${color}"> ${label}: ${val} </span>`;
			frm.dashboard.set_headline(
				__('<div class="flex" style="gap:8px; flex-wrap: wrap;">{0}{1}{2}{3}{4}</div>', [
					badge(__("Total"), g, "blue"),
					badge(__("Available"), a, a <= 5 ? "orange" : "green"),
					badge(__("Reserved"), r, r > 0 ? "orange" : "gray"),
					badge(__("Used"), u, "gray"),
					badge(__("Void"), v, v > 0 ? "red" : "gray"),
				])
			);
			if (a <= 5 && g > 0) {
				frm.dashboard.set_headline_alert(
					__("Cheque book is running out of available leaves."),
					"orange"
				);
			}
		});
		if ((frm.doc.docstatus || 0) !== 0) {
			return;
		}
		frm.add_custom_button(__("View Leaves"), () => {
			frappe.set_route("List", "Cheque Leaf", { cheque_book: frm.doc.name });
		});
		frm.add_custom_button(__("Recalculate Counts"), () => {
			frm.call("recalculate_counts").then((r) => {
				const m = (r && r.message) || {};
				frappe.show_alert(
					{
						message: __("Counts updated — {0} ({1} available, {2} used).", [
							m.status || "",
							m.available_leaves_count ?? 0,
							m.used_leaves_count ?? 0,
						]),
						indicator: "green",
					},
					5
				);
				frm.reload_doc();
			});
		});
		if ((frm.doc.status || "Draft") !== "Draft") {
			return;
		}
		if ((frm.doc.generated_leaves_count || 0) > 0) {
			return;
		}
		frm.add_custom_button(__("Generate Leaves"), () => {
			frappe.confirm(
				__("Generate cheque leaves for this book? This cannot be undone."),
				() => {
					frm.call("generate_leaves").then((r) => {
						const msg = (r && r.message) || {};
						frappe.show_alert(
							{
								message: __("Generated {0} cheque leaves.", [msg.created || 0]),
								indicator: "green",
							},
							6
						);
						frm.reload_doc();
					});
				},
				() => {}
			);
		}).addClass("btn-primary");
	},
});
