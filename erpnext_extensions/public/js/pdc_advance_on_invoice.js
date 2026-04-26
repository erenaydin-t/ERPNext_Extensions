// Task 6: Draft application of Advance-mode PDCs on invoices (PI/SI).

frappe.provide("erpnext_extensions.cheque_management");

function _pdc_toast(message, indicator = "blue", duration_s = 6) {
	// UX: non-blocking messages should use consistent toasts.
	frappe.show_alert(
		{
			message: message,
			indicator: indicator,
		},
		duration_s
	);
}

function _hide_pdc_advance_docfield_buttons(frm) {
	// Do NOT use DocField Button controls for layout.
	// Hide them aggressively because they otherwise render vertically.
	["get_advance_pdcs", "recalculate_pdc_advance_suggestions", "clear_draft_pdc_advances"].forEach((fn) => {
		try {
			frm.toggle_display(fn, false);
		} catch (e) {
			// ignore
		}
		try {
			frm.set_df_property(fn, "hidden", 1);
		} catch (e) {
			// ignore
		}
		try {
			const w = frm.fields_dict && frm.fields_dict[fn] && frm.fields_dict[fn].wrapper;
			if (w && typeof w.hide === "function") w.hide();
		} catch (e) {
			// ignore
		}
	});
}

function _render_pdc_advance_actions_bar(frm) {
	if (!frm || !frm.doc) return;
	_hide_pdc_advance_docfield_buttons(frm);

	// Global de-dup: remove any previously injected bars anywhere in the form.
	try {
		if (frm.wrapper) {
			$(frm.wrapper).find(".pdc-advance-action-bar").remove();
		}
	} catch (e) {
		// ignore
	}

	// Prefer the dedicated HTML field (added by patch). If unavailable, fall back to injecting
	// directly above the `pdc_invoice_applications` grid wrapper.
	let target_wrapper = null;
	let inject_mode = "none"; // "html_field" | "before_grid"
	try {
		const f = frm.fields_dict && frm.fields_dict.pdc_advance_actions_html;
		const w = f && f.$wrapper;
		const visible = w && w.length && w.is(":visible");
		if (visible) {
			target_wrapper = w;
			inject_mode = "html_field";
		}
	} catch (e) {
		// ignore
	}

	if (!target_wrapper) {
		try {
			const grid_wrapper =
				frm.fields_dict &&
				frm.fields_dict.pdc_invoice_applications &&
				frm.fields_dict.pdc_invoice_applications.grid &&
				frm.fields_dict.pdc_invoice_applications.grid.wrapper;
			if (grid_wrapper && grid_wrapper.length) {
				target_wrapper = grid_wrapper;
				inject_mode = "before_grid";
			}
		} catch (e) {
			// ignore
		}
	}

	if (!target_wrapper) return;

	const html = $(`
		<div class="pdc-advance-action-bar pdc-advance-actions" style="display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:12px;">
			<button type="button" class="btn btn-primary btn-sm" data-pdc-action="get">
				${__("Get Advance PDCs")}
			</button>
			<button type="button" class="btn btn-default btn-sm" data-pdc-action="recalc">
				${__("Recalculate Suggested Amounts")}
			</button>
			<button type="button" class="btn btn-danger btn-sm" data-pdc-action="clear">
				${__("Clear Draft PDC Advances")}
			</button>
		</div>
	`);

	// If using the HTML field wrapper, append into it. If using grid wrapper, inject before the grid.
	try {
		if (inject_mode === "html_field") {
			target_wrapper.append(html);
		} else if (inject_mode === "before_grid") {
			html.insertBefore(target_wrapper);
		} else {
			target_wrapper.append(html);
		}
	} catch (e) {
		// Fallback: append
		target_wrapper.append(html);
	}

	// Call existing handlers directly.
	html.find('[data-pdc-action="get"]').on("click", () => frm.trigger("get_advance_pdcs"));
	html.find('[data-pdc-action="recalc"]').on("click", () => frm.trigger("recalculate_pdc_advance_suggestions"));
	html.find('[data-pdc-action="clear"]').on("click", () => frm.trigger("clear_draft_pdc_advances"));

	// Post-render safety: if duplicates somehow exist, keep first and remove the rest.
	try {
		if (frm.wrapper) {
			const bars = $(frm.wrapper).find(".pdc-advance-action-bar");
			if (bars && bars.length > 1) {
				bars.slice(1).remove();
			}
		}
	} catch (e) {
		// ignore
	}
}

