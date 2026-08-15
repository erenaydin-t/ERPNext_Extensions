// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

const GD_DOCTYPE = "Guarantee Document";

/**
 * Frappe FilterList auto-adds an empty name filter when the Filter popover opens.
 * On popover hide it applies filters, and empty string is kept (!= null) →
 * "ID Equals <empty>" with zero rows. Same class of bug as Post Dated Cheque list.
 * Sanitize only invalid empty-value filters; never wipe legitimate saved/route filters.
 */
const GD_CONDITIONS_WITHOUT_OPERAND = new Set([
	"set",
	"not set",
	"is set",
	"is not set",
	"is null",
	"is not null",
	"is empty",
	"is not empty",
]);

const GD_CONDITIONS_REQUIRING_OPERAND = new Set([
	"=",
	"!=",
	"like",
	"not like",
	"in",
	"not in",
	"between",
	">",
	"<",
	">=",
	"<=",
	"descendants of",
	"descendants of (inclusive)",
	"ancestors of",
	"not descendants of",
	"not ancestors of",
	"timespan",
]);

frappe.listview_settings[GD_DOCTYPE] = {
	// Explicit: no automatic/default list filters (including Status = Active).
	filters: [],

	add_fields: [
		"party_type",
		"party",
		"other_party_name",
		"guarantee_direction",
		"status",
		"document_no",
		"expiry_date",
		"guarantee_type",
		"amount",
		"currency",
	],

	onload(listview) {
		gd_strip_company_from_list_columns(listview);
		gd_bind_invalid_empty_filter_cleanup(listview);

		// Presentation-only: rename Direction column header to Held By (field identity unchanged).
		(listview.columns || []).forEach((col) => {
			if (col.df && col.df.fieldname === "guarantee_direction") {
				col.df.label = __("Held By");
			}
		});

		if (listview._gd_render_patched) {
			return;
		}
		listview._gd_render_patched = true;
		listview._gd_party_display_cache = listview._gd_party_display_cache || {};
		listview._gd_party_token = 0;

		const original_render = listview.render_list.bind(listview);
		listview.render_list = function () {
			// Paint immediately so Refreshing/freeze cannot stall on party RPC.
			original_render();

			const token = ++listview._gd_party_token;
			gd_batch_resolve_party_displays(listview)
				.then(() => {
					if (token !== listview._gd_party_token) {
						return;
					}
					original_render();
				})
				.catch(() => {
					/* batch failure must not block list rendering */
				});
		};
	},

	get_indicator(doc) {
		const status = (doc.status || "Draft").trim();
		const colors = {
			Draft: "gray",
			Active: "green",
			Returned: "blue",
			Released: "cyan",
			Cancelled: "darkgrey",
			Expired: "orange",
			Lost: "red",
		};
		const color = colors[status] || "gray";
		return [__(status), color, "status,=," + status];
	},

	formatters: {
		guarantee_direction(value, df, doc) {
			return gd_held_by_label(doc);
		},
		party(value, df, doc) {
			if (doc.party_type === "Other") {
				return doc.other_party_name || value || "";
			}
			const list = typeof cur_list !== "undefined" ? cur_list : null;
			const cache = (list && list._gd_party_display_cache) || {};
			const key = (doc.party_type || "") + "::" + (doc.party || "");
			if (cache[key]) {
				return cache[key];
			}
			return value || "";
		},
		title(value, df, doc) {
			const no = (doc.document_no || "").trim();
			if (no) {
				return no;
			}
			return doc.name;
		},
	},
};

function gd_held_by_label(doc) {
	const status = (doc.status || "").trim();
	const direction = (doc.guarantee_direction || "").trim();
	if (status !== "Active") {
		return "—";
	}
	if (direction === "Received") {
		return __("Held by Us");
	}
	if (direction === "Issued") {
		return __("Held by Others");
	}
	return "—";
}

