frappe.provide("erpnext_extensions.cheque_management.pdc_list_view");

const PDC_DOCTYPE = "Post Dated Cheque";

const PDC_LIST_CONDITIONS_WITHOUT_OPERAND_VALUE = new Set([
	"set",
	"not set",
	"is set",
	"is not set",
	"is null",
	"is not null",
	"is empty",
	"is not empty",
]);

const PDC_LIST_CONDITIONS_REQUIRING_OPERAND_VALUE = new Set([
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

function pdc_list_normalize_condition(condition) {
	return (condition || "").toString().trim().toLowerCase();
}

function pdc_list_is_filter_value_empty(value) {
	if (value === null || value === undefined) {
		return true;
	}
	if (Array.isArray(value)) {
		return value.length === 0 || value.every((v) => pdc_list_is_filter_value_empty(v));
	}
	if (typeof value === "string") {
		return value.trim() === "";
	}
	return false;
}

/** True when tuple must not be applied (e.g. name Equals ""). */
function pdc_list_filter_tuple_has_invalid_empty_value(filter) {
	if (!Array.isArray(filter) || filter.length < 3) {
		return false;
	}
	const condition = pdc_list_normalize_condition(filter[2]);
	const value = filter.length > 3 ? filter[3] : undefined;

	if (PDC_LIST_CONDITIONS_WITHOUT_OPERAND_VALUE.has(condition)) {
		return false;
	}
	if (condition === "is") {
		return pdc_list_is_filter_value_empty(value);
	}
	const boot_cfg = frappe.boot?.additional_filters_config?.[filter[2]];
	if (boot_cfg && boot_cfg.valid_for_empty_value) {
		return false;
	}
	if (PDC_LIST_CONDITIONS_REQUIRING_OPERAND_VALUE.has(condition)) {
		return pdc_list_is_filter_value_empty(value);
	}
	return pdc_list_is_filter_value_empty(value);
}

function pdc_list_sanitize_filter_tuples(filters) {
	if (!Array.isArray(filters)) {
		return [];
	}
	return filters.filter((f) => !pdc_list_filter_tuple_has_invalid_empty_value(f));
}

function pdc_list_reconcile_state(listview) {
	if (!listview._pdc_filter_reconcile_state) {
		listview._pdc_filter_reconcile_state = {
			invalid_filter_cleanup_done: false,
			user_interacted: false,
		};
	}
	return listview._pdc_filter_reconcile_state;
}

function pdc_list_has_url_filters() {
	return new URLSearchParams(window.location.search).toString().length > 0;
}

function pdc_list_get_filter_debug(listview) {
	const filter_area = listview.filter_area;
	const filter_list = filter_area?.filter_list;
	const chip_filters = filter_area?.filter_list?.get_filters?.() || [];
	const standard_filters = filter_area?.get_standard_filters?.() || [];
	const combined = filter_area?.get?.() || [];
	const list_settings = frappe.get_user_settings?.(PDC_DOCTYPE, "List") || {};
	const filter_list_meta = (filter_list?.filters || []).map((f) => ({
		fieldname: f.fieldname,
		hidden: !!f.hidden,
		value: f.get_selected_value?.(),
	}));
	return {
		route: frappe.get_route?.(),
		route_options: frappe.route_options,
		url_search: window.location.search,
		chip_filters,
		standard_filters,
		combined_filters: combined,
		filter_list_meta,
		listview_filters: listview.filters,
		user_list_settings: list_settings,
		data_length: listview.data?.length ?? 0,
		reconcile_state: { ...pdc_list_reconcile_state(listview) },
	};
}

/** User intentionally applied filters this session (menu, chips, standard bar). */
function pdc_list_has_session_intentional_filters(listview) {
	return !!pdc_list_reconcile_state(listview).user_interacted;
}

function pdc_list_clear_stale_route_options() {
	if (pdc_list_has_url_filters()) {
		return;
	}
	if (frappe.route_options && Object.keys(frappe.route_options).length) {
		frappe.route_options = null;
	}
}

function pdc_list_bind_filter_user_interaction(listview) {
	const filter_area = listview.filter_area;
	if (!filter_area || filter_area._pdc_interaction_hooked) {
		return;
	}
	filter_area._pdc_interaction_hooked = true;
	const orig_refresh = filter_area.refresh_list_view.bind(filter_area);
	filter_area.refresh_list_view = function () {
		const state = pdc_list_reconcile_state(listview);
		if (state.invalid_filter_cleanup_done && !listview._pdc_programmatic_filter_change) {
			state.user_interacted = true;
		}
		return orig_refresh();
	};
	if (!filter_area._pdc_add_hooked) {
		filter_area._pdc_add_hooked = true;
		const orig_add = filter_area.add.bind(filter_area);
		filter_area.add = function (filters, refresh = true) {
			const state = pdc_list_reconcile_state(listview);
			if (state.invalid_filter_cleanup_done && !listview._pdc_programmatic_filter_change) {
				state.user_interacted = true;
			}
			return orig_add(filters, refresh);
		};
	}
}

function pdc_list_wrap_get_filters_for_args(listview) {
	if (listview._pdc_get_filters_wrapped) {
		return;
	}
	listview._pdc_get_filters_wrapped = true;
	const orig = listview.get_filters_for_args.bind(listview);
	listview.get_filters_for_args = function () {
		return pdc_list_sanitize_filter_tuples(orig());
	};
}

function pdc_list_wrap_before_refresh(listview) {
	if (listview._pdc_before_refresh_wrapped) {
		return;
	}
	listview._pdc_before_refresh_wrapped = true;
	const orig = listview.before_refresh.bind(listview);
	listview.before_refresh = function () {
		return pdc_list_remove_invalid_empty_filters(listview, { refresh: false }).then(() =>
			orig()
		);
	};
}

function pdc_list_sanitize_boot_user_list_filters() {
	try {
		const bucket = frappe.model?.user_settings?.[PDC_DOCTYPE];
		if (bucket?.List?.filters) {
			bucket.List.filters = pdc_list_sanitize_filter_tuples(bucket.List.filters);
		}
		const boot_raw = frappe.boot?.user?.user_settings?.[PDC_DOCTYPE];
		if (boot_raw) {
			const parsed = typeof boot_raw === "string" ? JSON.parse(boot_raw) : boot_raw;
			if (parsed?.List?.filters) {
				parsed.List.filters = pdc_list_sanitize_filter_tuples(parsed.List.filters);
				frappe.boot.user.user_settings[PDC_DOCTYPE] = JSON.stringify(parsed);
			}
		}
	} catch (e) {
		/* ignore */
	}
}

function pdc_list_storage_snapshot(kind) {
	const store = kind === "session" ? window.sessionStorage : window.localStorage;
	const out = {};
	try {
		for (let i = 0; i < store.length; i++) {
			const key = store.key(i);
			if (!key) continue;
			if (
				/pdc|post.dated|cheque|user_settings|filter|list|frappe/i.test(key) ||
				key.includes(PDC_DOCTYPE)
			) {
				out[key] = store.getItem(key);
			}
		}
	} catch (e) {
		out._error = String(e);
	}
	return out;
}

function pdc_list_filter_row_is_invalid_empty(filter_row) {
	if (!filter_row?.field) {
		return true;
	}
	const tuple = filter_row.get_value?.();
	if (tuple && pdc_list_filter_tuple_has_invalid_empty_value(tuple)) {
		return true;
	}
	const fieldname = filter_row.field.df?.fieldname;
	const cond = pdc_list_normalize_condition(filter_row.get_condition?.());
	const val = filter_row.get_selected_value?.();
	return (
		fieldname === "name" &&
		(cond === "=" || cond === "equals") &&
		pdc_list_is_filter_value_empty(val)
	);
}

/** Run before filter_area.set() so saved name="" never hits the query or popover. */
function pdc_list_install_early_list_hooks() {
	if (!frappe.views?.ListView?.prototype || frappe.views.ListView.prototype._pdc_early_hooks) {
		return;
	}
	frappe.views.ListView.prototype._pdc_early_hooks = true;

	const origSetupDefaults = frappe.views.ListView.prototype.setup_defaults;
	frappe.views.ListView.prototype.setup_defaults = function () {
		const result = origSetupDefaults.apply(this, arguments);
		if (this.doctype !== PDC_DOCTYPE) {
			return result;
		}
		pdc_list_sanitize_boot_user_list_filters();
		if (this.user_settings?.List?.filters) {
			this.user_settings.List.filters = pdc_list_sanitize_filter_tuples(
				this.user_settings.List.filters
			);
		}
		if (Array.isArray(this.filters)) {
			this.filters = pdc_list_sanitize_filter_tuples(this.filters);
		}
		pdc_list_persist_sanitized_user_list_filters();
		return result;
	};

	if (!frappe.views.BaseList.prototype._pdc_setup_filter_patched) {
		frappe.views.BaseList.prototype._pdc_setup_filter_patched = true;
		const origSetupFilterArea = frappe.views.BaseList.prototype.setup_filter_area;
		frappe.views.BaseList.prototype.setup_filter_area = function () {
			if (this.doctype === PDC_DOCTYPE) {
				pdc_list_sanitize_boot_user_list_filters();
				if (Array.isArray(this.filters)) {
					this.filters = pdc_list_sanitize_filter_tuples(this.filters);
				}
			}
			return origSetupFilterArea.apply(this, arguments);
		};
	}
}

function pdc_list_wrap_filter_area_set(listview) {
	const filter_area = listview.filter_area;
	if (!filter_area || filter_area._pdc_set_wrapped) {
		return;
	}
	filter_area._pdc_set_wrapped = true;
	const orig = filter_area.set.bind(filter_area);
	filter_area.set = function (filters) {
		const sanitized = pdc_list_sanitize_filter_tuples(filters || []);
		return orig(sanitized);
	};
}

function pdc_list_bind_popover_cleanup(listview) {
	const filter_list = listview.filter_area?.filter_list;
	const btn = filter_list?.filter_button;
	if (!btn || filter_list._pdc_popover_prune_hooked) {
		return;
	}
	filter_list._pdc_popover_prune_hooked = true;
	btn.on("show.bs.popover", () => {
		pdc_list_remove_invalid_empty_filters_sync(listview);
	});
	btn.on("shown.bs.popover", () => {
		const changed = pdc_list_prune_invalid_filter_rows(listview);
		if (changed && filter_list.filters.length === 0) {
			filter_list.toggle_empty_filters(true);
			filter_list.update_filter_button?.();
		}
	});
}

/** Synchronously drop invalid FilterGroup rows and fix button/X state (no refresh). */
function pdc_list_prune_invalid_filter_rows(listview) {
	const filter_list = listview.filter_area?.filter_list;
	if (!filter_list?.filters?.length) {
		return false;
	}
	let changed = false;
	const keep = [];
	for (const f of filter_list.filters) {
		if (pdc_list_filter_row_is_invalid_empty(f)) {
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

function pdc_list_remove_invalid_empty_filters_sync(listview) {
	if (!listview?.filter_area) {
		return false;
	}
	let changed = false;
	if (Array.isArray(listview.filters)) {
		const sanitized = pdc_list_sanitize_filter_tuples(listview.filters);
		if (sanitized.length !== listview.filters.length) {
			listview.filters = sanitized;
			changed = true;
		}
	}
	if (pdc_list_prune_invalid_filter_rows(listview)) {
		changed = true;
	}
	const combined = listview.filter_area.get?.() || [];
	const sanitized_combined = pdc_list_sanitize_filter_tuples(combined);
	if (sanitized_combined.length !== combined.length) {
		changed = true;
		if (typeof listview.save_view_user_settings === "function") {
			listview.save_view_user_settings({ filters: sanitized_combined });
		}
	}
	pdc_list_persist_sanitized_user_list_filters();
	if (changed) {
		listview.filter_area.filter_list?.update_filter_button?.();
	}
	return changed;
}

/**
 * Drop invalid empty-value filters from FilterGroup rows, listview.filters, and saved List settings.
 * Valid filters (e.g. ID Equals PDC-xxx, name Is set) are kept.
 */
async function pdc_list_remove_invalid_empty_filters(listview, { refresh = false } = {}) {
	if (!listview?.filter_area) {
		return false;
	}
	let changed = pdc_list_remove_invalid_empty_filters_sync(listview);
	listview._pdc_programmatic_filter_change = true;
	try {
		const fields_dict = listview.page?.fields_dict || {};
		for (const key of Object.keys(fields_dict)) {
			const field = fields_dict[key];
			const raw = field.get_value?.();
			if (pdc_list_is_filter_value_empty(raw)) {
				continue;
			}
			let match_type = field.df?.match_type || "=";
			let condition = match_type === "like" ? "like" : "=";
			const tuple = [field.df?.doctype || PDC_DOCTYPE, field.df?.fieldname, condition, raw];
			if (pdc_list_filter_tuple_has_invalid_empty_value(tuple)) {
				await field.set_value("");
				changed = true;
			}
		}

		if (changed && refresh) {
			await listview.refresh();
		}
	} finally {
		listview._pdc_programmatic_filter_change = false;
	}
	return changed;
}

function pdc_list_wrap_filter_area_get(listview) {
	const filter_area = listview.filter_area;
	if (!filter_area || filter_area._pdc_get_wrapped) {
		return;
	}
	filter_area._pdc_get_wrapped = true;
	const orig = filter_area.get.bind(filter_area);
	filter_area.get = function () {
		return pdc_list_sanitize_filter_tuples(orig());
	};
}

function pdc_list_wrap_filter_list_get_filters(listview) {
	const filter_list = listview.filter_area?.filter_list;
	if (!filter_list || filter_list._pdc_get_filters_wrapped) {
		return;
	}
	filter_list._pdc_get_filters_wrapped = true;
	const orig = filter_list.get_filters.bind(filter_list);
	filter_list.get_filters = function () {
		pdc_list_prune_invalid_filter_rows(listview);
		return pdc_list_sanitize_filter_tuples(orig());
	};
}

function pdc_list_wrap_filter_list_apply(listview) {
	const filter_list = listview.filter_area?.filter_list;
	if (!filter_list || filter_list._pdc_apply_wrapped) {
		return;
	}
	filter_list._pdc_apply_wrapped = true;
	const orig = filter_list.apply.bind(filter_list);
	filter_list.apply = function () {
		const had_invalid = pdc_list_remove_invalid_empty_filters_sync(listview);
		if (had_invalid) {
			frappe.show_alert(
				{
					message: __("Filter value is required for this condition."),
					indicator: "orange",
				},
				4
			);
		}
		return orig();
	};
	const orig_on_change = filter_list.on_change;
	if (typeof orig_on_change === "function") {
		filter_list.on_change = function () {
			pdc_list_prune_invalid_filter_rows(listview);
			return orig_on_change.apply(this, arguments);
		};
	}
}

function pdc_list_persist_sanitized_user_list_filters() {
	const list_settings = frappe.get_user_settings?.(PDC_DOCTYPE, "List") || {};
	const saved = list_settings.filters;
	if (!Array.isArray(saved)) {
		return;
	}
	const sanitized = pdc_list_sanitize_filter_tuples(saved);
	if (sanitized.length === saved.length) {
		return;
	}
	frappe.model.user_settings.save(PDC_DOCTYPE, "List", { filters: sanitized });
}

function pdc_list_bind_invalid_filter_cleanup(listview) {
	pdc_list_bind_filter_user_interaction(listview);
	pdc_list_wrap_filter_area_set(listview);
	pdc_list_wrap_get_filters_for_args(listview);
	pdc_list_wrap_filter_area_get(listview);
	pdc_list_wrap_filter_list_get_filters(listview);
	pdc_list_wrap_filter_list_apply(listview);
	pdc_list_wrap_before_refresh(listview);
	pdc_list_bind_popover_cleanup(listview);
	pdc_list_sanitize_boot_user_list_filters();
	pdc_list_persist_sanitized_user_list_filters();
	pdc_list_remove_invalid_empty_filters_sync(listview);

	if (typeof listview.on === "function") {
		listview.on("after_refresh", async () => {
			const state = pdc_list_reconcile_state(listview);
			if (state.invalid_filter_cleanup_done) {
				return;
			}
			state.invalid_filter_cleanup_done = true;
			const changed = await pdc_list_remove_invalid_empty_filters(listview, {
				refresh: false,
			});
			if (changed) {
				await listview.refresh();
			}
		});
	}
}

function pdc_list_apply_filters(listview, filters, { clear = true } = {}) {
	const chain = clear ? listview.filter_area.clear(false) : Promise.resolve();
	return chain
		.then(() => {
			const promises = (filters || []).map((f) =>
				listview.filter_area.add(f[0], f[1], f[2], f[3], false)
			);
			return Promise.all(promises);
		})
		.then(() => listview.refresh());
}

function pdc_list_reset_reconcile_state(listview) {
	listview._pdc_filter_reconcile_state = {
		invalid_filter_cleanup_done: false,
		user_interacted: false,
	};
	listview._pdc_programmatic_filter_change = false;
}

function pdc_list_wait_refresh(listview, ms = 800) {
	return new Promise((resolve) => {
		listview.once("after_refresh", () => resolve());
		setTimeout(resolve, ms);
	});
}

function pdc_list_dump_all_sources(listview) {
	const boot_raw = frappe.boot?.user?.user_settings?.[PDC_DOCTYPE];
	let boot_parsed = null;
	try {
		boot_parsed = typeof boot_raw === "string" ? JSON.parse(boot_raw || "{}") : boot_raw;
	} catch (e) {
		boot_parsed = { _parse_error: String(e) };
	}
	const filter_list = listview?.filter_area?.filter_list;
	return {
		user_list_settings: frappe.get_user_settings?.(PDC_DOCTYPE, "List") || {},
		model_user_settings: frappe.model?.user_settings?.[PDC_DOCTYPE] || {},
		boot_user_settings: boot_parsed,
		localStorage: pdc_list_storage_snapshot("local"),
		sessionStorage: pdc_list_storage_snapshot("session"),
		route_options: frappe.route_options,
		listview_filters: listview?.filters || [],
		filter_area_get: listview?.filter_area?.get?.() || [],
		filter_list_rows: (filter_list?.filters || []).map((f) => ({
			fieldname: f.field?.df?.fieldname,
			condition: f.get_condition?.(),
			value: f.get_selected_value?.(),
			tuple: f.get_value?.(),
			invalid: pdc_list_filter_row_is_invalid_empty(f),
		})),
		get_filters_for_args: listview?.get_filters_for_args?.() || [],
	};
}

pdc_list_install_early_list_hooks();

erpnext_extensions.cheque_management.pdc_list_view.dump_all_sources = pdc_list_dump_all_sources;
erpnext_extensions.cheque_management.pdc_list_view.get_filter_debug = pdc_list_get_filter_debug;
erpnext_extensions.cheque_management.pdc_list_view.remove_invalid_empty_filters =
	pdc_list_remove_invalid_empty_filters;
erpnext_extensions.cheque_management.pdc_list_view.sanitize_filter_tuples =
	pdc_list_sanitize_filter_tuples;
erpnext_extensions.cheque_management.pdc_list_view.filter_tuple_has_invalid_empty_value =
	pdc_list_filter_tuple_has_invalid_empty_value;
erpnext_extensions.cheque_management.pdc_list_view.reset_reconcile_state =
	pdc_list_reset_reconcile_state;

erpnext_extensions.cheque_management.pdc_list_view.run_filter_e2e = async function (listview) {
	const results = [];
	const push = (name, ok, detail) => results.push({ test: name, ok, detail });

	const db_count = await frappe.db.count(PDC_DOCTYPE);
	push("db_has_records", db_count > 0, { db_count });
	const sample_rows = await frappe.db.get_list(PDC_DOCTYPE, {
		fields: ["name"],
		limit: 1,
		order_by: "modified desc",
	});
	const sample_name = sample_rows[0]?.name || null;

	// A — empty ID Equals "" removed; list shows rows
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(false);
	await listview.filter_area.add(PDC_DOCTYPE, "name", "=", "", false);
	await pdc_list_remove_invalid_empty_filters(listview, { refresh: true });
	await pdc_list_wait_refresh(listview);
	const debug_a = pdc_list_get_filter_debug(listview);
	const args_a = listview.get_filters_for_args();
	push(
		"A_empty_id_equals_removed",
		(listview.data?.length ?? 0) > 0 &&
			!args_a.some(
				(f) => f[1] === "name" && f[2] === "=" && pdc_list_is_filter_value_empty(f[3])
			) &&
			(debug_a.filter_list_meta || []).every(
				(m) => !(m.fieldname === "name" && pdc_list_is_filter_value_empty(m.value))
			),
		{ debug: debug_a, args: args_a }
	);

	// B — valid ID filter preserved
	if (sample_name) {
		pdc_list_reset_reconcile_state(listview);
		await listview.filter_area.clear(true);
		pdc_list_reconcile_state(listview).user_interacted = true;
		await listview.filter_area.add(PDC_DOCTYPE, "name", "=", sample_name, true);
		await pdc_list_wait_refresh(listview);
		const args_b = listview.get_filters_for_args();
		push(
			"B_valid_id_filter_kept",
			args_b.some((f) => f[1] === "name" && f[3] === sample_name) &&
				(listview.data?.length ?? 0) >= 1,
			{ args: args_b, rows: listview.data?.length }
		);
		await listview.filter_area.clear(true);
		await listview.refresh();
	} else {
		push("B_valid_id_filter_kept", false, { skipped: "no sample PDC" });
	}

	// C — Is Set preserved
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(true);
	pdc_list_reconcile_state(listview).user_interacted = true;
	await listview.filter_area.add(PDC_DOCTYPE, "name", "is", "set", true);
	await pdc_list_wait_refresh(listview);
	const args_c = listview.get_filters_for_args();
	push(
		"C_is_set_filter_kept",
		args_c.some((f) => f[1] === "name" && f[2] === "is" && f[3] === "set") &&
			(listview.data?.length ?? 0) > 0,
		{ args: args_c }
	);
	await listview.filter_area.clear(true);
	await listview.refresh();

	// D — empty standard quick filter not in query args
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(true);
	const name_field = listview.page.fields_dict.name;
	if (name_field) {
		listview._pdc_programmatic_filter_change = true;
		await name_field.set_value("");
		listview._pdc_programmatic_filter_change = false;
	}
	await pdc_list_remove_invalid_empty_filters(listview, { refresh: true });
	await pdc_list_wait_refresh(listview);
	const args_d = listview.get_filters_for_args();
	push(
		"D_empty_standard_not_in_query",
		!args_d.some((f) => f[1] === "name" && pdc_list_is_filter_value_empty(f[3])),
		{ args: args_d }
	);

	// E — sanitize drops invalid tuple without touching valid
	const san_e = pdc_list_sanitize_filter_tuples([
		[PDC_DOCTYPE, "name", "=", ""],
		[PDC_DOCTYPE, "workflow_state", "=", "Registered"],
	]);
	push("E_sanitize_drops_only_invalid", san_e.length === 1 && san_e[0][1] === "workflow_state", {
		san_e,
	});

	// F — invalid empty equals row removed from FilterGroup after cleanup
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(false);
	await listview.filter_area.add(PDC_DOCTYPE, "name", "=", "", false);
	await listview.refresh();
	await pdc_list_wait_refresh(listview);
	const before_f = pdc_list_get_filter_debug(listview);
	await pdc_list_remove_invalid_empty_filters(listview, { refresh: true });
	await pdc_list_wait_refresh(listview);
	const after_f = pdc_list_get_filter_debug(listview);
	const had_invalid = (before_f.filter_list_meta || []).some(
		(m) => m.fieldname === "name" && pdc_list_is_filter_value_empty(m.value)
	);
	const no_invalid = !(after_f.filter_list_meta || []).some(
		(m) => m.fieldname === "name" && pdc_list_is_filter_value_empty(m.value)
	);
	push("F_empty_equals_row_removed", had_invalid && no_invalid, { before_f, after_f });

	const all_ok = results.every((r) => r.ok);
	console.table(results);
	return { all_ok, results };
};

frappe.listview_settings[PDC_DOCTYPE] = {
	get_indicator(doc) {
		const ws = (doc.workflow_state || "").trim();
		const cs = (doc.cheque_status || "").trim();
		const state = ws || cs;

		const red = [
			"Bounced",
			"Returned",
			"Returned to Customer",
			"Returned from Payee",
		].includes(state);
		const green = ["Cleared"].includes(state);
		const orange = ["Sent to Bank", "In Clearing"].includes(state) || cs === "In Clearing";
		const blue = ["Registered", "Issued"].includes(state);

		if (green) return [__("Cleared"), "green", `cheque_status,=,Cleared`];
		if (red) {
			const filter_field = cs ? "cheque_status" : "workflow_state";
			const filter_value = cs || ws;
			return [__(state), "red", `${filter_field},=,${filter_value}`];
		}
		if (orange) return [__("In Clearing"), "orange", "cheque_status,=,In Clearing"];
		if (blue) return [__(state), "blue", `workflow_state,=,${state}`];
		if ((ws || cs) === "Draft") return [__(state), "gray", "workflow_state,=,Draft"];
		return [__(ws || cs || "—"), "gray", ""];
	},

	onload(listview) {
		pdc_list_clear_stale_route_options();
		if (Array.isArray(listview.filters)) {
			listview.filters = pdc_list_sanitize_filter_tuples(listview.filters);
		}
		pdc_list_bind_invalid_filter_cleanup(listview);
		const cleaned = pdc_list_remove_invalid_empty_filters_sync(listview);
		if (cleaned) {
			pdc_list_reconcile_state(listview).invalid_filter_cleanup_done = true;
			listview.refresh();
		}

		const dt = frappe.datetime;

		const set_due_range = (from, to) => {
			pdc_list_reconcile_state(listview).user_interacted = true;
			listview.filter_area.clear();
			if (from) listview.filter_area.add(PDC_DOCTYPE, "cheque_due_date", ">=", from);
			if (to) listview.filter_area.add(PDC_DOCTYPE, "cheque_due_date", "<=", to);
			listview.refresh();
		};

		listview.page.add_menu_item(__("Due Today"), () => {
			const d = dt.get_today();
			set_due_range(d, d);
		});

		listview.page.add_menu_item(__("Due This Week"), () => {
			set_due_range(dt.week_start(), dt.week_end());
		});

		listview.page.add_menu_item(__("Overdue"), () => {
			pdc_list_apply_filters(
				listview,
				[
					[PDC_DOCTYPE, "cheque_due_date", "<", dt.get_today()],
					[PDC_DOCTYPE, "cheque_status", "!=", "Cleared"],
				],
				{ clear: true }
			);
		});

		listview.page.add_menu_item(__("Near Due (next 7 days)"), () => {
			set_due_range(dt.get_today(), dt.add_days(dt.get_today(), 7));
		});

		listview.page.add_menu_item(__("Cleared"), () => {
			pdc_list_apply_filters(listview, [[PDC_DOCTYPE, "cheque_status", "=", "Cleared"]], {
				clear: true,
			});
		});

		listview.page.add_menu_item(__("Bounced"), () => {
			pdc_list_apply_filters(listview, [[PDC_DOCTYPE, "cheque_status", "=", "Bounced"]], {
				clear: true,
			});
		});

		listview.page.add_menu_item(__("In Clearing"), () => {
			pdc_list_apply_filters(
				listview,
				[[PDC_DOCTYPE, "cheque_status", "=", "In Clearing"]],
				{
					clear: true,
				}
			);
		});

		listview.page.add_menu_item(__("At Bank"), () => {
			pdc_list_apply_filters(listview, [[PDC_DOCTYPE, "is_at_bank", "=", 1]], {
				clear: true,
			});
		});

		const refresh_counts = async () => {
			try {
				const [at_bank, overdue_recv] = await Promise.all([
					frappe.db.count(PDC_DOCTYPE, {
						cheque_direction: "Receivable",
						is_at_bank: 1,
					}),
					frappe.db.count(PDC_DOCTYPE, {
						cheque_direction: "Receivable",
						cheque_due_date: ["<", dt.get_today()],
						cheque_status: ["!=", "Cleared"],
					}),
				]);
				listview.page.set_indicator(
					__("Receivable At Bank: {0} · Overdue Receivable: {1}", [
						at_bank || 0,
						overdue_recv || 0,
					]),
					(overdue_recv || 0) > 0 ? "orange" : "blue"
				);
			} catch (e) {
				// ignore
			}
		};

		refresh_counts();
		if (typeof listview.on === "function") {
			listview.on("after_refresh", refresh_counts);
		}

		if (frappe.utils.get_url_arg("run_pdc_list_filter_e2e") === "1" && cur_list === listview) {
			setTimeout(() => {
				erpnext_extensions.cheque_management.pdc_list_view.run_filter_e2e(listview);
			}, 1500);
		}
	},
};