function _pdc_flt(value, fallback = 0.0) {
	try {
		if (frappe && frappe.utils && typeof frappe.utils.flt === "function") {
			return frappe.utils.flt(value);
		}
	} catch (e) {
		// ignore
	}
	const v = parseFloat(value);
	return Number.isFinite(v) ? v : fallback;
}

function _set_value_no_dirty(frm, fieldname, value) {
	try {
		// Frappe supports skip_dirty_trigger in model.set_value in most Desk versions.
		if (frappe && frappe.model && typeof frappe.model.set_value === "function") {
			// Ensure underlying doc has the value immediately for refresh/render.
			try {
				frm.doc[fieldname] = value;
			} catch (e) {
				// ignore
			}
			frappe.model.set_value(frm.doctype, frm.docname, fieldname, value, null, true);
			return;
		}
	} catch (e) {
		// fall through
	}
	// Fallback: assignment + refresh (may mark dirty on older builds, so we avoid calling it post-save).
	try {
		frm.doc[fieldname] = value;
	} catch (e) {
		// ignore
	}
}

function _recalc_pdc_advance_preview(frm) {
	if (!frm || !frm.doc) {
		return;
	}
	if ((parseInt(frm.doc.docstatus, 10) || 0) !== 0) {
		return;
	}

	const rows = frm.doc.pdc_invoice_applications || [];
	let total = 0.0;
	(rows || []).forEach((r) => {
		// UI-only: sum the row "amount" as requested (invoice currency).
		total += _pdc_flt(r && r.amount);
	});

	// Match ERPNext-like UX: reflect draft advances immediately.
	_set_value_no_dirty(frm, "total_advance", total);

	const gt = _pdc_flt(frm.doc.grand_total);
	const outstanding = gt - total;
	// UI-only preview: do not post anything; backend will recompute on submit.
	_set_value_no_dirty(frm, "outstanding_amount", outstanding);
	frm.refresh_field("total_advance");
	frm.refresh_field("outstanding_amount");

	// UX warnings only (backend remains source of truth).
	if (_pdc_flt(total) > _pdc_flt(frm.doc.grand_total) + 1e-9) {
		_pdc_toast(__("Total draft PDC advances exceed invoice total."), "orange", 6);
	}
	(rows || []).some((r) => {
		const scope = String((r && r.advance_scope) || "").trim();
		const odt = String((r && r.order_doctype) || "").trim();
		const onm = String((r && r.order_name) || "").trim();
		if (scope === "general" && (odt || onm)) {
			_pdc_toast(__("General advance row has order fields filled (will be blocked on submit)."), "orange", 6);
			return true;
		}
		if (scope === "order_based" && (!odt || !onm)) {
			_pdc_toast(__("Order-based advance row is missing order fields (will be blocked on submit)."), "orange", 6);
			return true;
		}
		return false;
	});
}

function _key_for_application_row(r) {
	const pdc = (r && (r.post_dated_cheque || r.post_dated_cheque_name || r.pdc)) || "";
	const scope = (r && r.advance_scope) || "";
	const odt = (r && r.order_doctype) || "";
	const onm = (r && r.order_name) || "";
	return `${String(scope).trim()}|${String(pdc).trim()}|${String(odt).trim()}|${String(onm).trim()}`;
}

function _remove_draft_pdc_advance_rows(frm) {
	if (!frm || !frm.doc) return 0;
	const kept = [];
	let removed = 0;
	(frm.doc.pdc_invoice_applications || []).forEach((r) => {
		const st = String((r && r.application_status) || "draft").trim() || "draft";
		if (st === "draft") {
			removed += 1;
		} else {
			kept.push(r);
		}
	});
	frm.doc.pdc_invoice_applications = kept;
	frm.refresh_field("pdc_invoice_applications");
	_recalc_pdc_advance_preview(frm);
	return removed;
}

