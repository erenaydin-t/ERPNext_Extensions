frappe.provide("erpnext_extensions.cheque_management.pdc_list_view");

const PDC_DOCTYPE = "Post Dated Cheque";

function pdc_list_reconcile_state(listview) {
	if (!listview._pdc_filter_reconcile_state) {
		listview._pdc_filter_reconcile_state = {
			initial_pass_done: false,
			auto_cleared: false,
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
	const chip_filters = filter_area?.filter_list?.get_filters?.() || [];
	const standard_filters = filter_area?.get_standard_filters?.() || [];
	const combined = filter_area?.get?.() || [];
	return {
		route_options: frappe.route_options,
		url_search: window.location.search,
		chip_filters,
		standard_filters,
		combined_filters: combined,
		data_length: listview.data?.length ?? 0,
		reconcile_state: { ...pdc_list_reconcile_state(listview) },
	};
}

/** True only when empty list is caused by hidden (standard-bar) filters, not chips or URL. */
function pdc_list_should_auto_clear_hidden_filters(listview, debug) {
	void listview;
	if (pdc_list_has_url_filters()) {
		return false;
	}
	const chip_count = debug.chip_filters?.length ?? 0;
	const combined_count = debug.combined_filters?.length ?? 0;
	if (chip_count > 0) {
		return false;
	}
	if (combined_count === 0) {
		return false;
	}
	// filter_area.get() = chip filters + standard filters; with zero chips, all are standard-bar / restored "=" filters
	const standard_count = debug.standard_filters?.length ?? 0;
	if (standard_count === 0) {
		return false;
	}
	return standard_count === combined_count;
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
	const orig = filter_area.refresh_list_view.bind(filter_area);
	filter_area.refresh_list_view = function () {
		const state = pdc_list_reconcile_state(listview);
		if (state.initial_pass_done && !listview._pdc_programmatic_filter_change) {
			state.user_interacted = true;
		}
		return orig();
	};
}

function pdc_list_bind_empty_list_reconcile(listview) {
	pdc_list_bind_filter_user_interaction(listview);

	listview.on("after_refresh", async () => {
		const state = pdc_list_reconcile_state(listview);

		if (state.auto_cleared || state.user_interacted) {
			if (!state.initial_pass_done) {
				state.initial_pass_done = true;
			}
			return;
		}
		if (state.initial_pass_done) {
			return;
		}

		state.initial_pass_done = true;

		const db_count = await frappe.db.count(PDC_DOCTYPE);
		const row_count = listview.data?.length ?? 0;
		if (!db_count || row_count > 0) {
			return;
		}

		const debug = pdc_list_get_filter_debug(listview);
		if (!pdc_list_should_auto_clear_hidden_filters(listview, debug)) {
			return;
		}

		state.auto_cleared = true;
		console.warn("[PDC List] Hidden standard/saved filters returned zero rows; clearing.", debug);
		frappe.show_alert(
			{
				message: __(
					"No Post Dated Cheques match the hidden filters in the list header. Filters were cleared."
				),
				indicator: "orange",
			},
			6
		);
		listview._pdc_programmatic_filter_change = true;
		try {
			await listview.filter_area.clear(true);
		} finally {
			listview._pdc_programmatic_filter_change = false;
		}
	});
}

function pdc_list_apply_filters(listview, filters, { clear = true } = {}) {
	const chain = clear ? listview.filter_area.clear(false) : Promise.resolve();
	return chain
		.then(() => {
			const promises = (filters || []).map((f) => listview.filter_area.add(f, false));
			return Promise.all(promises);
		})
		.then(() => listview.refresh());
}

function pdc_list_reset_reconcile_state(listview) {
	listview._pdc_filter_reconcile_state = {
		initial_pass_done: false,
		auto_cleared: false,
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

erpnext_extensions.cheque_management.pdc_list_view.get_filter_debug = pdc_list_get_filter_debug;
erpnext_extensions.cheque_management.pdc_list_view.should_auto_clear_hidden_filters =
	pdc_list_should_auto_clear_hidden_filters;
erpnext_extensions.cheque_management.pdc_list_view.reset_reconcile_state = pdc_list_reset_reconcile_state;

erpnext_extensions.cheque_management.pdc_list_view.run_filter_e2e = async function (listview) {
	const results = [];
	const push = (name, ok, detail) => results.push({ test: name, ok, detail });

	const db_count = await frappe.db.count(PDC_DOCTYPE);
	push("db_has_records", db_count > 0, { db_count });

	// D — fresh list, no filters
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(true);
	await listview.refresh();
	await pdc_list_wait_refresh(listview);
	const debug_d = pdc_list_get_filter_debug(listview);
	push(
		"D_fresh_list_no_filters",
		(listview.data?.length ?? 0) > 0 && (debug_d.combined_filters?.length ?? 0) === 0,
		debug_d
	);

	// E — manual clear
	pdc_list_apply_filters(
		listview,
		[[PDC_DOCTYPE, "cheque_direction", "=", "Receivable"]],
		{ clear: true }
	);
	await pdc_list_wait_refresh(listview);
	pdc_list_reconcile_state(listview).user_interacted = true;
	await listview.filter_area.clear(true);
	await listview.refresh();
	await pdc_list_wait_refresh(listview);
	const debug_e = pdc_list_get_filter_debug(listview);
	push(
		"E_manual_clear_shows_rows",
		(listview.data?.length ?? 0) > 0 && (debug_e.combined_filters?.length ?? 0) === 0,
		debug_e
	);

	// B — visible chip filter, zero rows, no auto-clear
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(false);
	await listview.filter_area.add(
		[PDC_DOCTYPE, "name", "=", "__PDC_E2E_NO_SUCH_DOC__"],
		false
	);
	await listview.refresh();
	await pdc_list_wait_refresh(listview);
	const debug_b = pdc_list_get_filter_debug(listview);
	const state_b = pdc_list_reconcile_state(listview);
	push(
		"B_visible_chip_empty_no_autoclear",
		(debug_b.chip_filters?.length ?? 0) > 0 &&
			(listview.data?.length ?? 0) === 0 &&
			!state_b.auto_cleared &&
			(debug_b.combined_filters?.length ?? 0) > 0,
		debug_b
	);
	pdc_list_reconcile_state(listview).user_interacted = true;
	await listview.filter_area.clear(true);
	await listview.refresh();

	// C — URL query present → should_auto_clear false
	const debug_c = {
		chip_filters: [],
		standard_filters: [[PDC_DOCTYPE, "workflow_state", "=", "X"]],
		combined_filters: [[PDC_DOCTYPE, "workflow_state", "=", "X"]],
		url_search: "?workflow_state=X",
	};
	const url_saved = window.location.search;
	history.replaceState(null, "", `${window.location.pathname}?workflow_state=__PDC_E2E__`);
	push(
		"C_url_filter_blocks_autoclear",
		!pdc_list_should_auto_clear_hidden_filters(listview, {
			...debug_c,
			url_search: window.location.search,
		}),
		{ url: window.location.search }
	);
	history.replaceState(null, "", window.location.pathname + url_saved);

	// A — hidden standard filter → auto-clear (simulate first load)
	pdc_list_reset_reconcile_state(listview);
	await listview.filter_area.clear(false);
	const name_field = listview.page.fields_dict.name;
	if (name_field) {
		listview._pdc_programmatic_filter_change = true;
		await name_field.set_value("__PDC_E2E_NO_SUCH__");
		listview._pdc_programmatic_filter_change = false;
	}
	await listview.refresh();
	await pdc_list_wait_refresh(listview);
	await pdc_list_wait_refresh(listview);
	const debug_a = pdc_list_get_filter_debug(listview);
	const state_a = pdc_list_reconcile_state(listview);
	push(
		"A_hidden_standard_autoclear",
		state_a.auto_cleared &&
			(listview.data?.length ?? 0) > 0 &&
			(debug_a.combined_filters?.length ?? 0) === 0,
		debug_a
	);

	const all_ok = results.every((r) => r.ok);
	console.table(results);
	return { all_ok, results };
};

frappe.listview_settings[PDC_DOCTYPE] = {
	get_indicator(doc) {
		const ws = (doc.workflow_state || "").trim();
		const cs = (doc.cheque_status || "").trim();
		const state = ws || cs;

		const red = ["Bounced", "Returned", "Returned to Customer", "Returned from Payee"].includes(
			state
		);
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
		pdc_list_bind_empty_list_reconcile(listview);

		const dt = frappe.datetime;

		const set_due_range = (from, to) => {
			listview.filter_area.clear();
			if (from) listview.filter_area.add([PDC_DOCTYPE, "cheque_due_date", ">=", from]);
			if (to) listview.filter_area.add([PDC_DOCTYPE, "cheque_due_date", "<=", to]);
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
			pdc_list_apply_filters(listview, [[PDC_DOCTYPE, "cheque_status", "=", "In Clearing"]], {
				clear: true,
			});
		});

		listview.page.add_menu_item(__("At Bank"), () => {
			pdc_list_apply_filters(listview, [[PDC_DOCTYPE, "is_at_bank", "=", 1]], { clear: true });
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
					__("Receivable At Bank: {0} · Overdue Receivable: {1}", [at_bank || 0, overdue_recv || 0]),
					(overdue_recv || 0) > 0 ? "orange" : "blue"
				);
			} catch (e) {
				// ignore
			}
		};

		refresh_counts();
		listview.on("after_refresh", refresh_counts);

		if (frappe.utils.get_url_arg("run_pdc_list_filter_e2e") === "1" && cur_list === listview) {
			setTimeout(() => {
				erpnext_extensions.cheque_management.pdc_list_view.run_filter_e2e(listview);
			}, 1500);
		}
	},
};