function gd_strip_company_from_list_columns(listview) {
	if (Array.isArray(listview.columns)) {
		listview.columns = listview.columns.filter(
			(col) => !(col && col.df && col.df.fieldname === "company")
		);
	}
	const lvs = listview.list_view_settings;
	if (lvs && Array.isArray(lvs.fields)) {
		lvs.fields = lvs.fields.filter((f) => {
			const name = typeof f === "string" ? f : f && f.fieldname;
			return name !== "company";
		});
	}
}

function gd_normalize_condition(condition) {
	return (condition || "").toString().trim().toLowerCase();
}

function gd_is_filter_value_empty(value) {
	if (value === null || value === undefined) {
		return true;
	}
	if (Array.isArray(value)) {
		return value.length === 0 || value.every((v) => gd_is_filter_value_empty(v));
	}
	if (typeof value === "string") {
		return value.trim() === "";
	}
	return false;
}

function gd_filter_tuple_has_invalid_empty_value(filter) {
	if (!Array.isArray(filter) || filter.length < 3) {
		return false;
	}
	const condition = gd_normalize_condition(filter[2]);
	const value = filter.length > 3 ? filter[3] : undefined;

	if (GD_CONDITIONS_WITHOUT_OPERAND.has(condition)) {
		return false;
	}
	if (condition === "is") {
		return gd_is_filter_value_empty(value);
	}
	const boot_cfg = frappe.boot?.additional_filters_config?.[filter[2]];
	if (boot_cfg && boot_cfg.valid_for_empty_value) {
		return false;
	}
	if (GD_CONDITIONS_REQUIRING_OPERAND.has(condition)) {
		return gd_is_filter_value_empty(value);
	}
	return gd_is_filter_value_empty(value);
}

function gd_sanitize_filter_tuples(filters) {
	if (!Array.isArray(filters)) {
		return [];
	}
	return filters.filter((f) => !gd_filter_tuple_has_invalid_empty_value(f));
}

function gd_filter_row_is_invalid_empty(filter_row) {
	if (!filter_row?.field) {
		return true;
	}
	const tuple = filter_row.get_value?.();
	if (tuple && gd_filter_tuple_has_invalid_empty_value(tuple)) {
		return true;
	}
	const fieldname = filter_row.field.df?.fieldname;
	const cond = gd_normalize_condition(filter_row.get_condition?.());
	const val = filter_row.get_selected_value?.();
	return (
		fieldname === "name" &&
		(cond === "=" || cond === "equals") &&
		gd_is_filter_value_empty(val)
	);
}

function gd_prune_invalid_filter_rows(listview) {
	const filter_list = listview.filter_area?.filter_list;
	if (!filter_list?.filters?.length) {
		return false;
	}
	let changed = false;
	const keep = [];
	for (const f of filter_list.filters) {
		if (gd_filter_row_is_invalid_empty(f)) {
			try {
				f.remove(true);
			} catch (e) {
				/* ignore */
			}
			changed = true;
			continue;
		}
		keep.push(f);
	}
	if (changed) {
		filter_list.filters = keep;
		filter_list.update_filters?.();
		filter_list.update_filter_button?.();
		filter_list.toggle_empty_filters?.(filter_list.filters.length === 0);
	}
	return changed;
}

function gd_remove_invalid_empty_filters_sync(listview) {
	if (!listview?.filter_area) {
		return false;
	}
	let changed = false;
	if (Array.isArray(listview.filters)) {
		const sanitized = gd_sanitize_filter_tuples(listview.filters);
		if (sanitized.length !== listview.filters.length) {
			listview.filters = sanitized;
			changed = true;
		}
	}
	if (gd_prune_invalid_filter_rows(listview)) {
		changed = true;
	}
	const combined = listview.filter_area.get?.() || [];
	const sanitized_combined = gd_sanitize_filter_tuples(combined);
	if (sanitized_combined.length !== combined.length) {
		changed = true;
		if (typeof listview.save_view_user_settings === "function") {
			listview.save_view_user_settings({ filters: sanitized_combined });
		}
	}
	if (changed) {
		listview.filter_area.filter_list?.update_filter_button?.();
	}
	return changed;
}