function _recalculate_suggested_amounts(frm) {
	if (!frm || !frm.doc) return;
	if ((parseInt(frm.doc.docstatus, 10) || 0) !== 0) return;

	const rows = frm.doc.pdc_invoice_applications || [];
	const drafts = (rows || []).filter((r) => String((r.application_status || "draft")).trim() === "draft");
	const remaining0 = _pdc_flt(frm.doc.grand_total);
	let remaining = remaining0;

	// Process order_based first, then general, but do not reorder rows.
	const ordered = []
		.concat(drafts.filter((r) => String((r.advance_scope || "")).trim() === "order_based"))
		.concat(drafts.filter((r) => String((r.advance_scope || "")).trim() === "general"));

	(ordered || []).forEach((r) => {
		const open_amt = _pdc_flt(r && r.open_amount);
		const sug = Math.max(0, Math.min(open_amt, remaining));
		r.amount = sug;
		r.amount_in_pdc_currency = sug;
		r.fx_rate = 1.0;
		remaining -= sug;
	});

	frm.refresh_field("pdc_invoice_applications");
	_recalc_pdc_advance_preview(frm);
}

["Purchase Invoice", "Sales Invoice"].forEach((dt) => {
	frappe.ui.form.on(dt, {
		onload_post_render(frm) {
			_render_pdc_advance_actions_bar(frm);
		},
		refresh(frm) {
			// UX: The interaction is via a Button field in the Payments tab section.
			// Keep this file attached to PI/SI doctypes; the patch ensures the fields exist.
			_render_pdc_advance_actions_bar(frm);
			frm.refresh_field("pdc_invoice_applications");
			_recalc_pdc_advance_preview(frm);
		},
		get_advance_pdcs(frm) {
			if (!frm || (frm.doctype !== "Purchase Invoice" && frm.doctype !== "Sales Invoice")) {
				return;
			}
			if (frm.is_new() || !frm.doc || !frm.doc.name) {
				_pdc_toast(__("Please save this invoice first."), "blue", 6);
				return;
			}
			if ((parseInt(frm.doc.docstatus, 10) || 0) !== 0) {
				_pdc_toast(__("Advance PDC rows can only be added while the invoice is in Draft."), "orange", 6);
				return;
			}

			// Local context hint for empty-state messaging only (backend decides eligibility).
			const has_order_link = (() => {
				try {
					const items = (frm.doc && frm.doc.items) || [];
					if (frm.doctype === "Purchase Invoice") {
						return (items || []).some((it) => (it && it.purchase_order ? String(it.purchase_order).trim() : ""));
					}
					if (frm.doctype === "Sales Invoice") {
						return (items || []).some((it) => (it && it.sales_order ? String(it.sales_order).trim() : ""));
					}
				} catch (e) {
					// ignore
				}
				return false;
			})();

			const draft_exists = (frm.doc.pdc_invoice_applications || []).some(
				(r) => String((r && r.application_status) || "draft").trim() === "draft"
			);

			const do_fetch = () => {
				frappe.call({
					method: "erpnext_extensions.cheque_management.pdc_advance_application_service.get_advance_candidates_for_invoice_api",
					args: {
						invoice_doctype: frm.doctype,
						invoice_name: frm.doc.name,
						include_general: 1,
					},
					freeze: true,
					freeze_message: __("Loading Advance PDCs"),
					callback: (r) => {
						const payload = (r && r.message) || {};
						let rows = (payload && payload.candidates) || [];
						const msg = (payload && payload.message) || "";

						// Only add candidates with suggested_apply_amount > 0
						rows = (rows || []).filter((c) => _pdc_flt(c && c.suggested_apply_amount) > 1e-9);

						if (!rows.length) {
							_pdc_toast(
								msg ||
									(has_order_link
										? __("No recognized Advance PDCs are available for this invoice.")
										: __("No general PDC advances are available for this invoice.")),
								"blue",
								6
							);
							return;
						}

						const draft_rows = (frm.doc.pdc_invoice_applications || []).filter(
							(x) => String((x.application_status || "draft")).trim() === "draft"
						);
						const existing_map = new Map(draft_rows.map((x) => [_key_for_application_row(x), x]));

						let added = 0;
						let updated = 0;
						let skipped = 0;

						(rows || []).forEach((c) => {
							const scope = String((c && c.advance_scope) || "").trim() || "order_based";
							const is_general = scope === "general";
							const source_dt = is_general
								? ""
								: String((c && (c.source_doctype || c.order_doctype)) || "").trim();
							const source_nm = is_general
								? ""
								: String((c && (c.source_name || c.order_name)) || "").trim();

							const key = `${scope}|${String(c.post_dated_cheque || "").trim()}|${source_dt}|${source_nm}`;
							const existing = existing_map.get(key);
							if (existing) {
								// Duplicate policy: update open_amount and only set amount if empty/zero.
								existing.open_amount = c.open_amount;
								if (_pdc_flt(existing.amount) <= 1e-9) {
									existing.amount = c.suggested_apply_amount;
									existing.amount_in_pdc_currency = c.suggested_apply_amount;
									existing.fx_rate = 1.0;
									updated += 1;
								} else {
									skipped += 1;
								}
								return;
							}

							const child = frm.add_child("pdc_invoice_applications");
							child.post_dated_cheque = c.post_dated_cheque;
							child.advance_scope = scope;
							child.open_amount = c.open_amount;
							child.amount_in_pdc_currency = c.suggested_apply_amount;
							child.amount = c.suggested_apply_amount; // v1: same currency only
							child.fx_rate = 1.0;

							if (is_general) {
								child.order_doctype = "";
								child.order_name = "";
								child.source_doctype = "";
								child.source_name = "";
								child.source_bucket_label = __("General Pool");
								const pk = (c && c.pool_key) || {};
								child.pool_company = pk.company || frm.doc.company;
								child.pool_party_type = pk.party_type || null;
								child.pool_party = pk.party || null;
								child.pool_currency = pk.currency || frm.doc.currency;
							} else {
								child.order_doctype = source_dt || "";
								child.order_name = source_nm || "";
								child.source_bucket_label = source_nm || (source_dt && source_nm ? `${source_dt} ${source_nm}` : null);
								child.source_doctype = "";
								child.source_name = "";
								child.pool_company = null;
								child.pool_party_type = null;
								child.pool_party = null;
								child.pool_currency = null;
							}

							child.application_status = "draft";
							added += 1;
						});

						frm.refresh_field("pdc_invoice_applications");
						_recalc_pdc_advance_preview(frm);
						_pdc_toast(
							__("Advance PDCs: {0} added, {1} updated, {2} skipped.", [added, updated, skipped]),
							"green",
							6
						);
					},
				});
			};

			if (draft_exists) {
				frappe.confirm(
					__("Draft PDC advance rows already exist. Replace them with fresh suggestions?"),
					() => {
						_remove_draft_pdc_advance_rows(frm);
						do_fetch();
					},
					() => {
						// Keep existing drafts; merge new suggestions by duplicate policy.
						do_fetch();
					}
				);
				return;
			}
			do_fetch();
		},
		recalculate_pdc_advance_suggestions(frm) {
			_recalculate_suggested_amounts(frm);
		},
		clear_draft_pdc_advances(frm) {
			const draft_exists = (frm.doc.pdc_invoice_applications || []).some(
				(r) => String((r && r.application_status) || "draft").trim() === "draft"
			);
			if (!draft_exists) {
				_pdc_toast(__("No draft PDC advance rows to clear."), "blue", 6);
				return;
			}
			frappe.confirm(__("Clear draft PDC advance rows?"), () => _remove_draft_pdc_advance_rows(frm));
		},
	});
});

frappe.ui.form.on("PDC Invoice Application", {
	amount(frm) {
		_recalc_pdc_advance_preview(frm);
	},
	pdc_invoice_applications_add(frm) {
		_recalc_pdc_advance_preview(frm);
	},
	pdc_invoice_applications_remove(frm) {
		_recalc_pdc_advance_preview(frm);
	},
});