function gd_bind_invalid_empty_filter_cleanup(listview) {
	if (listview._gd_filter_cleanup_bound) {
		return;
	}
	listview._gd_filter_cleanup_bound = true;

	if (Array.isArray(listview.filters)) {
		listview.filters = gd_sanitize_filter_tuples(listview.filters);
	}
	gd_remove_invalid_empty_filters_sync(listview);

	const filter_area = listview.filter_area;
	if (filter_area && !filter_area._gd_get_wrapped) {
		filter_area._gd_get_wrapped = true;
		const orig_get = filter_area.get.bind(filter_area);
		filter_area.get = function () {
			return gd_sanitize_filter_tuples(orig_get());
		};
		const orig_set = filter_area.set.bind(filter_area);
		filter_area.set = function (filters) {
			return orig_set(gd_sanitize_filter_tuples(filters || []));
		};
	}

	const filter_list = filter_area?.filter_list;
	if (filter_list && !filter_list._gd_get_filters_wrapped) {
		filter_list._gd_get_filters_wrapped = true;
		const orig_get_filters = filter_list.get_filters.bind(filter_list);
		filter_list.get_filters = function () {
			gd_prune_invalid_filter_rows(listview);
			return gd_sanitize_filter_tuples(orig_get_filters());
		};
		const orig_apply = filter_list.apply.bind(filter_list);
		filter_list.apply = function () {
			gd_remove_invalid_empty_filters_sync(listview);
			return orig_apply();
		};
	}

	if (!listview._gd_before_refresh_wrapped) {
		listview._gd_before_refresh_wrapped = true;
		const orig_before = listview.before_refresh.bind(listview);
		listview.before_refresh = function () {
			gd_remove_invalid_empty_filters_sync(listview);
			return orig_before();
		};
	}

	if (!listview._gd_get_filters_for_args_wrapped) {
		listview._gd_get_filters_for_args_wrapped = true;
		const orig_args = listview.get_filters_for_args.bind(listview);
		listview.get_filters_for_args = function () {
			return gd_sanitize_filter_tuples(orig_args());
		};
	}

	const btn = filter_list?.filter_button;
	if (btn && filter_list && !filter_list._gd_popover_prune_hooked) {
		filter_list._gd_popover_prune_hooked = true;
		btn.on("show.bs.popover", () => {
			gd_remove_invalid_empty_filters_sync(listview);
		});
		btn.on("shown.bs.popover", () => {
			const changed = gd_prune_invalid_filter_rows(listview);
			if (changed && filter_list.filters.length === 0) {
				filter_list.toggle_empty_filters?.(true);
				filter_list.update_filter_button?.();
			}
		});
	}
}

function gd_batch_resolve_party_displays(listview) {
	const data = listview.data || [];
	const refs = [];
	const seen = {};

	data.forEach((doc) => {
		const pt = (doc.party_type || "").trim();
		if (pt === "Other") {
			const other = (doc.other_party_name || "").trim();
			if (!other) {
				return;
			}
			const key = "Other::" + other;
			if (!seen[key]) {
				seen[key] = true;
				refs.push({
					party_type: "Other",
					party: "",
					other_party_name: other,
				});
			}
			return;
		}
		const party = (doc.party || "").trim();
		if (!pt || !party) {
			return;
		}
		const key = pt + "::" + party;
		if (seen[key]) {
			return;
		}
		seen[key] = true;
		refs.push({
			party_type: pt,
			party: party,
			other_party_name: "",
		});
	});

	if (!refs.length) {
		return Promise.resolve();
	}

	return frappe
		.call({
			method:
				"erpnext_extensions.guarantee_management.services.party_display.batch_resolve_party_displays_for_list",
			args: { refs },
		})
		.then((r) => {
			listview._gd_party_display_cache = (r && r.message) || {};
		})
		.catch(() => {
			listview._gd_party_display_cache = listview._gd_party_display_cache || {};
		});
}
