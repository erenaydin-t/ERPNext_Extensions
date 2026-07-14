{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_events.js" %}
{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_store.js" %}
{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_plugins.js" %}
{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/explorer_workspace_state.js" %}
{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/core/ae_user_preferences.js" %}
{% include "erpnext_extensions/erpnext_extensions/page/account_explorer/adapters/ae_datatable_adapter.js" %}

frappe.provide("erpnext_extensions.account_explorer");

function ae_clone_document_scope(scope) {
	return {
		...scope,
		voucher: { ...(scope.voucher || {}) },
		accounting: { ...(scope.accounting || {}) },
		accounting_dimensions: { ...(scope.accounting_dimensions || {}) },
		currency: { ...(scope.currency || {}) },
		status: { ...(scope.status || {}) },
	};
}

function ae_clear_advanced_document_scope(scope, status_defaults = {}) {
	return {
		...scope,
		finance_book: null,
		voucher: {
			voucher_type: null,
			voucher_no: null,
			against_voucher_type: null,
			against_voucher_no: null,
			reference_no: null,
		},
		accounting: {
			account: null,
			party_type: null,
			party: null,
		},
		accounting_dimensions: {},
		currency: {
			currency_type: scope.currency?.currency_type || "account_currency",
			currency: null,
		},
		status: {
			include_opening_entries: status_defaults.include_opening_entries ?? 1,
			include_cancelled_entries: status_defaults.include_cancelled_entries ?? 0,
			include_default_finance_book_entries: status_defaults.include_default_finance_book_entries ?? 1,
			include_period_closing_vouchers: status_defaults.include_period_closing_vouchers ?? 0,
		},
	};
}

function ae_count_active_document_scope_filters(scope) {
	if (!scope) {
		return 0;
	}
	let count = 0;
	if (scope.finance_book) {
		count += 1;
	}
	const voucher = scope.voucher || {};
	["voucher_type", "voucher_no", "against_voucher_type", "against_voucher_no", "reference_no"].forEach((key) => {
		if (voucher[key]) {
			count += 1;
		}
	});
	const accounting = scope.accounting || {};
	["account", "party_type", "party"].forEach((key) => {
		const value = accounting[key];
		if (value && (!Array.isArray(value) || value.length)) {
			count += 1;
		}
	});
	Object.values(scope.accounting_dimensions || {}).forEach((value) => {
		if (value && (!Array.isArray(value) || value.length)) {
			count += 1;
		}
	});
	if (scope.currency?.currency) {
		count += 1;
	}
	if (scope.currency?.currency_type && scope.currency.currency_type !== "account_currency") {
		count += 1;
	}
	const status = scope.status || {};
	if (!status.include_opening_entries) {
		count += 1;
	}
	if (status.include_cancelled_entries) {
		count += 1;
	}
	if (!status.include_default_finance_book_entries) {
		count += 1;
	}
	if (status.include_period_closing_vouchers) {
		count += 1;
	}
	return count;
}

function ae_serialize_document_scope(scope) {
	return JSON.stringify({
		company: scope.company || null,
		fiscal_year: scope.fiscal_year || null,
		from_date: scope.from_date || null,
		to_date: scope.to_date || null,
		finance_book: scope.finance_book || null,
		hide_zero_rows: scope.hide_zero_rows ?? 1,
		voucher: { ...(scope.voucher || {}) },
		accounting: { ...(scope.accounting || {}) },
		accounting_dimensions: { ...(scope.accounting_dimensions || {}) },
		currency: { ...(scope.currency || {}) },
		status: { ...(scope.status || {}) },
	});
}

function ae_normalize_multi_value(value) {
	if (value === null || value === undefined || value === "") {
		return null;
	}
	if (Array.isArray(value)) {
		const items = value.filter((item) => item !== null && item !== undefined && item !== "");
		if (!items.length) {
			return null;
		}
		return items.length === 1 ? items[0] : items;
	}
	return value;
}

function ae_trim_compact_decimals(value) {
	const str = String(value);
	if (!str.includes(".")) {
		return str;
	}
	return str.replace(/(\.\d*?[1-9])0+$/, "$1").replace(/\.0+$/, "").replace(/\.$/, "");
}

function ae_format_amount_with_mode(value, currency_code, mode = "auto") {
	const num = flt(value);
	const full = format_currency(num, currency_code);
	const normalized_mode = String(mode || "auto").toLowerCase();
	if (normalized_mode === "raw") {
		return { compact: full, full };
	}
	const abs = Math.abs(num);
	const format_scaled = (divisor, suffix) => ({
		compact: `${ae_trim_compact_decimals((num / divisor).toFixed(divisor >= 1000000000 ? 1 : divisor >= 1000000 ? 1 : 2))} ${suffix}`,
		full,
	});
	if (normalized_mode === "trillions" || (normalized_mode === "auto" && abs >= 1e12)) {
		return format_scaled(1e12, "T");
	}
	if (normalized_mode === "billions" || (normalized_mode === "auto" && abs >= 1e9)) {
		return format_scaled(1e9, "B");
	}
	if (normalized_mode === "millions" || (normalized_mode === "auto" && abs >= 1e6)) {
		return format_scaled(1e6, "M");
	}
	if (normalized_mode === "thousands" || (normalized_mode === "auto" && abs >= 1e3)) {
		return format_scaled(1e3, "K");
	}
	return { compact: full, full };
}

function ae_format_compact_amount(value, currency_code) {
	return ae_format_amount_with_mode(value, currency_code, "auto");
}

function ae_scope_value_to_control(value) {
	if (Array.isArray(value)) {
		return value;
	}
	if (value) {
		return [value];
	}
	return [];
}

function ae_clone_analysis_context(context) {
	return {
		...context,
		account_scope: { ...(context.account_scope || {}) },
		party_scope: { ...(context.party_scope || {}) },
		unified_party_scope: { ...(context.unified_party_scope || {}) },
		dimension_scope: { ...(context.dimension_scope || {}) },
		voucher_scope: { ...(context.voucher_scope || {}) },
	};
}

function ae_default_document_scope(overrides = {}) {
	return {
		company: null,
		fiscal_year: null,
		from_date: null,
		to_date: null,
		finance_book: null,
		hide_zero_rows: 1,
		voucher: {
			voucher_type: null,
			voucher_no: null,
			against_voucher_type: null,
			against_voucher_no: null,
			reference_no: null,
		},
		accounting: {
			account: null,
			party_type: null,
			party: null,
		},
		accounting_dimensions: {},
		currency: {
			currency_type: "account_currency",
			currency: null,
		},
		status: {
			include_opening_entries: 1,
			include_cancelled_entries: 0,
			include_default_finance_book_entries: 1,
			include_period_closing_vouchers: 0,
		},
		...overrides,
	};
}

frappe.pages["account-explorer"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Account Explorer"),
		single_column: true,
	});

	page.main.addClass("account-explorer-page");
	wrapper.account_explorer = new erpnext_extensions.account_explorer.Controller(page);

	$(wrapper).bind("show", () => {
		wrapper.account_explorer?.on_page_show();
	});
	$(wrapper).bind("hide", () => {
		wrapper.account_explorer?.on_page_hide();
	});
};

erpnext_extensions.account_explorer.Controller = class AccountExplorerController {
	constructor(page) {
		this.page = page;
		this.api_base = "erpnext_extensions.iran_accounting.account_explorer";
		this.metadata = null;
		this.rows = [];
		this.totals = {};
		this.currency_code = null;
		this.pagination = { page: 1, page_size: 50, total_rows: 0, has_next: false };
		this.warnings = [];
		this.voucher_header = null;
		this.gl_dimensions = [];
		this.gl_dimension_column_visibility = {};
		this.last_gl_columns = [];
		this.last_summary_columns = [];
		this.show_full_voucher_dimensions = false;
		this.show_optional_full_voucher_columns = false;
		this.grid_hidden_columns = [];
		this.grid_column_order = [];
		this.grid_column_widths = {};
		this.grid_sticky_column = null;
		this.number_format_mode = "auto";
		this.grid_density = "comfortable";
		this._presentation_signature = null;
		this._$grid_prefs_controls = null;
		this.summary_load_error = null;
		this._grid_keyboard_bound = false;
		this.grid_perf_report = { refresh_history: [] };
		this._grid_perf_token = null;
		this._pending_grid_perf_operation = null;
		this._grid_lifecycle_counters = { grid_render_count: 0 };
		this._last_perf_phases = {};
		this.grid_render_generation = 0;
		this._summary_refresh_tail = Promise.resolve();
		this.filter_panel_open = false;
		this.filter_controls = {};
		this.saved_views = [];
		this.active_saved_view = null;

		this.document_scope = ae_default_document_scope();

		this.analysis_context = {
			view_axis: "account_level",
			level_sequence: null,
			account_scope: {
				mode: "tree",
				selected_account: null,
				virtual_row_key: null,
				is_virtual_group: 0,
				level_sequence: null,
				tree_root_account: null,
			},
			party_scope: {
				party_type: null,
				selected_party: null,
			},
			unified_party_scope: {
				selected_unified_party: null,
				include_unmapped: 0,
			},
			dimension_scope: {
				dimension_type: null,
				selected_dimension_value: null,
			},
			voucher_scope: {
				voucher_type: null,
				voucher_no: null,
			},
			detail_mode: "summary",
			sort_field: "display_code",
			sort_order: "asc",
			page: 1,
			page_size: 50,
		};

		this.breadcrumbs = [];
		this._datatable_grid_namespace = ".aeDatatableGrid";
		this._datatable_grid_bound = false;
		this._suppress_datatable_sort_events = false;
		this._init_explorer_architecture();
		this.setup_actions();
		this.render_shell();
		this.load_metadata();
	}

	_init_explorer_architecture() {
		const core = erpnext_extensions.account_explorer.core;
		const adapters = erpnext_extensions.account_explorer.adapters;

		this.events = new core.ExplorerEventBus();
		this.store = new core.ExplorerStore(this.events);
		this.plugins = new core.ExplorerPluginRegistry(this.events, this.store);
		this.workspace_state = new core.ExplorerWorkspaceState(this.store, this.events);
		this.user_preferences = new core.AEUserPreferences(this);
		this.datatable_adapter = new adapters.AEDataTableAdapter(this.events);
		this._page_shown = false;
		this.user_preferences.bind_controller_events();

		this.store.replace(
			{
				document_scope: this.document_scope,
				analysis_context: this.analysis_context,
				presentation: this.build_presentation_state(),
				selection: {
					selected_row_key: null,
					checked_row_keys: [],
				},
				navigation: {
					breadcrumbs: this.breadcrumbs,
				},
				loading: {
					metadata: true,
					summary: false,
				},
			},
			{ silent: true }
		);
		this.breadcrumbs = this.store.get("navigation").breadcrumbs;
	}

	_reset_breadcrumbs(trail = []) {
		const crumbs = this.store.get("navigation").breadcrumbs;
		crumbs.length = 0;
		(trail || []).forEach((chip) => crumbs.push(chip));
		this.breadcrumbs = crumbs;
		this._sync_store_context({ emit: false });
	}

	sync_scope_trail_from_store() {
		this.breadcrumbs = [...(this.store.get("navigation")?.breadcrumbs || [])];
	}

	_sync_store_context({ emit = false } = {}) {
		const patch = {
			document_scope: this.document_scope,
			analysis_context: this.analysis_context,
			presentation: this.build_presentation_state(),
			navigation: { breadcrumbs: this.breadcrumbs },
		};
		this.store.patch(patch, { silent: !emit });
		if (emit) {
			this.events.emit("context:change", patch);
		}
	}

	on_page_show() {
		if (!this._page_shown) {
			this._page_shown = true;
			return;
		}
		if (!this.metadata?.enabled) {
			return;
		}
		this.events.emit("page:show");
		if (this.document_scope.company && this.document_scope.from_date && this.document_scope.to_date) {
			this._pending_grid_perf_operation = "navigate_back";
			this.refresh_summary();
		}
	}

	on_page_hide() {
		// Desk navigation away: flush pending debounce without waiting for 600ms.
		// Uses async path; pagehide/beforeunload uses sync path for hard reload.
		this.user_preferences?.flush_save?.({ sync: false });
		this.datatable_adapter?.cancel_pending_mount?.();
		$("body").find(".ae-grid-copy-menu").remove();
		$(document).off("click.aeGridCopyMenu");
		if (this.is_datatable_summary_enabled()) {
			this.destroy_summary_datatable();
		}
		this._invalidate_grid_render();
	}

	_refresh_after_drill() {
		this._pending_grid_perf_operation = "drill_down";
		this.refresh_summary();
	}

	setup_actions() {
		this.page.set_primary_action(__("Refresh"), () => this.refresh_summary());
	}

	render_shell() {
		this.$container = $('<div class="ae-shell"></div>').appendTo(this.page.main);
		this.$disabled = $('<div class="ae-disabled"></div>').appendTo(this.$container);
		this.$toolbar = $('<div class="ae-toolbar"></div>').appendTo(this.$container);
		this.$filter_panel = $('<div class="ae-filter-panel ae-filter-panel--collapsed" id="ae-filter-panel"></div>').appendTo(
			this.$container
		);
		this.$nav = $('<div class="ae-nav"></div>').appendTo(this.$container);
		this.$context = $('<div class="ae-context-bar"></div>').appendTo(this.$container);
		this.$detail_header = $('<div class="ae-detail-header"></div>').appendTo(this.$container);
		this.$actions = $('<div class="ae-context-actions"></div>').appendTo(this.$container).hide();
		this.$grid = $('<div class="ae-grid-wrap" tabindex="0" role="region" aria-label="' + __("Summary grid") + '"></div>').appendTo(this.$container);
		this.$grid_status = $('<div class="ae-grid-status visually-hidden" aria-live="polite" aria-atomic="true"></div>').appendTo(this.$container);
		this._bind_datatable_grid_interactions();
		this._bind_grid_keyboard_shortcuts();
		this.$member_panel = $('<div class="ae-member-panel"></div>').appendTo(this.$container).hide();
		this.$totals = $('<div class="ae-totals"></div>').appendTo(this.$container);
		this.$pagination = $('<div class="ae-pagination"></div>').appendTo(this.$container);
		this.$warnings = $('<div class="text-muted small mt-2"></div>').appendTo(this.$container);
	}

	_bind_datatable_grid_interactions() {
		if (this._datatable_grid_bound || !this.$grid) {
			return;
		}
		this._datatable_grid_bound = true;
		this.$grid.on(`click${this._datatable_grid_namespace}`, (event) => {
			if (!this.should_handle_datatable_row_event()) {
				return;
			}
			if (this.datatable_adapter.is_interactive_grid_target(event.target)) {
				return;
			}
			const source_row = this.datatable_adapter.resolve_row_from_event(event);
			if (source_row) {
				this.handle_summary_row_click(source_row);
			}
		});
		this.$grid.on(`dblclick${this._datatable_grid_namespace}`, (event) => {
			if (!this.should_handle_datatable_row_event()) {
				return;
			}
			if (this.datatable_adapter.is_interactive_grid_target(event.target)) {
				return;
			}
			const source_row = this.datatable_adapter.resolve_row_from_event(event);
			if (source_row) {
				this.handle_summary_row_dblclick(source_row);
			}
		});
		this.$grid.on(`click${this._datatable_grid_namespace}`, ".ae-voucher-action", (event) => {
			if (!this.should_handle_datatable_row_event()) {
				return;
			}
			event.preventDefault();
			event.stopPropagation();
			const source_row = this.datatable_adapter.resolve_row_from_event(event);
			const action = $(event.currentTarget).data("action");
			this.handle_voucher_row_action(source_row, action);
		});
	}

	should_handle_datatable_row_event() {
		return (
			this.is_datatable_summary_enabled() &&
			this.analysis_context.detail_mode === "summary" &&
			this.datatable_adapter?.is_mounted?.()
		);
	}

	update_context_actions() {
		const has_voucher_drill =
			this.analysis_context.view_axis === "voucher" &&
			(this.analysis_context.detail_mode === "grouped_gl" ||
				this.analysis_context.voucher_scope?.voucher_no);
		if (this.$back_btn) {
			this.$back_btn.toggle(
				!!this.get_scope_trail().length ||
					has_voucher_drill ||
					this.analysis_context.detail_mode === "grouped_gl"
			);
		}
	}

	load_metadata() {
		frappe.call({
			method: `${this.api_base}.get_account_explorer_metadata`,
			callback: (r) => {
				this.metadata = r.message || {};
				this.store.patch({ loading: { metadata: false } });
				if (!this.metadata.enabled) {
					this.show_disabled(
						__("Account Explorer is not enabled. Open Iran Accounting Settings to configure and enable it.")
					);
					return;
				}
				void this._initialize_after_metadata();
			},
		});
	}

	async _initialize_after_metadata() {
		await this.user_preferences.load();
		this.user_preferences.apply_axis_to_controller();
		this.$disabled.hide();
		this.setup_toolbar();
		this.render_navigator();
		this.render_breadcrumbs();
		if (this.metadata.saved_views_enabled) {
			this.refresh_saved_views_list();
		}
	}

	show_disabled(message) {
		this.$disabled.text(message).show();
		this.$toolbar.hide();
		this.$nav.hide();
	}

	setup_toolbar() {
		this.$toolbar.empty();
		const defaults = this.metadata.defaults || {};
		const scopeDefaults = defaults.document_scope || defaults;

		const $row_scope = $('<div class="ae-toolbar-row ae-toolbar-row--scope"></div>').appendTo(this.$toolbar);
		const $scope = $('<div class="ae-toolbar-scope"></div>').appendTo($row_scope);
		$('<div class="ae-toolbar-section-label">').text(__("Scope")).appendTo($scope);
		const $scope_fields = $('<div class="ae-toolbar-scope-fields"></div>').appendTo($scope);

		this.company_field = frappe.ui.form.make_control({
			parent: $scope_fields,
			df: {
				fieldtype: "Link",
				label: __("Company"),
				fieldname: "company",
				options: "Company",
				reqd: 1,
				change: () => {
					this.document_scope.company = this.company_field.get_value();
				},
			},
			render_input: true,
		});
		if (scopeDefaults.company) {
			this.company_field.set_value(scopeDefaults.company);
			this.document_scope.company = scopeDefaults.company;
		}

		this.fy_field = frappe.ui.form.make_control({
			parent: $scope_fields,
			df: {
				fieldtype: "Link",
				label: __("Fiscal Year"),
				fieldname: "fiscal_year",
				options: "Fiscal Year",
				change: () => {
					this.document_scope.fiscal_year = this.fy_field.get_value();
					this.sync_dates_from_fy();
				},
			},
			render_input: true,
		});
		if (scopeDefaults.fiscal_year) {
			this.fy_field.set_value(scopeDefaults.fiscal_year);
			this.document_scope.fiscal_year = scopeDefaults.fiscal_year;
		}

		this.from_date_field = frappe.ui.form.make_control({
			parent: $scope_fields,
			df: {
				fieldtype: "Date",
				label: __("From Date"),
				fieldname: "from_date",
				reqd: 1,
				change: () => {
					this.document_scope.from_date = this.from_date_field.get_value();
				},
			},
			render_input: true,
		});

		this.to_date_field = frappe.ui.form.make_control({
			parent: $scope_fields,
			df: {
				fieldtype: "Date",
				label: __("To Date"),
				fieldname: "to_date",
				reqd: 1,
				change: () => {
					this.document_scope.to_date = this.to_date_field.get_value();
				},
			},
			render_input: true,
		});

		if (scopeDefaults.from_date) {
			this.from_date_field.set_value(scopeDefaults.from_date);
			this.document_scope.from_date = scopeDefaults.from_date;
		}
		if (scopeDefaults.to_date) {
			this.to_date_field.set_value(scopeDefaults.to_date);
			this.document_scope.to_date = scopeDefaults.to_date;
		}

		this.analysis_context.level_sequence = this.metadata.default_level_sequence;
		if (!this.analysis_context.page_size) {
			this.analysis_context.page_size = defaults.page_size || 50;
		}
		const defaultDimensionType =
			this.metadata.default_dimension_type || this.metadata.default_dimension_field || null;
		if (defaultDimensionType) {
			this.analysis_context.dimension_scope.dimension_type = defaultDimensionType;
		}
		if (scopeDefaults.status) {
			this.document_scope.status = { ...this.document_scope.status, ...scopeDefaults.status };
		}
		if (scopeDefaults.currency) {
			this.document_scope.currency = { ...this.document_scope.currency, ...scopeDefaults.currency };
		}

		const $row_actions = $('<div class="ae-toolbar-row ae-toolbar-row--actions"></div>').appendTo(this.$toolbar);

		$('<button type="button" class="btn btn-primary btn-sm ae-btn-apply">')
			.text(__("Apply"))
			.on("click", () => this.apply_scope())
			.appendTo($row_actions);

		const $secondary_group = $('<div class="ae-toolbar-group ae-toolbar-group--secondary"></div>').appendTo(
			$row_actions
		);

		this.$advanced_filters_btn = $('<button type="button" class="btn btn-default btn-sm ae-advanced-filters-btn">')
			.text(__("Filters"))
			.attr("aria-expanded", "false")
			.attr("aria-controls", "ae-filter-panel")
			.on("click", () => this.toggle_filter_panel())
			.appendTo($secondary_group);

		if (this.metadata.saved_views_enabled) {
			this.setup_saved_views_ui($secondary_group);
		}

		this.setup_export_ui($secondary_group);

		const $utility_group = $('<div class="ae-toolbar-group ae-toolbar-group--utility"></div>').appendTo($row_actions);
		this.$back_btn = $('<button type="button" class="btn btn-default btn-sm ae-btn-back">')
			.text(__("Back"))
			.hide()
			.on("click", () => this.go_back())
			.appendTo($utility_group);
		this.setup_reset_dropdown($utility_group);

		this.setup_filter_panel(scopeDefaults);
		this.update_filter_panel_ui();
		this.update_context_actions();
	}

	setup_reset_dropdown($parent) {
		const $group = $('<div class="ae-reset-group btn-group"></div>').appendTo($parent);
		$('<button type="button" class="btn btn-default btn-sm dropdown-toggle ae-reset-btn">')
			.text(__("Reset"))
			.attr("data-toggle", "dropdown")
			.attr("aria-haspopup", "true")
			.attr("aria-expanded", "false")
			.appendTo($group);
		const $menu = $('<ul class="dropdown-menu dropdown-menu-right ae-reset-menu"></ul>').appendTo($group);
		$("<li>")
			.append(
				$("<a href='#'>")
					.text(__("Reset Analysis"))
					.on("click", (event) => {
						event.preventDefault();
						this.reset_analysis();
					})
			)
			.appendTo($menu);
		$("<li>")
			.append(
				$("<a href='#'>")
					.text(__("Reset Document Scope"))
					.on("click", (event) => {
						event.preventDefault();
						this.reset_document_scope();
					})
			)
			.appendTo($menu);
	}

	get_currency_type_label() {
		const type = this.document_scope?.currency?.currency_type || "account_currency";
		const match = (this.metadata?.currency_types || []).find((row) => row.value === type);
		return match?.label || type;
	}

	set_currency_mode(currency_type) {
		this.document_scope.currency = {
			...this.document_scope.currency,
			currency_type,
		};
		if (this.filter_controls?.currency_type) {
			this.filter_controls.currency_type.set_value(currency_type);
		}
		this.render_navigator();
		this.update_advanced_filters_button();
		this.render_filter_summary();
		if (this.document_scope.from_date && this.document_scope.to_date) {
			this.refresh_summary();
		}
	}

	toggle_sort(field) {
		if (this.analysis_context.sort_field === field) {
			this.analysis_context.sort_order = this.analysis_context.sort_order === "asc" ? "desc" : "asc";
		} else {
			this.analysis_context.sort_field = field;
			this.analysis_context.sort_order = "asc";
		}
		this.analysis_context.page = 1;
		this.refresh_summary();
	}

	_patch_presentation({ schedule_save = true } = {}) {
		const presentation = this.build_presentation_state();
		const signature = JSON.stringify(presentation);
		if (this._presentation_signature === signature) {
			return false;
		}
		this._presentation_signature = signature;
		this.store.patch({ presentation });
		if (schedule_save && !this.user_preferences?.is_hydrating?.()) {
			if (this.user_preferences) {
				this.user_preferences._applied_axis_signature = null;
			}
			this.user_preferences?.schedule_save?.();
		}
		return true;
	}

	handle_datatable_server_sort(column_id, column) {
		if (this._suppress_datatable_sort_events || !column_id) {
			return;
		}
		const next_order = column?.sortOrder === "desc" ? "desc" : "asc";
		if (
			this.analysis_context.sort_field === column_id &&
			this.analysis_context.sort_order === next_order
		) {
			return;
		}
		this.analysis_context.sort_field = column_id;
		this.analysis_context.sort_order = next_order;
		this.analysis_context.page = 1;
		this._pending_grid_perf_operation = "sort";
		this._patch_presentation({ schedule_save: true });
		this.refresh_summary();
	}

	begin_grid_perf(operation, meta = {}) {
		this._grid_perf_token = {
			operation,
			meta,
			started_at: performance.now(),
		};
	}

	end_grid_perf(extra = {}) {
		if (!this._grid_perf_token) {
			return null;
		}
		const elapsed_ms = Math.round(performance.now() - this._grid_perf_token.started_at);
		const adapter_stats = this.datatable_adapter?.get_perf_stats?.() || {};
		const entry = {
			elapsed_ms,
			at: new Date().toISOString(),
			row_count: this.rows?.length || 0,
			total_rows: this.pagination?.total_rows || 0,
			adapter: { ...adapter_stats },
			...this._grid_perf_token.meta,
			...extra,
		};
		const operation = this._grid_perf_token.operation;
		this.grid_perf_report[operation] = entry;
		if (["refresh", "first_render", "sort", "axis_switch", "drill_down", "navigate_back"].includes(operation)) {
			if (!Array.isArray(this.grid_perf_report.refresh_history)) {
				this.grid_perf_report.refresh_history = [];
			}
			this.grid_perf_report.refresh_history.push({
				operation,
				elapsed_ms,
				render_elapsed_ms: extra.render_elapsed_ms ?? null,
				row_count: entry.row_count,
				at: entry.at,
			});
		}
		this.events?.emit("grid:perf", entry);
		if (frappe.boot?.developer_mode) {
			console.info(`[Account Explorer perf] ${operation}: ${elapsed_ms}ms`, entry);
		}
		const token = this._grid_perf_token;
		this._grid_perf_token = null;
		return entry;
	}

	get_grid_perf_report() {
		return {
			...this.grid_perf_report,
			refresh_history: [...(this.grid_perf_report.refresh_history || [])],
		};
	}

	get_grid_perf_summary() {
		const history = this.grid_perf_report.refresh_history || [];
		const refresh_only = history.filter((row) => row.operation === "refresh");
		const render_times = history
			.map((row) => row.render_elapsed_ms)
			.filter((value) => typeof value === "number");
		const sum = (values) => (values.length ? values.reduce((total, value) => total + value, 0) : 0);
		const avg = (values) => (values.length ? Math.round(sum(values) / values.length) : null);
		return {
			first_render_ms: this.grid_perf_report.first_render?.elapsed_ms ?? null,
			refresh_ms: this.grid_perf_report.refresh?.elapsed_ms ?? null,
			axis_switch_ms: this.grid_perf_report.axis_switch?.elapsed_ms ?? null,
			sort_ms: this.grid_perf_report.sort?.elapsed_ms ?? null,
			drill_down_ms: this.grid_perf_report.drill_down?.elapsed_ms ?? null,
			navigate_back_ms: this.grid_perf_report.navigate_back?.elapsed_ms ?? null,
			refresh_count: refresh_only.length,
			refresh_avg_ms: avg(refresh_only.map((row) => row.elapsed_ms)),
			render_avg_ms: avg(render_times),
			adapter: this.datatable_adapter?.get_perf_stats?.() || {},
			memory: this.get_grid_memory_diagnostics(),
			lifecycle: this.get_grid_lifecycle_counters(),
		};
	}

	reset_grid_lifecycle_counters() {
		const adapters = erpnext_extensions.account_explorer.adapters;
		adapters.AEDataTableAdapter.reset_lifecycle_counters();
		this._grid_lifecycle_counters = { grid_render_count: 0 };
	}

	get_grid_lifecycle_counters() {
		const adapters = erpnext_extensions.account_explorer.adapters;
		return {
			...adapters.AEDataTableAdapter.get_lifecycle_counters(),
			grid_render_count: this._grid_lifecycle_counters.grid_render_count,
		};
	}

	get_perf_hotspots(operation = null) {
		const entry = operation
			? this.grid_perf_report[operation]
			: this._grid_perf_token
				? null
				: this.grid_perf_report.refresh ||
					this.grid_perf_report.first_render ||
					this.grid_perf_report.axis_switch;
		const target = operation ? this.grid_perf_report[operation] : entry;
		if (!target) {
			return [];
		}
		const phases = target.phases || {};
		const adapter = target.adapter || {};
		const candidates = [
			{ name: "api", ms: target.api_elapsed_ms },
			{ name: "render_grid", ms: target.render_elapsed_ms },
			{ name: "datatable_mount", ms: adapter.mount?.elapsed_ms },
			{ name: "datatable_update", ms: adapter.update?.elapsed_ms },
			{ name: "detail_header", ms: phases.detail_header_ms },
			{ name: "datatable", ms: phases.datatable_ms },
			{ name: "toolbar", ms: phases.toolbar_ms },
			{ name: "breadcrumb", ms: phases.breadcrumb_ms },
			{ name: "totals", ms: phases.totals_ms },
			{ name: "pagination", ms: phases.pagination_ms },
			{ name: "warnings", ms: phases.warnings_ms },
			{ name: "formatting", ms: phases.formatting_ms },
			{ name: "dom_update", ms: phases.dom_update_ms },
			{ name: "layout", ms: phases.layout_ms },
			{ name: "paint", ms: phases.paint_ms },
			{ name: "tooltip", ms: phases.tooltip_ms },
		].filter((row) => typeof row.ms === "number" && row.ms >= 0);
		return candidates.sort((left, right) => right.ms - left.ms);
	}

	get_grid_memory_diagnostics() {
		return {
			datatable_mounted: !!this.datatable_adapter?.is_mounted?.(),
			datatable_hosts: this.$grid?.find(".ae-datatable-host").length || 0,
			grid_containers: this.$grid?.find(".ae-grid-container").length || 0,
			resize_observer_active: !!this.datatable_adapter?._resize_observer,
			source_row_count: this.datatable_adapter?._source_rows?.length || 0,
			grid_render_generation: this.grid_render_generation,
			interaction_bound: !!this._datatable_grid_bound,
		};
	}

	_count_jquery_handlers($target, namespace = null) {
		const element = $target?.[0];
		if (!element || !$.hasData?.(element)) {
			return 0;
		}
		const events = $._data(element, "events") || {};
		let total = 0;
		Object.keys(events).forEach((type) => {
			(events[type] || []).forEach((handler) => {
				if (!namespace) {
					total += 1;
					return;
				}
				const namespaces = (handler.namespace || "").split(".").filter(Boolean);
				if (namespaces.includes(namespace)) {
					total += 1;
				}
			});
		});
		return total;
	}

	get_lifecycle_leak_diagnostics() {
		const adapters = erpnext_extensions.account_explorer.adapters;
		const event_counts = this.events?.get_listener_counts?.() || { total: 0, by_event: {} };
		const jquery_handlers = {
			grid_datatable: this._count_jquery_handlers(this.$grid, "aeDatatableGrid"),
			grid_keyboard: this._count_jquery_handlers(this.$grid, "aeGridKeyboard"),
			document_copy_menu: this._count_jquery_handlers($(document), "aeGridCopyMenu"),
		};
		jquery_handlers.total =
			jquery_handlers.grid_datatable +
			jquery_handlers.grid_keyboard +
			jquery_handlers.document_copy_menu;
		const heap = performance.memory
			? {
					used_js_heap_bytes: performance.memory.usedJSHeapSize,
					total_js_heap_bytes: performance.memory.totalJSHeapSize,
					js_heap_limit_bytes: performance.memory.jsHeapSizeLimit,
				}
			: null;
		return {
			datatable_instances: adapters.AEDataTableAdapter.get_active_mount_count(),
			datatable_hosts_in_document: document.querySelectorAll(".ae-datatable-host").length,
			resize_observers: adapters.AEDataTableAdapter.get_active_resize_observer_count(),
			detached_dom_nodes: adapters.AEDataTableAdapter.get_detached_host_count(),
			explorer_store_subscriptions: this.store?.get_subscriber_count?.() || 0,
			event_listeners: {
				event_bus_total: event_counts.total,
				event_bus_by_event: event_counts.by_event,
				jquery: jquery_handlers,
				total: event_counts.total + jquery_handlers.total,
			},
			browser_heap: heap,
			datatable_mounted: !!this.datatable_adapter?.is_mounted?.(),
			grid_interaction_bound: !!this._datatable_grid_bound,
			grid_keyboard_bound: !!this._grid_keyboard_bound,
		};
	}

	async run_lifecycle_leak_cycle() {
		const wait_refresh = () => this._summary_refresh_tail;
		this.switch_axis("account_level");
		await wait_refresh();
		this.switch_axis("party");
		await wait_refresh();
		this.switch_axis("voucher");
		await wait_refresh();
		let gl_opened = false;
		const voucher_row = (this.rows || []).find((row) => row.voucher_type && row.voucher_no);
		if (voucher_row) {
			this.open_grouped_gl_detail(voucher_row);
			await wait_refresh();
			this.go_back();
			await wait_refresh();
			gl_opened = true;
		}
		this.switch_axis("dimension");
		await wait_refresh();
		this.switch_axis("currency");
		await wait_refresh();
		this.switch_axis("account_level");
		await wait_refresh();
		return { gl_opened };
	}

	should_datatable_incremental_update() {
		const host = this.$grid.find(".ae-datatable-container")[0];
		return (
			!!host &&
			this.datatable_adapter?.is_mounted?.() &&
			this.datatable_adapter?.get_container?.() === host
		);
	}

	update_summary_grid_toolbar_counts() {
		const $toolbar = this.$grid.find(".ae-grid-toolbar");
		if (!$toolbar.length) {
			return;
		}
		$toolbar.find(".ae-grid-meta-item").first().text(__("Rows: {0}", [this.rows.length]));
		this.update_grid_toolbar_state();
	}

	get_scope_status_defaults() {
		const scopeDefaults = (this.metadata?.defaults || {}).document_scope || this.metadata?.defaults || {};
		return scopeDefaults.status || {};
	}

	setup_saved_views_ui($parent) {
		const $group = $('<div class="ae-views-group btn-group"></div>').appendTo($parent);
		$('<button type="button" class="btn btn-default btn-sm dropdown-toggle ae-views-btn">')
			.text(__("Views"))
			.attr("data-toggle", "dropdown")
			.attr("aria-haspopup", "true")
			.attr("aria-expanded", "false")
			.appendTo($group);
		const $menu = $('<ul class="dropdown-menu dropdown-menu-right ae-views-menu"></ul>').appendTo($group);
		$('<li class="dropdown-header">').text(__("Saved Views")).appendTo($menu);
		$("<li>")
			.addClass("ae-views-select-item")
			.append(
				this.$saved_view_select = $('<select class="form-control input-sm ae-saved-view-select">')
					.append($("<option>").val("").text(__("Select view…")))
					.on("change", () => {
						const name = this.$saved_view_select.val();
						if (name) {
							this.load_saved_view(name);
						}
					})
			)
			.appendTo($menu);
		$('<li class="divider">').appendTo($menu);
		$("<li>")
			.append(
				$("<a href='#'>")
					.text(__("Save Current View"))
					.on("click", (event) => {
						event.preventDefault();
						this.prompt_save_view();
					})
			)
			.appendTo($menu);
		$("<li>")
			.append(
				(this.$delete_saved_view_item = $("<a href='#'>")
					.addClass("ae-views-delete")
					.text(__("Delete View"))
					.on("click", (event) => {
						event.preventDefault();
						if (!this.$delete_saved_view_item.hasClass("disabled")) {
							this.delete_active_saved_view();
						}
					}))
			)
			.appendTo($menu);
		this.update_saved_views_menu_state();
	}

	update_saved_views_menu_state() {
		if (this.$delete_saved_view_item) {
			this.$delete_saved_view_item.toggleClass("disabled", !this.active_saved_view?.name);
		}
	}

	refresh_saved_views_list() {
		if (!this.metadata?.saved_views_enabled || !this.$saved_view_select) {
			return;
		}
		const company = this.document_scope.company || this.company_field?.get_value();
		frappe.call({
			method: `${this.api_base}.list_account_explorer_saved_views`,
			args: { company },
			callback: (r) => {
				this.saved_views = r.message || [];
				const current = this.active_saved_view?.name || "";
				this.$saved_view_select.empty().append($("<option>").val("").text(__("Select view…")));
				this.saved_views.forEach((row) => {
					this.$saved_view_select.append(
						$("<option>").val(row.name).text(row.view_name).prop("selected", row.name === current)
					);
				});
			},
		});
	}

	build_presentation_state() {
		return {
			schema_version: 1,
			visible_columns: this.get_effective_visible_column_ids(),
			hidden_columns: [...this.get_summary_hidden_columns()],
			column_order: [...(this.grid_column_order || [])],
			column_widths: { ...(this.grid_column_widths || {}) },
			sticky_column: this.grid_sticky_column || this.get_required_summary_column_id(),
			density: this.grid_density || "comfortable",
			sort_field: this.analysis_context.sort_field,
			sort_order: this.analysis_context.sort_order,
			page_size: this.analysis_context.page_size,
			number_format: this.number_format_mode || "auto",
			show_optional_full_voucher_columns: this.show_optional_full_voucher_columns ? 1 : 0,
			dimension_layout: this.show_full_voucher_dimensions ? "full" : "compact",
			visible_dimension_fields: Object.entries(this.gl_dimension_column_visibility || {})
				.filter(([, visible]) => visible !== false)
				.map(([fieldname]) => fieldname),
		};
	}

	get_summary_hidden_columns() {
		const stored = this.store?.get("presentation")?.hidden_columns;
		if (Array.isArray(this.grid_hidden_columns) && this.grid_hidden_columns.length) {
			return this.grid_hidden_columns;
		}
		return Array.isArray(stored) ? stored : [];
	}

	set_summary_hidden_columns(hidden_ids = []) {
		this.grid_hidden_columns = [...new Set((hidden_ids || []).filter(Boolean))];
		this._patch_presentation({ schedule_save: true });
	}

	get_required_summary_column_id() {
		const defaults = this.get_default_visible_columns();
		return defaults[0] || null;
	}

	get_effective_visible_column_ids(columns = this.last_summary_columns) {
		const hidden = new Set(this.get_summary_hidden_columns());
		const required = this.get_required_summary_column_id();
		const allowed = this.get_default_visible_columns();
		return (columns || [])
			.map((col) => col.id)
			.filter((id) => allowed.includes(id) && (!hidden.has(id) || id === required));
	}

	announce_grid_status(message) {
		if (!this.$grid_status?.length || !message) {
			return;
		}
		this.$grid_status.text(message);
	}

	clear_grid_selection() {
		this.datatable_adapter?.clear_selection?.();
		this.store.patch({
			selection: {
				selected_row_key: null,
				checked_row_keys: [],
			},
		});
		this.update_grid_toolbar_state();
	}

	get_checked_row_count() {
		return (this.store.get("selection")?.checked_row_keys || []).length;
	}

	get_grid_density() {
		return this.grid_density || this.store.get("presentation")?.density || "comfortable";
	}

	set_grid_density(mode) {
		const next = mode === "compact" ? "compact" : "comfortable";
		if (this.grid_density === next) {
			return;
		}
		this.grid_density = next;
		if (this.datatable_adapter?.is_mounted?.()) {
			this.datatable_adapter?.set_density?.(this.grid_density);
		}
		this._patch_presentation({ schedule_save: true });
		this.update_grid_toolbar_state();
		this.announce_grid_status(
			this.grid_density === "compact" ? __("Compact grid density") : __("Comfortable grid density")
		);
	}

	set_page_size(page_size) {
		const normalized = erpnext_extensions.account_explorer.core.AE_GRID_PAGE_SIZE_OPTIONS.includes(
			cint(page_size)
		)
			? cint(page_size)
			: 50;
		if (this.analysis_context.page_size === normalized) {
			return;
		}
		this.analysis_context.page_size = normalized;
		this.analysis_context.page = 1;
		this.clear_grid_selection();
		this._patch_presentation({ schedule_save: true });
		this.update_grid_toolbar_state();
		this.refresh_summary();
	}

	set_number_format_mode(mode) {
		const allowed = erpnext_extensions.account_explorer.core.AE_NUMBER_FORMAT_MODES;
		const next = allowed.includes(mode) ? mode : "auto";
		if (this.number_format_mode === next) {
			return;
		}
		this.number_format_mode = next;
		this._patch_presentation({ schedule_save: true });
		this.update_grid_toolbar_state();
		if (this.is_datatable_summary_enabled() && this.datatable_adapter?.is_mounted?.()) {
			void this.render_grid(this.last_summary_columns || []);
		}
	}

	prompt_reset_grid_preferences(reset_all = false) {
		const confirm_message = reset_all
			? __("Reset grid preferences for all axes?")
			: __("Reset grid preferences for the current axis?");
		frappe.confirm(confirm_message, () => {
			if (reset_all) {
				this.user_preferences.reset_all_axes();
			} else {
				this.user_preferences.reset_current_axis();
			}
			this.clear_grid_selection();
			this.refresh_summary();
			frappe.show_alert({ message: __("Grid preferences reset."), indicator: "green" });
		});
	}

	build_saved_view_payload(view_name) {
		this.sync_document_scope_from_controls();
		return {
			view_name,
			company: this.document_scope.company,
			document_scope: ae_clone_document_scope(this.document_scope),
			analysis_context: ae_clone_analysis_context(this.analysis_context),
			presentation: this.build_presentation_state(),
		};
	}

	prompt_save_view() {
		if (!this.metadata?.saved_views_enabled) {
			return;
		}
		if (!this.document_scope.company) {
			frappe.msgprint(__("Company is required before saving a view."));
			return;
		}
		const default_name = this.active_saved_view?.view_name || "";
		frappe.prompt(
			[
				{
					fieldname: "view_name",
					fieldtype: "Data",
					label: __("View Name"),
					reqd: 1,
					default: default_name,
				},
			],
			(values) => {
				frappe.call({
					method: `${this.api_base}.save_account_explorer_saved_view`,
					args: { payload: this.build_saved_view_payload(values.view_name) },
					freeze: true,
					callback: (r) => {
						this.active_saved_view = r.message || null;
						this.update_saved_views_menu_state();
						this.refresh_saved_views_list();
						frappe.show_alert(__("View saved."));
					},
				});
			},
			__("Save Current View"),
			__("Save")
		);
	}

	load_saved_view(name) {
		frappe.call({
			method: `${this.api_base}.get_account_explorer_saved_view`,
			args: { name },
			freeze: true,
			callback: (r) => {
				const view = r.message;
				if (!view) {
					return;
				}
				this.apply_saved_view_configuration(view);
				this.active_saved_view = view;
				this.update_saved_views_menu_state();
				if (this.$saved_view_select) {
					this.$saved_view_select.val(view.name);
				}
			},
		});
	}

	apply_saved_view_configuration(view) {
		const scope = ae_default_document_scope(view.document_scope || {});
		this.document_scope = scope;
		if (this.company_field) {
			this.company_field.set_value(scope.company || "");
		}
		if (this.fy_field) {
			this.fy_field.set_value(scope.fiscal_year || "");
		}
		if (this.from_date_field) {
			this.from_date_field.set_value(scope.from_date || "");
		}
		if (this.to_date_field) {
			this.to_date_field.set_value(scope.to_date || "");
		}
		this.sync_filter_controls_from_document_scope(scope);

		const analysis = view.analysis_context || {};
		this.analysis_context = {
			...this.analysis_context,
			...analysis,
			account_scope: { ...this.analysis_context.account_scope, ...(analysis.account_scope || {}) },
			party_scope: { ...this.analysis_context.party_scope, ...(analysis.party_scope || {}) },
			unified_party_scope: {
				...this.analysis_context.unified_party_scope,
				...(analysis.unified_party_scope || {}),
			},
			dimension_scope: {
				...this.analysis_context.dimension_scope,
				...(analysis.dimension_scope || {}),
			},
			voucher_scope: { ...this.analysis_context.voucher_scope, ...(analysis.voucher_scope || {}) },
		};

		const presentation = view.presentation || {};
		if (presentation.sort_field) {
			this.analysis_context.sort_field = presentation.sort_field;
		}
		if (presentation.sort_order) {
			this.analysis_context.sort_order = presentation.sort_order;
		}
		if (presentation.page_size) {
			this.analysis_context.page_size = presentation.page_size;
		}
		this.show_optional_full_voucher_columns = !!presentation.show_optional_full_voucher_columns;

		this._reset_breadcrumbs();
		this.render_navigator();
		this.render_breadcrumbs();
		this.render_detail_header();
		this.update_advanced_filters_button();
		this.render_filter_summary();
		this.apply_scope();
	}

	delete_active_saved_view() {
		if (!this.active_saved_view?.name) {
			return;
		}
		frappe.confirm(__("Delete saved view {0}?", [this.active_saved_view.view_name]), () => {
			frappe.call({
				method: `${this.api_base}.delete_account_explorer_saved_view`,
				args: { name: this.active_saved_view.name },
				callback: () => {
					this.active_saved_view = null;
					this.update_saved_views_menu_state();
					if (this.$saved_view_select) {
						this.$saved_view_select.val("");
					}
					this.refresh_saved_views_list();
					frappe.show_alert(__("View deleted."));
				},
			});
		});
	}

	setup_export_ui($parent) {
		const export_enabled = cint(this.metadata?.export_enabled);
		const $group = $('<div class="ae-export-group btn-group"></div>').appendTo($parent);
		this.$export_btn = $('<button type="button" class="btn btn-default btn-sm dropdown-toggle ae-export-btn">')
			.text(__("Export"))
			.prop("disabled", !export_enabled)
			.attr("data-toggle", "dropdown")
			.attr("aria-haspopup", "true")
			.attr("aria-expanded", "false")
			.appendTo($group);

		if (!export_enabled) {
			this.$export_btn.attr("title", __("Export is disabled in Iran Accounting Settings."));
		}

		const $menu = $('<ul class="dropdown-menu dropdown-menu-right ae-export-menu"></ul>').appendTo($group);
		["csv", "xlsx"].forEach((format) => {
			$("<li>")
				.append(
					$("<a>")
						.attr("href", "#")
						.text(format.toUpperCase())
						.on("click", (event) => {
							event.preventDefault();
							if (export_enabled) {
								this.run_export(format);
							}
						})
				)
				.appendTo($menu);
		});
	}

	run_export(file_format) {
		if (!this.metadata?.export_enabled) {
			frappe.msgprint(__("Export is disabled in Iran Accounting Settings."));
			return;
		}
		if (this.analysis_context.detail_mode !== "summary") {
			frappe.msgprint(__("Export is only supported for summary view."));
			return;
		}
		this.sync_document_scope_from_controls();
		if (!this.document_scope.company) {
			frappe.msgprint(__("Company is required."));
			return;
		}
		if (!this.document_scope.from_date || !this.document_scope.to_date) {
			frappe.msgprint(__("From Date and To Date are required before exporting."));
			return;
		}

		const payload = JSON.stringify(this.build_payload());
		const args = {
			payload,
			file_format,
		};
		const threshold = cint(this.metadata.export_background_threshold || 5000);
		const total_rows = cint(this.pagination?.total_rows || 0);

		if (total_rows > threshold) {
			frappe.call({
				method: `${this.api_base}.export_account_explorer`,
				args,
				freeze: true,
				freeze_message: __("Queuing export..."),
				callback: (r) => {
					const message = r.message?.message || __("Export queued in background.");
					frappe.msgprint(message);
				},
			});
			return;
		}

		open_url_post(`/api/method/${this.api_base}.export_account_explorer`, args);
	}

	toggle_filter_panel(force_open = null) {
		this.filter_panel_open = force_open === null ? !this.filter_panel_open : !!force_open;
		this.update_filter_panel_ui();
		if (this.filter_panel_open) {
			this.sync_filter_controls_from_document_scope();
		}
	}

	update_filter_panel_ui() {
		if (this.$filter_panel) {
			this.$filter_panel
				.toggleClass("ae-filter-panel--collapsed", !this.filter_panel_open)
				.toggleClass("ae-filter-panel--expanded", this.filter_panel_open)
				.attr("aria-hidden", this.filter_panel_open ? "false" : "true");
		}
		if (!this.$advanced_filters_btn) {
			return;
		}
		const count = ae_count_active_document_scope_filters(this.document_scope);
		const label = count ? `${__("Filters")} (${count})` : __("Filters");
		this.$advanced_filters_btn
			.text(label)
			.attr("aria-expanded", this.filter_panel_open ? "true" : "false")
			.toggleClass("active", this.filter_panel_open);
	}

	format_display_amount(value) {
		return ae_format_amount_with_mode(
			value ?? 0,
			this.currency_code || frappe.defaults.get_default("currency"),
			this.number_format_mode || "auto"
		);
	}

	render_amount_cell($cell, value) {
		const { compact, full } = this.format_display_amount(value);
		$cell.addClass("ae-amount-compact").attr("title", full).attr("aria-label", full);
		if (compact !== full) {
			$cell.addClass("ae-amount-compact--abbreviated");
		}
		$cell.text(compact);
	}

	make_filter_section(title, $parent, section_key) {
		const $section = $('<div class="ae-filter-card"></div>').appendTo($parent || this.$filter_panel);
		if (section_key) {
			$section.addClass(`ae-filter-card--${section_key}`);
		}
		$('<div class="ae-filter-section-title ae-filter-card-title">').text(title).appendTo($section);
		const $body = $('<div class="ae-filter-section-body ae-filter-card-body"></div>').appendTo($section);
		return $body;
	}

	make_filter_control(parent, df, on_change) {
		const control = frappe.ui.form.make_control({
			parent,
			df: {
				...df,
				change: () => {
					if (on_change) {
						on_change(control);
					}
				},
			},
			render_input: true,
		});
		return control;
	}

	setup_filter_panel(scopeDefaults = {}) {
		this.$filter_panel.empty();
		this.filter_controls = {};
		const $inner = $('<div class="ae-filter-panel-inner"></div>').appendTo(this.$filter_panel);
		const $heading = $('<div class="ae-filter-panel-heading"></div>').appendTo($inner);
		$heading.append($('<span class="ae-filter-panel-title">').text(__("Document Scope Filters")));
		$heading.append(
			$('<button type="button" class="btn btn-xs btn-default ae-filter-panel-collapse">')
				.text(__("Collapse"))
				.attr("aria-label", __("Collapse filters"))
				.on("click", () => this.toggle_filter_panel(false))
		);
		const $grid = $('<div class="ae-filter-grid"></div>').appendTo($inner);

		const general_body = this.make_filter_section(__("General"), $grid, "general");
		this.filter_controls.finance_book = this.make_filter_control(
			general_body,
			{
				fieldtype: "Link",
				label: __("Finance Book"),
				fieldname: "finance_book",
				options: "Finance Book",
			},
			() => {}
		);

		const voucher_body = this.make_filter_section(__("Voucher"), $grid, "voucher");
		this.filter_controls.voucher_type = this.make_filter_control(voucher_body, {
			fieldtype: "Data",
			label: __("Voucher Type"),
			fieldname: "voucher_type",
		});
		this.filter_controls.voucher_no = this.make_filter_control(voucher_body, {
			fieldtype: "Data",
			label: __("Voucher No"),
			fieldname: "voucher_no",
		});
		this.filter_controls.against_voucher_type = this.make_filter_control(voucher_body, {
			fieldtype: "Data",
			label: __("Against Voucher Type"),
			fieldname: "against_voucher_type",
		});
		this.filter_controls.against_voucher_no = this.make_filter_control(voucher_body, {
			fieldtype: "Data",
			label: __("Against Voucher No"),
			fieldname: "against_voucher_no",
		});
		this.filter_controls.reference_no = this.make_filter_control(voucher_body, {
			fieldtype: "Data",
			label: __("Reference No / Bill No"),
			fieldname: "reference_no",
		});

		const accounting_body = this.make_filter_section(__("Accounting"), $grid, "accounting");
		this.filter_controls.account = this.make_filter_control(accounting_body, {
			fieldtype: "MultiSelectList",
			label: __("Account"),
			fieldname: "account",
			options: "Account",
			get_data: (txt) =>
				frappe.db.get_link_options("Account", txt, {
					company: this.document_scope.company || this.company_field?.get_value(),
					is_group: 0,
				}),
		});
		const party_types = (this.metadata?.party_sources || [])
			.filter((row) => row.enabled)
			.map((row) => row.party_type);
		this.filter_controls.party_type = this.make_filter_control(
			accounting_body,
			{
				fieldtype: "Select",
				label: __("Party Type"),
				fieldname: "party_type",
				options: ["", ...party_types],
			},
			() => {
				this.filter_controls.party?.set_value(null);
			}
		);
		this.filter_controls.party = this.make_filter_control(accounting_body, {
			fieldtype: "MultiSelectList",
			label: __("Party"),
			fieldname: "party",
			options: "party_type",
			get_data: (txt) => {
				const party_type = this.filter_controls.party_type?.get_value();
				if (!party_type) {
					return Promise.resolve([]);
				}
				return frappe.db.get_link_options(party_type, txt);
			},
		});

		const dimensions_body = this.make_filter_section(__("Dimensions"), $grid, "dimensions");
		this.filter_controls.dimensions = {};
		(this.metadata?.dimensions || []).forEach((dimension) => {
			this.filter_controls.dimensions[dimension.fieldname] = this.make_filter_control(
				dimensions_body,
				{
					fieldtype: "MultiSelectList",
					label: dimension.label || dimension.fieldname,
					fieldname: dimension.fieldname,
					options: dimension.document_type || dimension.fieldname,
					get_data: (txt) => {
						const filters = {};
						const company = this.document_scope.company || this.company_field?.get_value();
						if (company && frappe.meta.has_field(dimension.document_type, "company")) {
							filters.company = company;
						}
						return frappe.db.get_link_options(dimension.document_type, txt, filters);
					},
				},
				() => {}
			);
		});

		const currency_body = this.make_filter_section(__("Currency"), $grid, "currency");
		const currency_type_values = (this.metadata?.currency_types || [
			{ value: "account_currency", label: __("Account Currency") },
			{ value: "transaction_currency", label: __("Transaction Currency") },
		]).map((row) => row.value);
		this.filter_controls.currency_type = this.make_filter_control(currency_body, {
			fieldtype: "Select",
			label: __("Currency Type"),
			fieldname: "currency_type",
			options: currency_type_values,
			default: "account_currency",
		});
		const currency_options = ["", ...(this.metadata?.currencies || [])].join("\n");
		this.filter_controls.currency = this.make_filter_control(currency_body, {
			fieldtype: "Select",
			label: __("Currency"),
			fieldname: "currency",
			options: currency_options,
		});

		const status_body = this.make_filter_section(__("Status"), $grid, "status");
		this.filter_controls.include_opening_entries = this.make_filter_control(status_body, {
			fieldtype: "Check",
			label: __("Include Opening Entries"),
			fieldname: "include_opening_entries",
			default: 1,
		});
		this.filter_controls.include_cancelled_entries = this.make_filter_control(status_body, {
			fieldtype: "Check",
			label: __("Include Cancelled Entries"),
			fieldname: "include_cancelled_entries",
			default: 0,
		});
		this.filter_controls.include_default_finance_book_entries = this.make_filter_control(status_body, {
			fieldtype: "Check",
			label: __("Include Default Finance Book Entries"),
			fieldname: "include_default_finance_book_entries",
			default: 1,
		});
		this.filter_controls.include_period_closing_vouchers = this.make_filter_control(status_body, {
			fieldtype: "Check",
			label: __("Include Period Closing Vouchers"),
			fieldname: "include_period_closing_vouchers",
			default: 0,
		});

		const $actions = $('<div class="ae-filter-panel-actions"></div>').appendTo($inner);
		$('<button type="button" class="btn btn-primary btn-sm">')
			.text(__("Apply"))
			.on("click", () => this.apply_scope())
			.appendTo($actions);
		$('<button type="button" class="btn btn-default btn-sm">')
			.text(__("Clear"))
			.on("click", () => this.clear_filter_panel())
			.appendTo($actions);

		this.sync_filter_controls_from_document_scope(scopeDefaults);
		this.update_filter_panel_ui();
	}

	sync_filter_controls_from_document_scope(scopeOverride = null) {
		const scope = scopeOverride || this.document_scope;
		this.filter_controls.finance_book?.set_value(scope.finance_book || "");
		this.filter_controls.voucher_type?.set_value(scope.voucher?.voucher_type || "");
		this.filter_controls.voucher_no?.set_value(scope.voucher?.voucher_no || "");
		this.filter_controls.against_voucher_type?.set_value(scope.voucher?.against_voucher_type || "");
		this.filter_controls.against_voucher_no?.set_value(scope.voucher?.against_voucher_no || "");
		this.filter_controls.reference_no?.set_value(scope.voucher?.reference_no || "");
		this.filter_controls.account?.set_value(ae_scope_value_to_control(scope.accounting?.account));
		this.filter_controls.party_type?.set_value(scope.accounting?.party_type || "");
		this.filter_controls.party?.set_value(ae_scope_value_to_control(scope.accounting?.party));
		Object.entries(this.filter_controls.dimensions || {}).forEach(([fieldname, control]) => {
			control.set_value(ae_scope_value_to_control(scope.accounting_dimensions?.[fieldname]));
		});
		this.filter_controls.currency_type?.set_value(scope.currency?.currency_type || "account_currency");
		this.filter_controls.currency?.set_value(scope.currency?.currency || "");
		this.filter_controls.include_opening_entries?.set_value(scope.status?.include_opening_entries ? 1 : 0);
		this.filter_controls.include_cancelled_entries?.set_value(scope.status?.include_cancelled_entries ? 1 : 0);
		this.filter_controls.include_default_finance_book_entries?.set_value(
			scope.status?.include_default_finance_book_entries ? 1 : 0
		);
		this.filter_controls.include_period_closing_vouchers?.set_value(
			scope.status?.include_period_closing_vouchers ? 1 : 0
		);
	}

	sync_document_scope_from_controls() {
		this.document_scope.company = this.company_field.get_value();
		this.document_scope.fiscal_year = this.fy_field.get_value();
		this.document_scope.from_date = this.from_date_field.get_value();
		this.document_scope.to_date = this.to_date_field.get_value();
		this.document_scope.finance_book = this.filter_controls.finance_book?.get_value() || null;
		this.document_scope.voucher = {
			voucher_type: this.filter_controls.voucher_type?.get_value() || null,
			voucher_no: this.filter_controls.voucher_no?.get_value() || null,
			against_voucher_type: this.filter_controls.against_voucher_type?.get_value() || null,
			against_voucher_no: this.filter_controls.against_voucher_no?.get_value() || null,
			reference_no: this.filter_controls.reference_no?.get_value() || null,
		};
		this.document_scope.accounting = {
			account: ae_normalize_multi_value(this.filter_controls.account?.get_value()),
			party_type: this.filter_controls.party_type?.get_value() || null,
			party: ae_normalize_multi_value(this.filter_controls.party?.get_value()),
		};
		const accounting_dimensions = {};
		Object.entries(this.filter_controls.dimensions || {}).forEach(([fieldname, control]) => {
			const value = ae_normalize_multi_value(control.get_value());
			if (value) {
				accounting_dimensions[fieldname] = value;
			}
		});
		this.document_scope.accounting_dimensions = accounting_dimensions;
		this.document_scope.currency = {
			currency_type: this.filter_controls.currency_type?.get_value() || "account_currency",
			currency: this.filter_controls.currency?.get_value() || null,
		};
		this.document_scope.status = {
			include_opening_entries: this.filter_controls.include_opening_entries?.get_value() ? 1 : 0,
			include_cancelled_entries: this.filter_controls.include_cancelled_entries?.get_value() ? 1 : 0,
			include_default_finance_book_entries: this.filter_controls.include_default_finance_book_entries?.get_value()
				? 1
				: 0,
			include_period_closing_vouchers: this.filter_controls.include_period_closing_vouchers?.get_value() ? 1 : 0,
		};
	}

	clear_filter_panel() {
		this.document_scope = ae_clear_advanced_document_scope(
			ae_clone_document_scope(this.document_scope),
			this.get_scope_status_defaults()
		);
		this.sync_filter_controls_from_document_scope();
		this.update_advanced_filters_button();
		this.render_filter_summary();
	}

	update_advanced_filters_button() {
		this.update_filter_panel_ui();
	}

	render_filter_summary() {
		if (!this.$filter_summary) {
			this.$filter_summary = $('<div class="ae-filter-summary"></div>').insertAfter(this.$filter_panel);
		}
		this.$filter_summary.hide().empty();
	}

	get_account_level_nav_items() {
		return (this.metadata.levels || []).filter(
			(level) => level.enabled && level.sequence != null && level.code_length != null && !level.fieldname
		);
	}

	get_dimension_nav_items() {
		return (this.metadata.dimensions || []).filter((dimension) => dimension.fieldname);
	}

	is_page_rtl() {
		return (document.documentElement.getAttribute("dir") || "").toLowerCase() === "rtl";
	}

	get_bilingual_label(primary, alternate) {
		const main = (primary || "").trim();
		const alt = (alternate || "").trim();
		if (!main && !alt) {
			return "";
		}
		if (!alt || main === alt) {
			return main || alt;
		}
		return this.is_page_rtl() ? main : alt || main;
	}

	get_level_nav_label(level) {
		return this.get_bilingual_label(level.title_fa, level.title);
	}

	get_level_nav_sublabel(level) {
		const fa = (level.title_fa || "").trim();
		const en = (level.title || "").trim();
		if (!fa || !en || fa === en) {
			return "";
		}
		return this.is_page_rtl() ? en : fa;
	}

	get_axis_path_label(axis) {
		const map = {
			account_level: __("Account Levels"),
			party: __("Parties"),
			unified_party: __("Unified Parties"),
			dimension: __("Dimensions"),
			currency: __("Currencies"),
			voucher: __("Vouchers"),
		};
		return map[axis] || axis || __("Analysis");
	}

	get_breadcrumb_axis_label(axis) {
		const map = {
			account_level: __("Account Level"),
			party: __("Party"),
			unified_party: __("Unified Party"),
			dimension: __("Dimension"),
			currency: __("Currency"),
			voucher: __("Voucher"),
		};
		return map[axis] || axis || __("Step");
	}

	get_company_path_label() {
		const company = this.document_scope.company || this.company_field?.get_value();
		return company || __("Company");
	}

	get_current_view_path_label() {
		if (this.analysis_context.detail_mode === "grouped_gl") {
			return __("Voucher");
		}
		return this.get_axis_path_label(this.analysis_context.view_axis);
	}

	build_analysis_path_segments() {
		const segments = [
			{
				step: "company",
				label: this.get_company_path_label(),
				kind: "company",
				clickable: this.has_removable_analysis_state(),
				removable: false,
			},
		];
		const scope_trail = this.get_scope_trail();
		const path_source_axis = this.get_path_source_axis();
		const view_axis = this.analysis_context.view_axis;
		const voucher_scope = this.analysis_context.voucher_scope || {};
		const has_type = !!voucher_scope.voucher_type;
		const has_no = !!voucher_scope.voucher_no;
		const is_gl = this.analysis_context.detail_mode === "grouped_gl";
		const on_voucher_path = view_axis === "voucher" || is_gl;

		segments.push({
			step: "axis",
			view_axis: path_source_axis,
			label: this.get_axis_path_label(path_source_axis),
			kind: "axis",
			clickable: scope_trail.length > 0 || on_voucher_path,
			removable: false,
		});

		scope_trail.forEach((chip, index) => {
			segments.push({
				step: `scope:${index}`,
				label: chip.label,
				kind: "scope",
				scope_index: index,
				is_virtual: !!chip.is_virtual_group,
				clickable: index < scope_trail.length - 1 || on_voucher_path,
				removable: true,
			});
		});

		if (on_voucher_path) {
			segments.push({
				step: "voucher_axis",
				label: __("Vouchers"),
				kind: "voucher_axis",
				clickable: has_type || has_no || is_gl,
				removable: false,
			});
			if (has_type) {
				segments.push({
					step: "voucher_type",
					label: voucher_scope.voucher_type,
					kind: "voucher_meta",
					clickable: has_no || is_gl,
					removable: false,
				});
			}
			if (has_no) {
				segments.push({
					step: "voucher_no",
					label: voucher_scope.voucher_no,
					kind: "voucher_meta",
					clickable: is_gl,
					removable: false,
				});
			}
			if (is_gl) {
				segments.push({
					step: "gl_detail",
					label: __("GL Detail"),
					kind: "detail",
					clickable: false,
					removable: false,
				});
			}
		}

		if (segments.length) {
			segments.forEach((segment) => {
				segment.active = false;
			});
			segments[segments.length - 1].active = true;
		}
		return segments;
	}

	has_removable_analysis_state() {
		return (
			this.get_scope_trail().length > 0 ||
			this.analysis_context.view_axis === "voucher" ||
			this.analysis_context.detail_mode === "grouped_gl" ||
			this.has_active_non_default_scope()
		);
	}

	has_active_non_default_scope() {
		const account = this.analysis_context.account_scope || {};
		if (account.selected_account || account.virtual_row_key) {
			return true;
		}
		if (this.analysis_context.party_scope?.selected_party) {
			return true;
		}
		if (this.analysis_context.unified_party_scope?.selected_unified_party) {
			return true;
		}
		if (this.analysis_context.dimension_scope?.selected_dimension_value !== null &&
			this.analysis_context.dimension_scope?.selected_dimension_value !== undefined) {
			return true;
		}
		return false;
	}

	get_path_source_axis() {
		const trail = this.get_normalized_breadcrumb_trail();
		if (trail.length) {
			return trail[0].axis || "account_level";
		}
		if (this.analysis_context.view_axis === "voucher" || this.analysis_context.detail_mode === "grouped_gl") {
			if (this.analysis_context.account_scope?.selected_account || this.analysis_context.account_scope?.virtual_row_key) {
				return "account_level";
			}
			if (this.analysis_context.party_scope?.selected_party) {
				return "party";
			}
			if (this.analysis_context.unified_party_scope?.selected_unified_party) {
				return "unified_party";
			}
			if (this.analysis_context.dimension_scope?.selected_dimension_value) {
				return "dimension";
			}
			return "account_level";
		}
		return this.analysis_context.view_axis || "account_level";
	}

	get_scope_trail() {
		const source_axis = this.get_path_source_axis();
		return this.get_normalized_breadcrumb_trail().filter((chip) => (chip.axis || source_axis) === source_axis);
	}

	get_breadcrumb_chip_key(chip) {
		return [
			chip.axis,
			chip.label,
			chip.selected_account,
			chip.virtual_row_key,
			chip.selected_party,
			chip.party_type,
			chip.dimension_type,
			chip.selected_dimension_value,
			chip.selected_unified_party,
			chip.currency,
		].join("|");
	}

	get_normalized_breadcrumb_trail() {
		const trail = [];
		let previous_key = null;
		(this.breadcrumbs || []).forEach((chip) => {
			if (chip.axis === "voucher" || chip.detail_mode === "grouped_gl") {
				return;
			}
			const key = this.get_breadcrumb_chip_key(chip);
			if (key === previous_key) {
				return;
			}
			trail.push(chip);
			previous_key = key;
		});
		return trail;
	}

	navigate_to_path_step(segment) {
		if (!segment || segment.active) {
			return;
		}
		if (segment.step === "company") {
			this.reset_analysis();
			this.analysis_context.view_axis = "account_level";
			this.render_navigator();
			return;
		}
		if (segment.step === "axis") {
			this.navigate_to_axis_root(segment.view_axis || this.get_path_source_axis());
			return;
		}
		if (segment.step && segment.step.startsWith("scope:")) {
			const scope_trail = this.get_scope_trail();
			this._reset_breadcrumbs(scope_trail.slice(0, segment.scope_index + 1));
			this.restore_context_from_breadcrumbs();
			return;
		}
		if (segment.step === "voucher_axis") {
			this.analysis_context.view_axis = "voucher";
			this.analysis_context.detail_mode = "summary";
			this.analysis_context.voucher_scope = { voucher_type: null, voucher_no: null };
			this.render_navigator();
			this.render_breadcrumbs();
			this.render_detail_header();
			this.refresh_summary();
			return;
		}
		if (segment.step === "voucher_type") {
			const voucher_type = this.analysis_context.voucher_scope?.voucher_type;
			this.analysis_context.view_axis = "voucher";
			this.analysis_context.detail_mode = "summary";
			this.analysis_context.voucher_scope = { voucher_type, voucher_no: null };
			this.render_navigator();
			this.render_breadcrumbs();
			this.render_detail_header();
			this.refresh_summary();
			return;
		}
		if (segment.step === "voucher_no") {
			this.analysis_context.view_axis = "voucher";
			this.analysis_context.detail_mode = "summary";
			this.render_navigator();
			this.render_breadcrumbs();
			this.render_detail_header();
			this.refresh_summary();
		}
	}

	navigate_to_axis_root(view_axis) {
		this._reset_breadcrumbs([]);
		this.clear_axis_scopes(view_axis);
		this.analysis_context.view_axis = view_axis;
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.voucher_scope = { voucher_type: null, voucher_no: null };
		this.analysis_context.page = 1;
		this.voucher_header = null;
		this.render_navigator();
		this.render_breadcrumbs();
		this.render_detail_header();
		this._sync_store_context({ emit: true });
		this.refresh_summary();
	}

	clear_axis_scopes(view_axis) {
		if (view_axis === "account_level") {
			this.analysis_context.account_scope = {
				mode: "tree",
				selected_account: null,
				virtual_row_key: null,
				is_virtual_group: 0,
				level_sequence: this.metadata?.default_level_sequence ?? null,
				tree_root_account: null,
			};
			this.analysis_context.level_sequence = this.metadata?.default_level_sequence ?? null;
			return;
		}
		if (view_axis === "party") {
			this.analysis_context.party_scope = { party_type: null, selected_party: null };
			return;
		}
		if (view_axis === "unified_party") {
			this.analysis_context.unified_party_scope = {
				selected_unified_party: null,
				include_unmapped: 0,
			};
			return;
		}
		if (view_axis === "dimension") {
			this.analysis_context.dimension_scope.selected_dimension_value = null;
			return;
		}
		if (view_axis === "currency") {
			this.document_scope.currency = {
				...this.document_scope.currency,
				currency: null,
			};
		}
	}

	remove_scope_at(scope_index) {
		const scope_trail = this.get_scope_trail();
		if (scope_index < 0 || scope_index >= scope_trail.length) {
			return;
		}
		this._reset_breadcrumbs(scope_trail.slice(0, scope_index));
		if (!this.breadcrumbs.length) {
			this.navigate_to_axis_root(this.get_path_source_axis());
			return;
		}
		this.restore_context_from_breadcrumbs();
	}

	get_scope_remove_label(segment) {
		const axis = this.get_path_source_axis();
		if (axis === "account_level") {
			return __("Remove account scope {0}", [segment.label]);
		}
		if (axis === "party") {
			return __("Remove party scope {0}", [segment.label]);
		}
		if (axis === "dimension") {
			return __("Remove dimension scope {0}", [segment.label]);
		}
		return __("Remove scope {0}", [segment.label]);
	}

	render_level_nav_pill($menu, level) {
		const is_level_active =
			this.analysis_context.view_axis === "account_level" &&
			this.analysis_context.level_sequence === level.sequence;
		const label = this.get_level_nav_label(level);
		const sublabel = this.get_level_nav_sublabel(level);
		const $pill = $('<button type="button" class="ae-nav-pill ae-nav-pill--level">')
			.toggleClass("active", is_level_active)
			.attr("aria-current", is_level_active ? "true" : "false")
			.on("click", (e) => {
				e.stopPropagation();
				this.switch_axis("account_level", level.sequence);
			});
		$pill.append($('<span class="ae-nav-pill-label">').text(label));
		if (sublabel) {
			$pill.append($('<span class="ae-nav-pill-sublabel">').text(sublabel));
		}
		$menu.append($pill);
	}

	render_navigator() {
		this.$nav.empty().show();
		const $shell = $('<div class="ae-nav-shell"></div>').appendTo(this.$nav);
		const $tabs = $('<div class="ae-nav-tabs" role="tablist"></div>').appendTo($shell);
		const $sub = $('<div class="ae-nav-sub"></div>').appendTo($shell);

		const label_map = {
			account_level: __("Account Levels"),
			party: __("Parties"),
			unified_party: __("Unified Parties"),
			dimension: __("Dimensions"),
			currency: __("Currencies"),
			voucher: __("Vouchers"),
		};

		(this.metadata.axes || []).forEach((axis) => {
			if (!axis.enabled) {
				return;
			}
			const is_active =
				this.analysis_context.view_axis === axis.id && this.analysis_context.detail_mode === "summary";
			$('<button type="button" class="ae-nav-tab" role="tab">')
				.text(label_map[axis.id] || axis.label)
				.toggleClass("active", is_active)
				.attr("aria-selected", is_active ? "true" : "false")
				.on("click", () => {
					if (axis.id === "account_level") {
						this.switch_axis("account_level");
						return;
					}
					if (axis.id === "dimension") {
						this.switch_axis("dimension");
						return;
					}
					this.switch_axis(axis.id);
				})
				.appendTo($tabs);
		});

		$sub.empty();
		let has_sub = false;
		if (this.analysis_context.view_axis === "account_level") {
			has_sub = true;
			const $row = $('<div class="ae-nav-sub-row ae-nav-sub-row--levels"></div>').appendTo($sub);
			$row.append($('<div class="ae-nav-sub-label">').text(__("Account Hierarchy")));
			const $menu = $('<div class="ae-nav-sub-items ae-nav-sub-items--levels"></div>').appendTo($row);
			this.get_account_level_nav_items().forEach((level) => {
				this.render_level_nav_pill($menu, level);
			});
		} else if (this.analysis_context.view_axis === "dimension") {
			has_sub = true;
			const $row = $('<div class="ae-nav-sub-row ae-nav-sub-row--dimensions"></div>').appendTo($sub);
			$row.append($('<div class="ae-nav-sub-label">').text(__("Dimension Types")));
			const $menu = $('<div class="ae-nav-sub-items ae-nav-sub-items--dimensions"></div>').appendTo($row);
			this.get_dimension_nav_items().forEach((dimension) => {
				const is_dimension_active =
					this.analysis_context.view_axis === "dimension" &&
					this.analysis_context.dimension_scope.dimension_type === dimension.fieldname;
				$('<button type="button" class="ae-nav-pill">')
					.text(dimension.label || dimension.fieldname)
					.toggleClass("active", is_dimension_active)
					.attr("aria-current", is_dimension_active ? "true" : "false")
					.on("click", (e) => {
						e.stopPropagation();
						this.switch_axis("dimension", dimension.fieldname);
					})
					.appendTo($menu);
			});
		} else if (this.analysis_context.view_axis === "currency") {
			has_sub = true;
			const $row = $('<div class="ae-nav-sub-row ae-nav-sub-row--currency"></div>').appendTo($sub);
			$row.append($('<div class="ae-nav-sub-label">').text(__("Currency Mode")));
			const $menu = $('<div class="ae-nav-sub-items ae-nav-sub-items--currency"></div>').appendTo($row);
			(this.metadata.currency_types || [
				{ value: "account_currency", label: __("Account Currency") },
				{ value: "transaction_currency", label: __("Transaction Currency") },
			]).forEach((type) => {
				const is_currency_active = (this.document_scope.currency?.currency_type || "account_currency") === type.value;
				$('<button type="button" class="ae-nav-pill ae-nav-pill--currency">')
					.text(type.label)
					.toggleClass("active", is_currency_active)
					.attr("aria-current", is_currency_active ? "true" : "false")
					.on("click", (e) => {
						e.stopPropagation();
						this.set_currency_mode(type.value);
					})
					.appendTo($menu);
			});
		}
		$sub.toggle(has_sub);
	}

	switch_axis(view_axis, level_or_dimension = null) {
		this.analysis_context.view_axis = view_axis;
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.page = 1;
		this.clear_grid_selection();
		this._reset_breadcrumbs([]);
		this._pending_grid_perf_operation = "axis_switch";
		if (view_axis !== "voucher") {
			this.analysis_context.voucher_scope = { voucher_type: null, voucher_no: null };
		}
		if (view_axis !== "voucher" && view_axis !== "unified_party") {
			this.analysis_context.unified_party_scope = {
				selected_unified_party: null,
				include_unmapped: 0,
			};
		}
		if (view_axis === "account_level") {
			if (level_or_dimension) {
				this.analysis_context.level_sequence = level_or_dimension;
			}
		}
		if (view_axis === "party") {
			this.analysis_context.sort_field = "party_type";
		} else if (view_axis === "unified_party") {
			this.analysis_context.sort_field = "display_title";
			this.analysis_context.party_scope = { party_type: null, selected_party: null };
			this.analysis_context.unified_party_scope.selected_unified_party = null;
		} else if (view_axis === "dimension") {
			this.analysis_context.sort_field = "display_code";
			this.analysis_context.dimension_scope.selected_dimension_value = null;
			if (level_or_dimension) {
				this.analysis_context.dimension_scope.dimension_type = level_or_dimension;
			} else if (!this.analysis_context.dimension_scope.dimension_type) {
				this.analysis_context.dimension_scope.dimension_type =
					this.metadata.default_dimension_type || this.metadata.default_dimension_field;
			}
		} else if (view_axis === "currency") {
			this.analysis_context.sort_field = "currency";
		} else if (view_axis === "voucher") {
			this.analysis_context.sort_field = "posting_date";
			this.analysis_context.sort_order = "desc";
		} else {
			this.analysis_context.sort_field = "display_code";
		}
		if (this.user_preferences?._loaded) {
			const dimension_type =
				view_axis === "dimension"
					? this.analysis_context.dimension_scope.dimension_type
					: null;
			this.user_preferences.apply_axis_to_controller(
				this.user_preferences.get_axis_key(view_axis, dimension_type)
			);
		}
		this.render_navigator();
		this.render_detail_header();
		const breadcrumb_started = performance.now();
		this.render_breadcrumbs();
		this._last_perf_phases.breadcrumb_ms = Math.round(performance.now() - breadcrumb_started);
		this.destroy_summary_datatable();
		this._sync_store_context({ emit: true });
		if (this.document_scope.from_date && this.document_scope.to_date) {
			this.refresh_summary();
		}
	}

	is_datatable_summary_enabled() {
		return !!this.metadata?.account_explorer_datatable_enabled;
	}

	_begin_grid_render() {
		this.grid_render_generation += 1;
		return this.grid_render_generation;
	}

	_invalidate_grid_render() {
		this.grid_render_generation += 1;
		this.datatable_adapter?.cancel_pending_mount?.();
	}

	_is_stale_grid_render(generation) {
		return generation !== this.grid_render_generation;
	}

	is_summary_grid_ready() {
		if (this.store.get("loading")?.summary) {
			return false;
		}
		if (this.analysis_context.detail_mode === "grouped_gl") {
			return !!this.$grid.find(".ae-gl-grid, .ae-gl-detail").length;
		}
		if (!this.rows.length) {
			return !!this.$grid.find(".ae-empty, .ae-grid-state").length;
		}
		if (this.is_datatable_summary_enabled()) {
			return (
				this.datatable_adapter?.is_mounted?.() &&
				this.datatable_adapter?.is_interaction_ready?.() &&
				!this.datatable_adapter?._loading &&
				!this.$grid?.hasClass("ae-grid-wrap--loading")
			);
		}
		return !!this.$grid.find("table.ae-grid").length;
	}

	destroy_summary_datatable() {
		this.datatable_adapter?.cancel_pending_mount?.();
		if (this.datatable_adapter?.is_mounted()) {
			this.datatable_adapter.destroy();
		}
	}

	async measure_datatable_scroll_fps(row_count = 100) {
		if (!this.is_datatable_summary_enabled()) {
			return { skipped: 1, reason: "DataTable disabled" };
		}
		await this.measure_datatable_stress_row_count(row_count);
		const scroll_el =
			this.$grid.find(".dt-scrollable").get(0) ||
			this.$grid.find(".ae-datatable-host").get(0) ||
			this.$grid.get(0);
		if (!scroll_el) {
			return { skipped: 1, reason: "Missing scroll container" };
		}
		const max_scroll = Math.max(0, scroll_el.scrollHeight - scroll_el.clientHeight);
		if (!max_scroll) {
			return { skipped: 1, reason: "No scroll range", row_count };
		}
		scroll_el.scrollTop = 0;
		await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
		const frame_deltas = [];
		let last_frame = performance.now();
		let scrolled = 0;
		const step = Math.max(24, Math.round(max_scroll / 120));
		const target_scroll = max_scroll;
		await new Promise((resolve) => {
			const tick = (now) => {
				frame_deltas.push(now - last_frame);
				last_frame = now;
				if (scrolled < target_scroll) {
					scroll_el.scrollTop = Math.min(target_scroll, scrolled + step);
					scrolled += step;
					requestAnimationFrame(tick);
					return;
				}
				resolve();
			};
			requestAnimationFrame(tick);
		});
		const samples = frame_deltas.slice(1);
		const fps_values = samples.map((delta) => (delta > 0 ? 1000 / delta : 0)).filter((fps) => fps > 0);
		const average_fps =
			fps_values.length > 0
				? Math.round(fps_values.reduce((total, fps) => total + fps, 0) / fps_values.length)
				: 0;
		return {
			row_count,
			average_fps,
			lowest_fps: fps_values.length ? Math.round(Math.min(...fps_values)) : 0,
			frame_drops: samples.filter((delta) => delta > 33.34).length,
			frame_samples: samples.length,
			scroll_pixels: target_scroll,
		};
	}

	async measure_datatable_stress_row_count(row_count) {
		if (!this.is_datatable_summary_enabled()) {
			return { skipped: 1, reason: "DataTable disabled" };
		}
		const columns = (this.last_summary_columns || []).filter((col) =>
			this.get_default_visible_columns().includes(col.id)
		);
		if (!columns.length) {
			return { skipped: 1, reason: "No summary columns" };
		}
		const sum = (values) => values.reduce((total, value) => total + value, 0);
		const rows = Array.from({ length: row_count }, (_, index) => ({
			row_key: `stress-${row_count}-${index}`,
			display_code: `ACC-${String(index).padStart(5, "0")}`,
			display_title: __("Stress Account {0}", [index + 1]),
			period_debit: 1000 + index,
			period_credit: 500 + index,
			debit_balance: 500 + index,
			credit_balance: 0,
			drill_down_enabled: 1,
			level_sequence: this.analysis_context.level_sequence || 1,
		}));
		const generation = this._begin_grid_render();
		const started_at = performance.now();
		this.rows = rows;
		await this.render_datatable_summary_grid(columns, generation);
		const mount_ms = Math.round(performance.now() - started_at);
		const update_samples = [];
		for (let index = 0; index < 3; index += 1) {
			const sample_started = performance.now();
			await this.datatable_adapter.update(columns, rows, this.get_datatable_grid_options(columns));
			update_samples.push(Math.round(performance.now() - sample_started));
		}
		const adapter_stats = this.datatable_adapter.get_perf_stats();
		const memory = this.get_grid_memory_diagnostics();
		return {
			row_count,
			mount_ms,
			update_samples_ms: update_samples,
			update_avg_ms: Math.round(sum(update_samples) / update_samples.length),
			clusterize: adapter_stats.update?.clusterize ?? adapter_stats.mount?.clusterize ?? null,
			memory,
		};
	}

	get_summary_visible_columns(columns) {
		const hidden = new Set(this.get_summary_hidden_columns());
		const required = this.get_required_summary_column_id();
		const allowed = new Set(this.get_default_visible_columns());
		const ordered_ids = this.get_ordered_summary_column_ids(columns);
		const by_id = new Map((columns || []).map((col) => [col.id, col]));
		return ordered_ids
			.map((id) => by_id.get(id))
			.filter(
				(col) =>
					col &&
					allowed.has(col.id) &&
					(!hidden.has(col.id) || col.id === required)
			);
	}

	get_ordered_summary_column_ids(columns = this.last_summary_columns) {
		const allowed = this.get_default_visible_columns();
		const saved_order = (this.grid_column_order || []).filter((id) => allowed.includes(id));
		const ordered = [];
		saved_order.forEach((id) => {
			if (!ordered.includes(id)) {
				ordered.push(id);
			}
		});
		allowed.forEach((id) => {
			if (!ordered.includes(id)) {
				ordered.push(id);
			}
		});
		(columns || []).forEach((col) => {
			if (col?.id && allowed.includes(col.id) && !ordered.includes(col.id)) {
				ordered.push(col.id);
			}
		});
		return ordered;
	}

	build_datatable_column_state(visible_columns) {
		const sticky = this.grid_sticky_column || this.get_required_summary_column_id();
		return (visible_columns || []).map((col) => ({
			id: col.id,
			width: this.grid_column_widths?.[col.id] || null,
			sortOrder:
				this.analysis_context.sort_field === col.id
					? this.analysis_context.sort_order
					: "none",
			sticky: col.id === sticky,
		}));
	}

	handle_datatable_column_state_changed() {
		const state = (this.datatable_adapter?.get_column_state?.() || []).filter(
			(col) => col?.id && !String(col.id).startsWith("_")
		);
		if (!state.length) {
			return;
		}
		const visible_ids = new Set(state.map((col) => col.id).filter(Boolean));
		const allowed = this.get_default_visible_columns();
		const required = this.get_required_summary_column_id();
		this.grid_column_order = state.map((col) => col.id).filter(Boolean);
		const has_checkbox_column = (this.datatable_adapter?.get_column_state?.() || []).some((col) =>
			String(col?.id || "").startsWith("_")
		);
		// When checkbox/internal columns are present, adapter "visibility" is not a reliable hide signal
		// after programmatic apply_column_state. Preserve explicit controller hides in that case unless
		// the user removed a business column through DataTable chrome.
		const removed_business_columns = allowed.filter(
			(id) => !visible_ids.has(id) && id !== required && !(this.grid_hidden_columns || []).includes(id)
		);
		if (!has_checkbox_column || removed_business_columns.length) {
			this.grid_hidden_columns = allowed.filter((id) => !visible_ids.has(id) && id !== required);
		}
		const widths = { ...(this.grid_column_widths || {}) };
		state.forEach((col) => {
			if (col?.id && col.width) {
				widths[col.id] = col.width;
			}
		});
		Object.keys(widths).forEach((column_id) => {
			if (String(column_id).startsWith("_")) {
				delete widths[column_id];
			}
		});
		this.grid_column_widths = widths;
		this._patch_presentation({ schedule_save: true });
	}

	build_summary_grid_meta_html() {
		const currency_label = this.currency_code || frappe.defaults.get_default("currency");
		const currency_type_label = this.get_currency_type_label();
		const $meta = $('<div class="ae-grid-meta"></div>')
			.append($('<span class="ae-grid-meta-item">').text(__("Rows: {0}", [this.rows.length])))
			.append(
				$('<span class="ae-grid-meta-item ae-currency-badge" title="' + __("Presentation currency") + '">').text(
					currency_label
				)
			);
		if (this.analysis_context.view_axis === "currency" || this.document_scope.currency?.currency_type !== "account_currency") {
			$meta.append(
				$('<span class="ae-grid-meta-item ae-currency-mode" title="' + __("Currency aggregation mode") + '">').text(
					currency_type_label
				)
			);
		}
		return $meta;
	}

	append_summary_grid_options($wrap) {
		if (this.analysis_context.view_axis === "voucher" && this.analysis_context.detail_mode === "summary") {
			$wrap.append(
				$('<div class="ae-grid-options mb-2">').append(
					$('<label class="small text-muted">').append(
						$("<input type='checkbox'>")
							.prop("checked", this.show_optional_full_voucher_columns)
							.on("change", (e) => {
								this.show_optional_full_voucher_columns = e.target.checked;
								this._patch_presentation({ schedule_save: true });
								void this.render_grid(this.last_summary_columns || []);
							}),
						" " + __("Show full voucher debit/credit columns")
					)
				)
			);
		}
		if (this.analysis_context.view_axis === "unified_party" && this.analysis_context.detail_mode === "summary") {
			$wrap.append(
				$('<div class="ae-grid-options mb-2">').append(
					$('<label class="small text-muted">').append(
						$("<input type='checkbox'>")
							.prop("checked", !!this.analysis_context.unified_party_scope.include_unmapped)
							.on("change", (e) => {
								this.analysis_context.unified_party_scope.include_unmapped = e.target.checked ? 1 : 0;
								this.analysis_context.page = 1;
								this.refresh_summary();
							}),
						" " + __("Include unmapped parties")
					)
				)
			);
		}
	}

	build_voucher_actions_html(row) {
		if (!row) {
			return "";
		}
		const specs = [
			{ key: "gl", label: __("GL"), title: __("Grouped GL detail in Account Explorer") },
			{ key: "list", label: __("List"), title: __("General Ledger report for this voucher") },
			{ key: "open", label: __("Open"), title: __("Open source ERPNext document") },
		];
		if (this.metadata?.voucher_print_format) {
			specs.push({ key: "print", label: __("Print"), title: __("Print voucher using configured format") });
		}
		return `<div class="ae-voucher-actions ae-row-actions">${specs
			.map((spec, index) => {
				const sep = index ? '<span class="ae-voucher-action-sep" aria-hidden="true">|</span>' : "";
				return `${sep}<button type="button" class="btn btn-xs btn-default ae-voucher-action ae-voucher-action--${spec.key}" data-action="${spec.key}" title="${frappe.utils.escape_html(
					spec.title
				)}">${frappe.utils.escape_html(spec.label)}</button>`;
			})
			.join("")}</div>`;
	}

	handle_voucher_row_action(row, action) {
		if (!row) {
			return;
		}
		if (action === "gl") {
			this.open_grouped_gl_detail(row);
			return;
		}
		if (action === "list") {
			this.navigate_gl_list(row);
			return;
		}
		if (action === "open") {
			this.navigate_source_voucher(row);
			return;
		}
		if (action === "print") {
			this.navigate_print_voucher(row);
		}
	}

	handle_summary_row_click(row) {
		const row_key = row?.row_key || null;
		this.store.patch({
			selection: {
				selected_row_key: row_key,
			},
		});
		if (
			this.analysis_context.view_axis === "unified_party" &&
			row.unified_party &&
			!row.is_virtual_group
		) {
			this.load_member_breakdown(row);
		}
	}

	handle_summary_row_dblclick(row) {
		this.drill_row(row);
	}

	handle_datatable_selection_change(checked_rows) {
		const checked_keys = (checked_rows || []).map((row) => row.row_key).filter(Boolean);
		this.store.patch({
			selection: {
				selected_row_key: checked_keys[0] || this.store.get("selection")?.selected_row_key || null,
				checked_row_keys: checked_keys,
			},
		});
		this.update_grid_toolbar_state();
		this.announce_grid_status(
			checked_keys.length
				? __("{0} rows selected", [checked_keys.length])
				: __("Selection cleared")
		);
	}

	get_datatable_grid_options(visible_columns) {
		const show_voucher_actions =
			this.analysis_context.view_axis === "voucher" && this.analysis_context.detail_mode === "summary";
		return {
			sort_field: this.analysis_context.sort_field,
			sort_order: this.analysis_context.sort_order,
			checkbox_column: true,
			inline_filters: false,
			density: this.get_grid_density(),
			clusterize: this.datatable_adapter?.should_clusterize?.(this.rows.length) ?? this.rows.length > 50,
			translate: (label) => __(label),
			actions_column: show_voucher_actions ? { width: 220 } : null,
			format_amount: (value) => this.format_display_amount(value),
			render_actions_html: (row) => this.build_voucher_actions_html(row),
			column_widths: { ...(this.grid_column_widths || {}) },
			on_server_sort: (column_id, column) => this.handle_datatable_server_sort(column_id, column),
			on_selection_change: (checked_rows) => this.handle_datatable_selection_change(checked_rows),
			on_column_removed: () => this.handle_datatable_column_state_changed(),
			on_column_switched: () => this.handle_datatable_column_state_changed(),
			on_column_resized: () => this.handle_datatable_column_state_changed(),
			empty_message: __("No rows match the current scope."),
		};
	}

	build_page_size_control() {
		const $wrap = $('<label class="ae-grid-toolbar-control ae-grid-toolbar-control--page-size"></label>');
		$wrap.append($('<span class="ae-grid-toolbar-control-label">').text(__("Page Size")));
		const $select = $('<select class="form-control input-xs ae-grid-page-size-select"></select>');
		erpnext_extensions.account_explorer.core.AE_GRID_PAGE_SIZE_OPTIONS.forEach((size) => {
			$select.append(
				$("<option>")
					.val(String(size))
					.text(String(size))
					.prop("selected", cint(this.analysis_context.page_size) === size)
			);
		});
		$select.on("change", (event) => {
			this.set_page_size($(event.currentTarget).val());
		});
		return $wrap.append($select);
	}

	build_number_format_control() {
		const labels = {
			raw: __("Raw"),
			auto: __("Auto"),
			thousands: __("Thousands"),
			millions: __("Millions"),
			billions: __("Billions"),
			trillions: __("Trillions"),
		};
		const $wrap = $('<label class="ae-grid-toolbar-control ae-grid-toolbar-control--number-format"></label>');
		$wrap.append($('<span class="ae-grid-toolbar-control-label">').text(__("Numbers")));
		const $select = $('<select class="form-control input-xs ae-grid-number-format-select"></select>');
		erpnext_extensions.account_explorer.core.AE_NUMBER_FORMAT_MODES.forEach((mode) => {
			$select.append(
				$("<option>")
					.val(mode)
					.text(labels[mode] || mode)
					.prop("selected", (this.number_format_mode || "auto") === mode)
			);
		});
		$select.on("change", (event) => {
			this.set_number_format_mode($(event.currentTarget).val());
		});
		return $wrap.append($select);
	}

	ensure_summary_grid_prefs_controls() {
		if (this._$grid_prefs_controls?.length && this._$grid_prefs_controls.data("ae-bound")) {
			return this._$grid_prefs_controls;
		}
		const $prefs = $('<div class="ae-grid-toolbar-prefs"></div>');
		$prefs.append(
			this.build_page_size_control(),
			this.build_number_format_control(),
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--reset-prefs">')
				.text(__("Reset Grid Preferences"))
				.attr("aria-label", __("Reset grid preferences for current axis"))
				.on("click", (event) => {
					event.stopPropagation();
					this.prompt_reset_grid_preferences(false);
				}),
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--reset-prefs-all">')
				.text(__("Reset All Axes"))
				.attr("aria-label", __("Reset grid preferences for all axes"))
				.on("click", (event) => {
					event.stopPropagation();
					this.prompt_reset_grid_preferences(true);
				})
		);
		$prefs.data("ae-bound", 1);
		this._$grid_prefs_controls = $prefs;
		return $prefs;
	}

	build_summary_grid_toolbar() {
		const currency_label = this.currency_code || frappe.defaults.get_default("currency");
		const selected_count = this.get_checked_row_count();
		const $toolbar = $('<div class="ae-grid-toolbar"></div>');
		const $actions = $('<div class="ae-grid-toolbar-actions"></div>').appendTo($toolbar);
		$actions.append(
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--columns">')
				.text(__("Columns"))
				.attr("aria-label", __("Choose visible columns"))
				.on("click", (event) => {
					event.stopPropagation();
					this.show_column_chooser();
				}),
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--copy">')
				.text(__("Copy"))
				.attr("aria-label", __("Copy grid data"))
				.on("click", (event) => {
					event.stopPropagation();
					this.show_copy_menu(event.currentTarget);
				}),
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--clear">')
				.text(__("Clear Selection"))
				.attr("aria-label", __("Clear row selection"))
				.prop("disabled", !selected_count)
				.on("click", (event) => {
					event.stopPropagation();
					this.clear_grid_selection();
				}),
			$('<button type="button" class="btn btn-default btn-xs ae-grid-toolbar-btn ae-grid-toolbar-btn--density">')
				.text(this.get_grid_density() === "compact" ? __("Comfortable") : __("Compact"))
				.attr(
					"aria-label",
					this.get_grid_density() === "compact"
						? __("Switch to comfortable density")
						: __("Switch to compact density")
				)
				.on("click", (event) => {
					event.stopPropagation();
					const next = this.get_grid_density() === "compact" ? "comfortable" : "compact";
					this.set_grid_density(next);
					$(event.currentTarget)
						.text(next === "compact" ? __("Comfortable") : __("Compact"))
						.attr(
							"aria-label",
							next === "compact"
								? __("Switch to comfortable density")
								: __("Switch to compact density")
						);
				}),
			this.ensure_summary_grid_prefs_controls()
		);
		const $meta = $('<div class="ae-grid-toolbar-meta"></div>').appendTo($toolbar);
		$meta.append(
			$('<span class="ae-grid-meta-item">').text(__("Rows: {0}", [this.rows.length])),
			$('<span class="ae-grid-meta-item ae-grid-meta-item--selected">').text(
				__("Selected: {0}", [selected_count])
			),
			$('<span class="ae-grid-meta-item ae-currency-badge" title="' + __("Presentation currency") + '">').text(
				currency_label
			)
		);
		return $toolbar;
	}

	update_grid_toolbar_state() {
		const $toolbar = this.$grid.find(".ae-grid-toolbar");
		if (!$toolbar.length) {
			return;
		}
		const selected_count = this.get_checked_row_count();
		$toolbar.find(".ae-grid-meta-item--selected").text(__("Selected: {0}", [selected_count]));
		$toolbar.find(".ae-grid-toolbar-btn--clear").prop("disabled", !selected_count);
		$toolbar.find(".ae-grid-page-size-select").val(String(this.analysis_context.page_size || 50));
		$toolbar.find(".ae-grid-number-format-select").val(this.number_format_mode || "auto");
	}

	show_column_chooser() {
		const columns = (this.last_summary_columns || []).filter((col) =>
			this.get_default_visible_columns().includes(col.id)
		);
		const required = this.get_required_summary_column_id();
		const hidden = new Set(this.get_summary_hidden_columns());
		const fields = columns.map((col) => ({
			fieldtype: "Check",
			fieldname: col.id,
			label: __(col.label),
			default: !hidden.has(col.id) ? 1 : 0,
			read_only: col.id === required ? 1 : 0,
		}));
		const dialog = new frappe.ui.Dialog({
			title: __("Summary Columns"),
			fields: [
				...fields,
				{
					fieldtype: "Button",
					fieldname: "restore_defaults",
					label: __("Restore Defaults"),
				},
			],
			primary_action_label: __("Apply"),
			primary_action: (values) => {
				const next_hidden = columns
					.filter((col) => col.id !== required && !values[col.id])
					.map((col) => col.id);
				if (columns.filter((col) => !next_hidden.includes(col.id)).length < 1) {
					frappe.msgprint(__("At least one business column must remain visible."));
					return;
				}
				this.set_summary_hidden_columns(next_hidden);
				dialog.hide();
				void this.render_grid(this.last_summary_columns || []);
			},
		});
		dialog.fields_dict.restore_defaults.$input.on("click", () => {
			this.restore_column_defaults();
			dialog.hide();
			void this.render_grid(this.last_summary_columns || []);
		});
		dialog.show();
	}

	restore_column_defaults() {
		this.set_summary_hidden_columns([]);
		this.announce_grid_status(__("Column defaults restored"));
	}

	show_copy_menu(anchor) {
		const checked_count = this.get_checked_row_count();
		const active_row = this.datatable_adapter?.get_active_row?.();
		const menu_items = [
			{
				label: __("Copy Cell"),
				action: () => {
					const row = active_row || this.datatable_adapter?.get_checked_rows?.()?.[0];
					const column_id = this.get_effective_visible_column_ids()[0];
					if (!row || !column_id) {
						frappe.show_alert({ message: __("Select a row first"), indicator: "orange" });
						return;
					}
					this.datatable_adapter.copy_cell_value(row, column_id);
				},
				enabled: !!(active_row || checked_count),
			},
			{
				label: __("Copy Row"),
				action: () => {
					const row = active_row || this.datatable_adapter?.get_checked_rows?.()?.[0];
					if (!row) {
						frappe.show_alert({ message: __("Select a row first"), indicator: "orange" });
						return;
					}
					this.datatable_adapter.copy_row_tsv(row);
				},
				enabled: !!(active_row || checked_count),
			},
			{
				label: __("Copy Selected Rows"),
				action: () => this.datatable_adapter.copy_checked_rows_tsv(),
				enabled: checked_count > 0,
			},
		];
		const $menu = $('<ul class="dropdown-menu ae-grid-copy-menu" role="menu"></ul>');
		menu_items.forEach((item) => {
			$menu.append(
				$("<li role='presentation'>").append(
					$('<a role="menuitem" href="#">')
						.text(item.label)
						.toggleClass("disabled", !item.enabled)
						.on("click", (event) => {
							event.preventDefault();
							if (!item.enabled) {
								return;
							}
							item.action();
							$menu.remove();
						})
				)
			);
		});
		$("body").find(".ae-grid-copy-menu").remove();
		const $anchor = $(anchor);
		const offset = $anchor.offset();
		$menu.css({ top: offset.top + $anchor.outerHeight(), left: offset.left }).appendTo("body");
		const dismiss = (event) => {
			if (!$(event.target).closest(".ae-grid-copy-menu, .ae-grid-toolbar-btn--copy").length) {
				$menu.remove();
				$(document).off("click.aeGridCopyMenu");
			}
		};
		setTimeout(() => $(document).on("click.aeGridCopyMenu", dismiss), 0);
	}

	get_grid_empty_reason() {
		if (this.summary_load_error) {
			return "error";
		}
		if (!this.metadata?.enabled) {
			return "permission";
		}
		if (
			this.analysis_context.view_axis === "dimension" &&
			!(this.metadata?.dimensions || []).length
		) {
			return "no_config";
		}
		if (ae_count_active_document_scope_filters(this.document_scope) > 0) {
			return "filtered";
		}
		return "no_data";
	}

	render_grid_empty_state(reason = "no_data") {
		const states = {
			no_data: {
				message: __("No rows exist in the current company and date scope."),
				action_label: null,
				action: null,
			},
			filtered: {
				message: __("No rows match the current Document Scope filters."),
				action_label: __("Clear Advanced Filters"),
				action: () => {
					this.document_scope = ae_clear_advanced_document_scope(this.document_scope);
					this.sync_filter_controls_from_document_scope();
					this.update_advanced_filters_button();
					this.render_filter_summary();
					this.refresh_summary();
				},
			},
			no_config: {
				message: __("No accounting dimensions are available."),
				action_label: frappe.model.can_read?.("Iran Accounting Settings")
					? __("Open Iran Accounting Settings")
					: null,
				action: () => frappe.set_route("Form", "Iran Accounting Settings", "Iran Accounting Settings"),
			},
			permission: {
				message: __("Account Explorer is not available for your user."),
				action_label: null,
				action: null,
			},
			error: {
				message: __("Account Explorer could not load this view."),
				action_label: __("Retry"),
				action: () => this.refresh_summary(),
			},
		};
		const state = states[reason] || states.no_data;
		const $empty = $('<div class="ae-empty ae-grid-state" role="status"></div>');
		$empty.append($('<div class="ae-grid-state-message">').text(state.message));
		if (state.action_label && state.action) {
			$empty.append(
				$('<button type="button" class="btn btn-default btn-sm ae-grid-state-action">')
					.text(state.action_label)
					.on("click", () => state.action())
			);
		}
		this.$grid.html($empty);
		this.announce_grid_status(state.message);
	}

	_bind_grid_keyboard_shortcuts() {
		if (this._grid_keyboard_bound || !this.$grid) {
			return;
		}
		this._grid_keyboard_bound = true;
		this.$grid.on("keydown.aeGridKeyboard", (event) => {
			if (!this.should_handle_datatable_row_event()) {
				return;
			}
			const key = event.key;
			const mod = event.ctrlKey || event.metaKey;
			if (key === "ArrowDown" || key === "ArrowUp") {
				event.preventDefault();
				const delta = key === "ArrowDown" ? 1 : -1;
				const current = this.datatable_adapter.get_active_row_index();
				const next =
					current === null || current === undefined
						? delta > 0
							? 0
							: Math.max(this.rows.length - 1, 0)
						: Math.max(0, Math.min(this.rows.length - 1, current + delta));
				this.datatable_adapter.set_active_row_index(next);
				const row = this.datatable_adapter.get_active_row();
				if (row?.row_key) {
					this.store.patch({ selection: { selected_row_key: row.row_key } });
				}
				return;
			}
			if (key === "Enter") {
				const row = this.datatable_adapter.get_active_row();
				if (row) {
					event.preventDefault();
					this.handle_summary_row_dblclick(row);
				}
				return;
			}
			if (key === " ") {
				const target = event.target;
				if (target?.closest?.(".dt-cell__checkbox, input[type='checkbox']")) {
					return;
				}
				event.preventDefault();
				this.datatable_adapter.toggle_active_row_selection();
				return;
			}
			if (key === "Escape") {
				if (this.get_checked_row_count()) {
					event.preventDefault();
					this.clear_grid_selection();
					return;
				}
				event.preventDefault();
				this.go_back();
				return;
			}
			if (mod && (key === "c" || key === "C")) {
				const row = this.datatable_adapter.get_active_row();
				if (row) {
					event.preventDefault();
					this.datatable_adapter.copy_row_tsv(row);
				}
				return;
			}
			if (event.altKey && key === "ArrowLeft") {
				event.preventDefault();
				this.go_back();
			}
		});
	}

	async render_datatable_summary_grid(columns, generation) {
		if (this._is_stale_grid_render(generation)) {
			return;
		}
		const visible = this.get_summary_visible_columns(columns);
		this.last_summary_columns = columns || [];
		const options = this.get_datatable_grid_options(visible);
		const incremental = this.should_datatable_incremental_update();
		let $host = this.$grid.find(".ae-datatable-container");
		const toolbar_started = performance.now();
		if (!$host.length) {
			const $wrap = $('<div class="ae-grid-container ae-grid-container--datatable"></div>');
			this.append_summary_grid_options($wrap);
			$wrap.append(this.build_summary_grid_toolbar());
			$host = $('<div class="ae-datatable-container"></div>').appendTo($wrap);
			this.$grid.empty().append($wrap);
		} else if (incremental) {
			this.update_summary_grid_toolbar_counts();
		}
		this._last_perf_phases.toolbar_ms = Math.round(performance.now() - toolbar_started);
		if (this._is_stale_grid_render(generation)) {
			return;
		}
		this._suppress_datatable_sort_events = true;
		const datatable_started = performance.now();
		try {
			if (incremental) {
				await this.datatable_adapter.update(visible, this.rows, options);
			} else {
				await this.datatable_adapter.mount($host[0], visible, this.rows, options);
			}
		} finally {
			this._suppress_datatable_sort_events = false;
		}
		this._last_perf_phases.datatable_ms = Math.round(performance.now() - datatable_started);
		if (this._is_stale_grid_render(generation)) {
			return;
		}
		if (!this.grid_column_order?.length) {
			this.grid_column_order = visible.map((col) => col.id);
		}
		this.datatable_adapter.set_loading(false);
		const presentation = this.build_presentation_state();
		const presentation_signature = JSON.stringify(presentation);
		if (this._presentation_signature !== presentation_signature) {
			this._presentation_signature = presentation_signature;
			this.store.patch({ presentation }, { silent: true });
		}
		this.announce_grid_status(__("Summary grid ready"));
	}

	is_voucher_analysis_enabled() {
		return !!(this.metadata && this.metadata.voucher_analysis_enabled);
	}

	is_party_analysis_enabled() {
		return !!(this.metadata && this.metadata.party_analysis_enabled);
	}

	is_dimension_analysis_enabled() {
		return !!(this.metadata && this.metadata.dimension_analysis_enabled);
	}

	is_dimension_field_navigable(fieldname) {
		if (!fieldname || !this.is_dimension_analysis_enabled()) {
			return false;
		}
		const dimension_axis = (this.metadata.axes || []).find((axis) => axis.id === "dimension");
		if (!dimension_axis || !dimension_axis.enabled) {
			return false;
		}
		return (dimension_axis.children || []).some((child) => child.fieldname === fieldname);
	}

	is_unified_party_enabled() {
		return !!(this.metadata && this.metadata.unified_party_enabled);
	}

	is_currency_analysis_enabled() {
		return !!(this.metadata && this.metadata.currency_analysis_enabled);
	}

	sync_dates_from_fy() {
		const fy = this.fy_field.get_value();
		if (!fy) {
			return;
		}
		frappe.db.get_value("Fiscal Year", fy, ["year_start_date", "year_end_date"]).then((r) => {
			if (!r.message) {
				return;
			}
			this.from_date_field.set_value(r.message.year_start_date);
			this.to_date_field.set_value(r.message.year_end_date);
			this.document_scope.from_date = r.message.year_start_date;
			this.document_scope.to_date = r.message.year_end_date;
		});
	}

	build_payload() {
		return {
			document_scope: {
				...this.document_scope,
				voucher: { ...this.document_scope.voucher },
				accounting: { ...this.document_scope.accounting },
				accounting_dimensions: { ...this.document_scope.accounting_dimensions },
				currency: { ...this.document_scope.currency },
				status: { ...this.document_scope.status },
			},
			analysis_context: {
				...this.analysis_context,
				account_scope: { ...this.analysis_context.account_scope },
				party_scope: { ...this.analysis_context.party_scope },
				unified_party_scope: { ...this.analysis_context.unified_party_scope },
				dimension_scope: { ...this.analysis_context.dimension_scope },
				voucher_scope: { ...this.analysis_context.voucher_scope },
			},
		};
	}

	get_summary_method() {
		if (this.analysis_context.detail_mode === "grouped_gl") {
			return `${this.api_base}.get_grouped_gl_entries`;
		}
		const axis = this.analysis_context.view_axis || "account_level";
		if (axis === "party") {
			return `${this.api_base}.get_party_summary`;
		}
		if (axis === "unified_party") {
			return `${this.api_base}.get_unified_party_summary`;
		}
		if (axis === "dimension") {
			return `${this.api_base}.get_dimension_summary`;
		}
		if (axis === "currency") {
			return `${this.api_base}.get_currency_summary`;
		}
		if (axis === "voucher") {
			return `${this.api_base}.get_voucher_summary`;
		}
		return `${this.api_base}.get_account_summary`;
	}

	apply_scope() {
		this.sync_document_scope_from_controls();
		if (!this.document_scope.company) {
			frappe.msgprint(__("Company is required."));
			return;
		}
		if (!this.document_scope.from_date || !this.document_scope.to_date) {
			frappe.msgprint(__("From Date and To Date are required before running queries."));
			return;
		}
		this.analysis_context.page = 1;
		this.clear_grid_selection();
		this.update_advanced_filters_button();
		this.render_filter_summary();
		this.refresh_summary();
	}

	refresh_summary() {
		const refresh_task = this._summary_refresh_tail.then(() => this._refresh_summary());
		this._summary_refresh_tail = refresh_task.catch(() => {});
		return refresh_task;
	}

	async _refresh_summary() {
		if (!this.metadata || !this.metadata.enabled) {
			return;
		}
		if (!this.document_scope.company || !this.document_scope.from_date || !this.document_scope.to_date) {
			this.render_prompt(__("Select Company and date range, then click Apply."));
			return;
		}

		const perf_operation =
			this._pending_grid_perf_operation ||
			(this.should_datatable_incremental_update() ? "refresh" : "first_render");
		this._pending_grid_perf_operation = null;
		this.begin_grid_perf(perf_operation, {
			view_axis: this.analysis_context.view_axis,
			page: this.analysis_context.page,
		});

		const generation = this._begin_grid_render();
		this.summary_load_error = null;
		this.$grid?.addClass("ae-grid-wrap--loading");
		this.store.patch({ loading: { summary: true } });
		this.events.emit("summary:loading");
		if (this.is_datatable_summary_enabled()) {
			this.datatable_adapter?.set_loading?.(true);
		}

		try {
			const api_started_at = performance.now();
			const r = await frappe.call({
				method: this.get_summary_method(),
				args: { payload: JSON.stringify(this.build_payload()) },
			});
			const api_elapsed_ms = Math.round(performance.now() - api_started_at);
			if (this._is_stale_grid_render(generation)) {
				return;
			}
			const data = r.message || {};
			this.rows = data.rows || [];
			this.totals = data.totals || {};
			this.currency_code = data.currency?.code || this.currency_code;
			this.pagination = data.pagination || this.pagination;
			this.warnings = data.warnings || [];
			this.voucher_header = data.voucher_header || null;
			this.gl_dimensions = data.dimensions || this.gl_dimensions || [];
			this.sync_gl_dimension_visibility();
			this.last_gl_columns = data.columns || [];
			const detail_started = performance.now();
			this.render_detail_header();
			const detail_header_ms = Math.round(performance.now() - detail_started);
			const render_started_at = performance.now();
			await this.render_grid(data.columns || [], generation);
			const render_elapsed_ms = Math.round(performance.now() - render_started_at);
			if (this._is_stale_grid_render(generation)) {
				return;
			}
			const totals_started = performance.now();
			this.render_totals();
			const totals_ms = Math.round(performance.now() - totals_started);
			const warnings_started = performance.now();
			this.render_warnings();
			const warnings_ms = Math.round(performance.now() - warnings_started);
			const pagination_started = performance.now();
			this.render_pagination();
			const pagination_ms = Math.round(performance.now() - pagination_started);
			if (this.analysis_context.view_axis !== "unified_party") {
				this.hide_member_panel();
			}
			this.events.emit("summary:loaded", { data });
			this.end_grid_perf({
				api_elapsed_ms,
				render_elapsed_ms,
				phases: {
					...this._last_perf_phases,
					detail_header_ms,
					totals_ms,
					warnings_ms,
					pagination_ms,
				},
			});
		} catch (error) {
			if (!this._is_stale_grid_render(generation)) {
				console.error("[Account Explorer] summary refresh failed", error);
				this.summary_load_error = error;
				this.destroy_summary_datatable();
				this.render_grid_empty_state("error");
				this.end_grid_perf({ failed: 1 });
				frappe.show_alert({
					message: __("Unable to refresh Account Explorer summary."),
					indicator: "red",
				});
			}
			throw error;
		} finally {
			if (!this._is_stale_grid_render(generation)) {
				this.$grid?.removeClass("ae-grid-wrap--loading");
				this.datatable_adapter?.set_loading?.(false);
				this.store.patch({ loading: { summary: false } });
			}
		}
	}

	get_gl_dimension_definitions() {
		if (this.gl_dimensions?.length) {
			return this.gl_dimensions;
		}
		return (this.metadata?.dimensions || []).map((row) => ({
			fieldname: row.fieldname,
			label: row.label,
			label_fa: row.label_fa,
			document_type: row.document_type,
		}));
	}

	get_gl_dimension_expand_threshold() {
		return cint(this.metadata?.gl_dimension_expand_threshold || 5);
	}

	sync_gl_dimension_visibility() {
		this.get_gl_dimension_definitions().forEach((definition) => {
			if (this.gl_dimension_column_visibility[definition.fieldname] === undefined) {
				this.gl_dimension_column_visibility[definition.fieldname] = true;
			}
		});
	}

	is_fa_locale() {
		return (frappe.boot?.lang || "").startsWith("fa");
	}

	get_gl_dimension_label(definition) {
		if (this.is_fa_locale() && definition.label_fa) {
			return definition.label_fa;
		}
		return definition.label || definition.fieldname;
	}

	get_gl_dimension_layout() {
		const count = this.get_gl_dimension_definitions().length;
		const threshold = this.get_gl_dimension_expand_threshold();
		if (count > threshold) {
			return "compact_with_selector";
		}
		if (this.show_full_voucher_dimensions && count <= threshold) {
			return "expanded";
		}
		return "compact";
	}

	get_visible_gl_dimension_definitions() {
		const definitions = this.get_gl_dimension_definitions();
		if (this.get_gl_dimension_layout() !== "compact_with_selector") {
			return definitions;
		}
		return definitions.filter(
			(definition) => this.gl_dimension_column_visibility[definition.fieldname] !== false
		);
	}

	get_default_visible_columns() {
		if (this.analysis_context.detail_mode === "grouped_gl") {
			const layout = this.get_gl_dimension_layout();
			if (layout === "expanded") {
				const cols = [
					"posting_date",
					"account",
					"account_name",
					"party_type",
					"party_name",
				];
				this.get_gl_dimension_definitions().forEach((dimension) => {
					cols.push(`dim:${dimension.fieldname}`);
				});
				cols.push("debit", "credit", "currency", "remarks");
				return cols;
			}
			const cols = ["account_name", "party_name", "debit", "credit"];
			if (this.get_visible_gl_dimension_definitions().length) {
				cols.splice(2, 0, "dimensions");
			}
			return cols;
		}
		const axis = this.analysis_context.view_axis || "account_level";
		if (axis === "party") {
			return ["party_type", "display_code", "display_title", "period_debit", "period_credit", "debit_balance", "credit_balance"];
		}
		if (axis === "unified_party") {
			return [
				"display_code",
				"display_title",
				"member_count",
				"primary_member_label",
				"identifier_summary",
				"period_debit",
				"period_credit",
				"debit_balance",
				"credit_balance",
			];
		}
		if (axis === "dimension") {
			return ["display_code", "display_title", "period_debit", "period_credit", "debit_balance", "credit_balance"];
		}
		if (axis === "currency") {
			return ["currency", "period_debit", "period_credit", "debit_balance", "credit_balance", "net_balance"];
		}
		if (axis === "voucher") {
			const cols = [
				"posting_date",
				"voucher_type",
				"voucher_no",
				"party_type",
				"party_name",
				"voucher_title",
				"reference",
				"scoped_debit",
				"scoped_credit",
				"scoped_net",
			];
			if (this.show_optional_full_voucher_columns) {
				cols.push("full_voucher_debit", "full_voucher_credit");
			}
			return cols;
		}
		return ["display_code", "display_title", "period_debit", "period_credit", "debit_balance", "credit_balance"];
	}

	render_detail_header() {
		this.$detail_header.empty().removeClass("ae-gl-detail-header");
		if (this.analysis_context.detail_mode !== "grouped_gl") {
			this.$detail_header.hide();
			return;
		}
		this.$detail_header.show().addClass("ae-gl-detail-header");
		const header = this.voucher_header || {};
		const voucher_scope = this.analysis_context.voucher_scope || {};
		const voucher_type = header.voucher_type || voucher_scope.voucher_type || "";
		const voucher_no = header.voucher_no || voucher_scope.voucher_no || "";
		const posting_date = header.posting_date || "";
		const company = this.document_scope.company || this.company_field?.get_value() || "";
		const currency_label = this.currency_code || frappe.defaults.get_default("currency") || "";
		const total_debit = this.totals?.debit ?? header.total_debit ?? 0;
		const total_credit = this.totals?.credit ?? header.total_credit ?? 0;

		const $toolbar = $('<div class="ae-gl-header-toolbar"></div>').appendTo(this.$detail_header);
		$toolbar.append(
			$('<button class="btn btn-default btn-sm ae-back-vouchers">')
				.text(__("Back to Vouchers"))
				.on("click", () => this.back_to_voucher_summary()),
			$('<span class="ae-gl-detail-title">').text(__("GL Detail"))
		);
		$toolbar.append(this.render_gl_dimension_header_controls());

		const $facts = $('<div class="ae-gl-voucher-facts"></div>').appendTo(this.$detail_header);
		[
			[__("Voucher Type"), voucher_type],
			[__("Voucher Number"), voucher_no],
			[__("Posting Date"), posting_date],
			[__("Company"), company],
			[__("Currency"), currency_label],
		].forEach(([label, value]) => {
			if (!value) {
				return;
			}
			$facts.append(
				$('<div class="ae-gl-fact-item">').append(
					$('<span class="ae-gl-fact-label">').text(label),
					$('<span class="ae-gl-fact-value">').text(value)
				)
			);
		});

		const $kpi = $('<div class="ae-gl-voucher-kpi"></div>').appendTo(this.$detail_header);
		[
			[total_debit, __("Debit Total")],
			[total_credit, __("Credit Total")],
		].forEach(([amount, label]) => {
			const { compact, full } = this.format_display_amount(amount || 0);
			const $value = $('<span class="ae-gl-kpi-value amount ae-amount-compact">')
				.text(compact)
				.attr("title", full)
				.attr("aria-label", full);
			if (compact !== full) {
				$value.addClass("ae-amount-compact--abbreviated");
			}
			$kpi.append(
				$('<div class="ae-gl-kpi-item">').append(
					$('<span class="ae-gl-kpi-label">').text(label),
					$value
				)
			);
		});

		const $actions = $('<div class="ae-gl-voucher-actions ae-voucher-actions"></div>').appendTo(
			this.$detail_header
		);
		this.render_voucher_action_bar($actions, this.get_gl_detail_voucher_row(), { include_gl: true, include_copy_link: true });
	}

	render_gl_dimension_header_controls() {
		const $controls = $('<div class="ae-gl-header-controls"></div>');
		const layout = this.get_gl_dimension_layout();
		const dimension_count = this.get_gl_dimension_definitions().length;
		const threshold = this.get_gl_dimension_expand_threshold();

		if (dimension_count > threshold) {
			const visible_count = this.get_visible_gl_dimension_definitions().length;
			const $dropdown = $('<div class="dropdown ae-gl-dimension-selector"></div>').appendTo($controls);
			$dropdown.append(
				$('<button type="button" class="btn btn-default btn-sm dropdown-toggle" data-toggle="dropdown">')
					.text(__("Dimension Columns ({0}/{1})", [visible_count, dimension_count]))
					.attr("title", __("Choose visible accounting dimensions"))
			);
			const $menu = $('<ul class="dropdown-menu ae-gl-dimension-menu"></ul>').appendTo($dropdown);
			this.get_gl_dimension_definitions().forEach((definition) => {
				const label = this.get_gl_dimension_label(definition);
				const checked = this.gl_dimension_column_visibility[definition.fieldname] !== false;
				const $item = $('<li></li>').appendTo($menu);
				$item.append(
					$('<label class="ae-gl-dimension-menu-item">').append(
						$("<input type='checkbox'>")
							.prop("checked", checked)
							.on("change", (e) => {
								this.gl_dimension_column_visibility[definition.fieldname] = e.target.checked;
								if (!this.get_visible_gl_dimension_definitions().length) {
									this.gl_dimension_column_visibility[definition.fieldname] = true;
									e.target.checked = true;
									frappe.show_alert({
										message: __("At least one dimension must remain visible."),
										indicator: "orange",
									});
									return;
								}
								this.render_detail_header();
								this.render_gl_detail_view(this.last_gl_columns || []);
							}),
						$("<span>").text(label)
					)
				);
			});
			return $controls;
		}

		if (!dimension_count) {
			return $controls;
		}

		$controls.append(
			$('<label class="ae-gl-full-dimensions-toggle btn btn-default btn-sm">').append(
				$("<input type='checkbox' class='ae-gl-full-dimensions-input'>")
					.prop("checked", !!this.show_full_voucher_dimensions)
					.on("change", (e) => {
						this.show_full_voucher_dimensions = e.target.checked;
						this.render_detail_header();
						this.render_gl_detail_view(this.last_gl_columns || []);
					}),
				$("<span>").text(__("Full Dimensions"))
			)
		);
		return $controls;
	}

	get_gl_detail_voucher_row() {
		const header = this.voucher_header || {};
		const voucher_scope = this.analysis_context.voucher_scope || {};
		return {
			voucher_type: header.voucher_type || voucher_scope.voucher_type,
			voucher_no: header.voucher_no || voucher_scope.voucher_no,
		};
	}

	render_voucher_action_bar($container, row, options = {}) {
		const { include_gl = false, include_copy_link = false } = options;
		const action_specs = [];
		if (include_gl) {
			action_specs.push({
				key: "gl",
				label: __("GL"),
				title: __("GL detail (current view)"),
				disabled: true,
			});
		} else {
			action_specs.push({
				key: "gl",
				label: __("GL"),
				title: __("Grouped GL detail in Account Explorer"),
				handler: () => this.open_grouped_gl_detail(row),
			});
		}
		action_specs.push(
			{
				key: "list",
				label: __("List"),
				title: __("General Ledger report for this voucher"),
				handler: () => this.navigate_gl_list(row),
			},
			{
				key: "open",
				label: __("Open"),
				title: __("Open source ERPNext document"),
				handler: () => this.navigate_source_voucher(row),
			}
		);
		if (this.metadata?.voucher_print_format) {
			action_specs.push({
				key: "print",
				label: __("Print"),
				title: __("Print voucher using configured format"),
				handler: () => this.navigate_print_voucher(row),
			});
		}
		if (include_copy_link) {
			action_specs.push({
				key: "copy",
				label: __("Copy Link"),
				title: __("Copy voucher link to clipboard"),
				handler: () => this.copy_gl_detail_link(row),
			});
		}
		action_specs.forEach((spec, index) => {
			if (index > 0) {
				$container.append($('<span class="ae-voucher-action-sep" aria-hidden="true">|</span>'));
			}
			const $btn = $('<button type="button" class="btn btn-xs btn-default ae-voucher-action">')
				.addClass(`ae-voucher-action--${spec.key}`)
				.text(spec.label)
				.attr("title", spec.title);
			if (spec.disabled) {
				$btn.prop("disabled", true).addClass("active");
			} else {
				$btn.on("click", (e) => {
					e.stopPropagation();
					spec.handler();
				});
			}
			$btn.appendTo($container);
		});
	}

	copy_gl_detail_link(row) {
		if (!row?.voucher_type || !row?.voucher_no) {
			frappe.msgprint(__("Voucher link is not available."));
			return;
		}
		const slug = frappe.router.slug(row.voucher_type);
		const url = `${window.location.origin}/app/${slug}/${encodeURIComponent(row.voucher_no)}`;
		frappe.utils.copy_to_clipboard(url);
		frappe.show_alert({ message: __("Link copied"), indicator: "green" });
	}

	back_to_voucher_summary() {
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.view_axis = "voucher";
		this.analysis_context.page = 1;
		this.render_detail_header();
		this.render_navigator();
		this.refresh_summary();
	}

	render_prompt(message) {
		this.$grid.html(`<div class="ae-empty">${frappe.utils.escape_html(message)}</div>`);
	}

	async render_grid(columns, generation = null) {
		const render_generation = generation ?? this._begin_grid_render();
		this._grid_lifecycle_counters.grid_render_count += 1;
		if (this.analysis_context.detail_mode === "grouped_gl") {
			this.destroy_summary_datatable();
			if (this._is_stale_grid_render(render_generation)) {
				return;
			}
			this.render_gl_detail_view(columns);
			return;
		}
		if (!this.rows.length) {
			this.destroy_summary_datatable();
			if (this._is_stale_grid_render(render_generation)) {
				return;
			}
			this.render_grid_empty_state(this.get_grid_empty_reason());
			return;
		}
		if (this.is_datatable_summary_enabled()) {
			try {
				await this.render_datatable_summary_grid(columns, render_generation);
			} catch (error) {
				if (this._is_stale_grid_render(render_generation)) {
					return;
				}
				console.error("[Account Explorer] DataTable summary render failed; using legacy grid.", error);
				this.destroy_summary_datatable();
				if (this._is_stale_grid_render(render_generation)) {
					return;
				}
				this.render_legacy_summary_grid(columns);
			}
			return;
		}
		this.destroy_summary_datatable();
		if (this._is_stale_grid_render(render_generation)) {
			return;
		}
		this.render_legacy_summary_grid(columns);
	}

	render_legacy_summary_grid(columns) {
		const allowed = new Set(this.get_default_visible_columns());
		const visible = columns.filter((c) => allowed.has(c.id));
		this.last_summary_columns = columns || [];
		const show_voucher_actions =
			this.analysis_context.view_axis === "voucher" && this.analysis_context.detail_mode === "summary";
		const $meta = this.build_summary_grid_meta_html();
		const $table = $('<table class="ae-grid"><thead></thead><tbody></tbody></table>');
		const $head = $("<tr></tr>").appendTo($table.find("thead"));
		visible.forEach((col) => {
			const cls = col.fieldtype === "Currency" ? "amount" : "";
			const is_sorted = this.analysis_context.sort_field === col.id;
			const sort_cls = is_sorted ? ` ae-sort-active ae-sort-${this.analysis_context.sort_order}` : "";
			$("<th>")
				.addClass(`${cls} ae-sortable${sort_cls}`)
				.attr("aria-sort", is_sorted ? this.analysis_context.sort_order + "ending" : "none")
				.append($('<span class="ae-th-label">').text(__(col.label)), $('<span class="ae-sort-indicator">'))
				.on("click", () => this.toggle_sort(col.id))
				.appendTo($head);
		});
		if (show_voucher_actions) {
			$("<th>").addClass("ae-actions-col").text(__("Actions")).appendTo($head);
		}

		const $body = $table.find("tbody");
		this.rows.forEach((row) => {
			const $tr = $("<tr>").data("row", row).appendTo($body);
			if (row.is_virtual_group) {
				$tr.addClass("ae-virtual-row");
			}
			if (row.drill_down_enabled !== 0 && row.drill_down_enabled !== false) {
				$tr.addClass("ae-grid-row--drillable");
			}
			const is_drillable = row.drill_down_enabled !== 0 && row.drill_down_enabled !== false;
			if (is_drillable) {
				$tr.attr("title", __("Click to select · Double-click to drill down"));
			}
			visible.forEach((col, col_index) => {
				const cls = col.fieldtype === "Currency" ? "amount" : "";
				let value = row[col.id];
				const $cell = $("<td>").addClass(cls);
				if (col_index === 0 && is_drillable) {
					$cell.addClass("ae-drill-cell").append(
						$('<span class="ae-drill-icon" aria-hidden="true">›</span>'),
						$('<span class="ae-drill-label">').text(value ?? "")
					);
				} else if (col.fieldtype === "Currency") {
					this.render_amount_cell($cell, value);
				} else {
					$cell.text(value ?? "");
				}
				$cell.appendTo($tr);
			});
			if (show_voucher_actions) {
				const $actions = $('<td class="ae-row-actions ae-voucher-actions">').appendTo($tr);
				this.render_voucher_action_bar($actions, row);
			}
			$tr.on("dblclick", () => this.drill_row(row));
			$tr.on("click", () => {
				$body.find("tr.selected").removeClass("selected");
				$tr.addClass("selected");
				if (
					this.analysis_context.view_axis === "unified_party" &&
					row.unified_party &&
					!row.is_virtual_group
				) {
					this.load_member_breakdown(row);
				}
			});
		});

		const $wrap = $('<div class="ae-grid-container ae-grid-container--legacy"></div>');
		this.append_summary_grid_options($wrap);
		$wrap.append($meta);
		$wrap.append($('<div class="ae-grid-scroll"></div>').append($table));
		this.$grid.empty().append($wrap);
	}

	open_grouped_gl_detail(row) {
		this.destroy_summary_datatable();
		this.analysis_context.voucher_scope = {
			voucher_type: row.voucher_type,
			voucher_no: row.voucher_no,
		};
		this.analysis_context.detail_mode = "grouped_gl";
		this.analysis_context.view_axis = "voucher";
		this.analysis_context.page = 1;
		this.analysis_context.sort_field = "posting_date";
		this.analysis_context.sort_order = "asc";
		this.render_breadcrumbs();
		this.render_navigator();
		this.render_detail_header();
		this.refresh_summary();
		this.update_context_actions();
	}

	render_gl_detail_view(columns) {
		if (!this.rows.length) {
			this.render_prompt(__("No GL entries match the current scope."));
			return;
		}
		const allowed = new Set(this.get_default_visible_columns());
		const visible = columns.filter((col) => allowed.has(col.id));
		const currency_label = this.currency_code || frappe.defaults.get_default("currency");
		const layout = this.get_gl_dimension_layout();

		const $wrap = $('<div class="ae-gl-detail"></div>');
		if (layout === "expanded") {
			$wrap.addClass("ae-gl-detail--full-dimensions");
		}
		if (layout === "compact_with_selector") {
			$wrap.addClass("ae-gl-detail--selector-mode");
		}
		$wrap.append(
			$('<div class="ae-grid-meta ae-gl-grid-meta"></div>')
				.append($('<span class="ae-grid-meta-item">').text(__("Rows on page: {0}", [this.rows.length])))
				.append(
					$('<span class="ae-grid-meta-item ae-currency-badge" title="' + __("Presentation currency") + '">').text(
						currency_label
					)
				)
		);
		$wrap.append(this.build_gl_detail_section(__("GL Lines"), visible, this.rows));
		this.$grid.empty().append($wrap);
	}

	build_gl_detail_section(title, visible_columns, rows) {
		const $section = $('<div class="ae-gl-detail-section"></div>');
		$section.append($('<div class="ae-gl-detail-section-title">').text(title));
		if (!rows.length) {
			$section.append($('<div class="ae-empty ae-gl-section-empty small">').text(__("No rows on this page.")));
			return $section;
		}
		const $table = $('<table class="ae-grid ae-gl-grid"><thead></thead><tbody></tbody></table>');
		const $head = $("<tr></tr>").appendTo($table.find("thead"));
		visible_columns.forEach((col) => {
			const cls = col.fieldtype === "Currency" ? "amount" : "";
			const is_sorted = this.analysis_context.sort_field === col.id;
			const sort_cls = is_sorted ? ` ae-sort-active ae-sort-${this.analysis_context.sort_order}` : "";
			const sortable = this.is_gl_detail_column_sortable(col);
			const $th = $("<th>")
				.addClass(`${cls}${sortable ? ` ae-sortable${sort_cls}` : ""}`)
				.append(
					$('<span class="ae-th-label">').text(
						col.column_kind === "dimensions_compact"
							? ""
							: col.label_fa && this.is_fa_locale()
								? col.label_fa
								: __(col.label)
					)
				);
			if (col.column_kind === "dimensions_compact") {
				$th.addClass("ae-gl-dimensions-col").attr("aria-label", __(col.label_key || "Accounting Dimension Details"));
			}
			if (sortable) {
				$th.attr("aria-sort", is_sorted ? this.analysis_context.sort_order + "ending" : "none");
				$th.append($('<span class="ae-sort-indicator">'));
				$th.on("click", () => this.toggle_sort(col.id));
			}
			$th.appendTo($head);
		});
		const $body = $table.find("tbody");
		rows.forEach((row) => {
			const $tr = $("<tr>").data("row", row).appendTo($body);
			if (row.side === "debit") {
				$tr.addClass("ae-gl-row--debit");
			} else if (row.side === "credit") {
				$tr.addClass("ae-gl-row--credit");
			}
			visible_columns.forEach((col) => {
				const cls = col.fieldtype === "Currency" ? "amount" : "";
				const $cell = $("<td>").addClass(cls);
				if (col.column_kind === "dimensions_compact") {
					this.render_gl_dimensions_cell($cell, row);
					$cell.appendTo($tr);
					return;
				}
				const value = row[col.id];
				if (this.render_gl_detail_link_cell($cell, col, row, value)) {
					$cell.appendTo($tr);
					return;
				}
				if (col.fieldtype === "Currency") {
					this.render_amount_cell($cell, value);
				} else {
					$cell.text(value ?? "");
				}
				$cell.appendTo($tr);
			});
		});
		$section.append($('<div class="ae-grid-scroll"></div>').append($table));
		return $section;
	}

	is_gl_detail_column_sortable(col) {
		// FUTURE ENHANCEMENT: enable dim:* sorting once QuerySpec validation accepts dynamic fields.
		if (col.column_kind === "dimensions_compact" || col.column_kind === "dimension") {
			return false;
		}
		return true;
	}

	render_gl_dimensions_cell($cell, row) {
		$cell.addClass("ae-gl-dimensions-cell");
		const dimensions = row.dimensions || {};
		const $list = $('<div class="ae-gl-dimensions-compact"></div>');
		this.get_visible_gl_dimension_definitions().forEach((definition) => {
			const info = dimensions[definition.fieldname] || {
				label: definition.label,
				label_fa: definition.label_fa,
				value: "",
				title: "",
			};
			const dimension_label = this.get_gl_dimension_label({
				label: info.label || definition.label,
				label_fa: info.label_fa || definition.label_fa,
				fieldname: definition.fieldname,
			});
			const $item = $('<div class="ae-gl-dimension-item"></div>');
			$item.append($('<span class="ae-gl-dimension-label">').text(`${dimension_label}:`));
			const display = info.title || info.value || "";
			if (info.value && this.is_dimension_field_navigable(definition.fieldname)) {
				$item.append(this.build_gl_dimension_link(definition.fieldname, display, info.value));
			} else if (display) {
				$item.append($('<span class="ae-gl-dimension-value">').text(display));
			} else {
				$item.append($('<span class="ae-gl-dimension-value ae-gl-dimension-value--empty">').text("—"));
			}
			$list.append($item);
		});
		$cell.append($list);
	}

	build_gl_dimension_link(fieldname, label, value) {
		return $('<button type="button" class="btn btn-link btn-xs ae-gl-link-btn ae-gl-dimension-value">')
			.text(label)
			.attr("title", __("Open {0} analysis", [label]))
			.on("click", (e) => {
				e.stopPropagation();
				this.navigate_gl_dimension(fieldname, value);
			});
	}

	render_gl_detail_link_cell($cell, col, row, value) {
		const column_id = col.id;
		if (column_id === "account" || column_id === "account_name") {
			const label = value || row.account_name || row.account;
			if (!label) {
				return false;
			}
			$cell.addClass("ae-gl-link ae-gl-link--account").append(
				$('<button type="button" class="btn btn-link btn-xs ae-gl-link-btn">')
					.text(label)
					.attr("title", __("Open account in Account Explorer"))
					.on("click", (e) => {
						e.stopPropagation();
						this.navigate_gl_account(row);
					})
			);
			return true;
		}
		if ((column_id === "party" || column_id === "party_name") && row.party_type && row.party) {
			if (!this.is_party_analysis_enabled()) {
				return false;
			}
			$cell.addClass("ae-gl-link ae-gl-link--party").append(
				$('<button type="button" class="btn btn-link btn-xs ae-gl-link-btn">')
					.text(value)
					.attr("title", __("Open party analysis"))
					.on("click", (e) => {
						e.stopPropagation();
						this.navigate_gl_party(row);
					})
			);
			return true;
		}
		if (col.column_kind === "dimension") {
			const fieldname = col.dimension_fieldname || column_id.slice(4);
			const info = row.dimensions?.[fieldname] || {};
			const link_value = info.value || value;
			const link_label = info.title || info.value || value || "";
			const column_label = this.get_gl_dimension_label({
				label: col.label,
				label_fa: col.label_fa,
				fieldname,
			});
			if (!link_value) {
				$cell.addClass("ae-gl-dimension-value--empty").text("—");
				return true;
			}
			if (!this.is_dimension_field_navigable(fieldname)) {
				$cell.text(link_label);
				return true;
			}
			$cell.addClass("ae-gl-link ae-gl-link--dimension").append(
				this.build_gl_dimension_link(fieldname, link_label, link_value).attr(
					"title",
					__("Open {0} analysis", [column_label])
				)
			);
			return true;
		}
		return false;
	}

	leave_gl_detail_for_analysis() {
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.voucher_scope = { voucher_type: null, voucher_no: null };
		this.analysis_context.page = 1;
		this.voucher_header = null;
		this.render_detail_header();
		this.update_context_actions();
	}

	navigate_gl_account(row) {
		if (!row?.account) {
			return;
		}
		this.leave_gl_detail_for_analysis();
		this._reset_breadcrumbs([]);
		this.analysis_context.view_axis = "account_level";
		this.analysis_context.account_scope = {
			mode: "account",
			selected_account: row.account,
			virtual_row_key: null,
			is_virtual_group: 0,
			level_sequence: null,
			tree_root_account: row.account,
		};
		this.push_breadcrumb({
			label: row.account_name || row.account,
			axis: "account_level",
			selected_account: row.account,
			virtual_row_key: null,
			level_sequence: null,
		});
		this.render_navigator();
		this.render_breadcrumbs();
		this.refresh_summary();
	}

	navigate_gl_party(row) {
		if (!row?.party_type || !row?.party) {
			return;
		}
		if (!this.is_party_analysis_enabled()) {
			frappe.msgprint(__("Party analysis is not enabled."));
			return;
		}
		this.leave_gl_detail_for_analysis();
		this._reset_breadcrumbs([]);
		this.analysis_context.view_axis = "party";
		this.analysis_context.party_scope = {
			party_type: row.party_type,
			selected_party: row.party,
		};
		this.push_breadcrumb({
			label: row.party_name || row.party,
			axis: "party",
			party_type: row.party_type,
			selected_party: row.party,
		});
		this.render_navigator();
		this.render_breadcrumbs();
		this.refresh_summary();
	}

	navigate_gl_dimension(dimension_type, dimension_value) {
		if (!dimension_type || !dimension_value) {
			return;
		}
		if (!this.is_dimension_field_navigable(dimension_type)) {
			frappe.msgprint(__("Dimension analysis is not enabled."));
			return;
		}
		this.leave_gl_detail_for_analysis();
		this._reset_breadcrumbs([]);
		this.analysis_context.view_axis = "dimension";
		this.analysis_context.dimension_scope = {
			dimension_type,
			selected_dimension_value: dimension_value,
		};
		this.push_breadcrumb({
			label: dimension_value,
			axis: "dimension",
			dimension_type,
			selected_dimension_value: dimension_value,
		});
		this.render_navigator();
		this.render_breadcrumbs();
		this.refresh_summary();
	}

	navigate_with_target(row, route_key) {
		const payload = JSON.stringify({
			document_scope: { ...this.document_scope },
			analysis_context: {
				voucher_scope: {
					voucher_type: row.voucher_type,
					voucher_no: row.voucher_no,
				},
			},
		});
		frappe.call({
			method: `${this.api_base}.get_voucher_navigation_target`,
			args: { payload },
			callback: (r) => {
				const target = r.message || {};
				const route = target[route_key];
				const allowed =
					route_key === "gl_list_route"
						? target.can_open_gl_list
						: route_key === "print_route"
							? target.can_print
							: target.can_open_source;
				if (!allowed || (!route && route_key !== "print_route")) {
					frappe.msgprint((target.messages || []).join("<br>") || __("Navigation is not allowed."));
					return;
				}
				if (route_key === "gl_list_route") {
					frappe.route_options = route[2] || {};
					frappe.set_route(route[0], route[1]);
					return;
				}
				if (route_key === "print_route") {
					this.open_voucher_print_preview(target);
					return;
				}
				frappe.set_route(...route);
			},
		});
	}

	open_voucher_print_preview(target) {
		const print_route = target.print_route || {};
		if (!target.can_print || !print_route.doctype || !print_route.name) {
			frappe.msgprint(__("Voucher print is not available."));
			return;
		}
		let url = `/printview?doctype=${encodeURIComponent(print_route.doctype)}&name=${encodeURIComponent(print_route.name)}`;
		if (print_route.format) {
			url += `&format=${encodeURIComponent(print_route.format)}`;
		}
		window.open(frappe.urllib.get_full_url(url));
	}

	navigate_gl_list(row) {
		this.navigate_with_target(row, "gl_list_route");
	}

	navigate_source_voucher(row) {
		this.navigate_with_target(row, "source_route");
	}

	navigate_print_voucher(row) {
		if (!this.metadata?.voucher_print_format) {
			frappe.msgprint(
				__("Configure Account Explorer Voucher Print Format in Iran Accounting Settings.")
			);
			return;
		}
		this.navigate_with_target(row, "print_route");
	}

	switch_to_voucher_axis(label, breadcrumb = {}, from_drill = false) {
		if (!this.is_voucher_analysis_enabled()) {
			return false;
		}
		this.analysis_context.view_axis = "voucher";
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.sort_field = "posting_date";
		this.analysis_context.sort_order = "desc";
		this.analysis_context.page = 1;
		if (breadcrumb.selected_unified_party) {
			this.analysis_context.unified_party_scope = {
				selected_unified_party: breadcrumb.selected_unified_party,
				include_unmapped: 0,
			};
		}
		if (breadcrumb.dimension_type) {
			this.analysis_context.dimension_scope = {
				dimension_type: breadcrumb.dimension_type,
				selected_dimension_value: breadcrumb.selected_dimension_value ?? null,
			};
		}
		this.render_navigator();
		this.render_breadcrumbs();
		this.hide_member_panel();
		if (from_drill) {
			this._pending_grid_perf_operation = "drill_down";
		}
		this.refresh_summary();
		return true;
	}

	load_member_breakdown(row) {
		if (!row.unified_party) {
			return;
		}
		this.analysis_context.unified_party_scope.selected_unified_party = row.unified_party;
		const payload = this.build_payload();
		frappe.call({
			method: `${this.api_base}.get_unified_party_member_breakdown`,
			args: { payload: JSON.stringify(payload) },
			callback: (r) => {
				const data = r.message || {};
				this.render_member_panel(row, data.rows || []);
			},
		});
	}

	render_member_panel(row, members) {
		this.$member_panel.empty().show();
		const title = row.display_title || row.unified_party;
		this.$member_panel.append(
			$('<div class="ae-member-panel-header">').append(
				$("<strong>").text(__("Members of {0}", [title])),
				$('<span class="text-muted small ml-2">').text(__("{0} members", [members.length]))
			)
		);
		if (!members.length) {
			this.$member_panel.append($('<div class="ae-empty small">').text(__("No members found.")));
			return;
		}
		const $table = $('<table class="ae-grid ae-member-grid"><thead></thead><tbody></tbody></table>');
		const $head = $("<tr></tr>").appendTo($table.find("thead"));
		["party_type", "display_title", "party_identifier", "period_debit", "period_credit"].forEach((col) => {
			const labels = {
				party_type: __("Party Type"),
				display_title: __("Party"),
				party_identifier: __("Identifier"),
				period_debit: __("Debit Turnover"),
				period_credit: __("Credit Turnover"),
			};
			$("<th>").text(labels[col] || col).appendTo($head);
		});
		const $body = $table.find("tbody");
		members.forEach((member) => {
			const $tr = $("<tr>").appendTo($body);
			if (member.is_primary) {
				$tr.addClass("ae-primary-member");
			}
			["party_type", "display_title", "party_identifier"].forEach((col) => {
				$("<td>").text(member[col] ?? "").appendTo($tr);
			});
			["period_debit", "period_credit"].forEach((col) => {
				const $amount = $("<td>").addClass("amount");
				this.render_amount_cell($amount, member[col] ?? 0);
				$amount.appendTo($tr);
			});
		});
		this.$member_panel.append($table);
	}

	hide_member_panel() {
		this.$member_panel.empty().hide();
	}

	drill_row(row) {
		const axis = this.analysis_context.view_axis || "account_level";

		if (this.analysis_context.detail_mode === "grouped_gl") {
			return;
		}

		if (axis === "voucher") {
			this.open_grouped_gl_detail(row);
			return;
		}

		if (axis === "party") {
			if (row.is_virtual_group || !row.party) {
				return;
			}
			if (this.analysis_context.party_scope.selected_party) {
				this.switch_to_voucher_axis(
					row.display_title || row.party,
					{
						party_type: row.party_type,
						selected_party: row.party,
					},
					true
				);
				return;
			}
			this.analysis_context.party_scope = {
				party_type: row.party_type,
				selected_party: row.party,
			};
			this.push_breadcrumb({
				label: row.display_title || row.party,
				axis: "party",
				party_type: row.party_type,
				selected_party: row.party,
			});
			this.analysis_context.page = 1;
			this.render_breadcrumbs();
			this._refresh_after_drill();
			return;
		}

		if (axis === "unified_party") {
			if (row.is_virtual_group || !row.unified_party) {
				return;
			}
			this.analysis_context.unified_party_scope = {
				selected_unified_party: row.unified_party,
				include_unmapped: 0,
			};
			this.switch_to_voucher_axis(
				row.display_title || row.unified_party,
				{
					selected_unified_party: row.unified_party,
				},
				true
			);
			return;
		}

		if (axis === "dimension") {
			if (row.is_virtual_group || !row.drill_down_enabled) {
				return;
			}
			const dimensionType = row.dimension_type || this.analysis_context.dimension_scope.dimension_type;
			if (this.analysis_context.dimension_scope.selected_dimension_value !== null) {
				this.analysis_context.dimension_scope = {
					dimension_type: dimensionType,
					selected_dimension_value: row.dimension_value,
				};
				this.switch_to_voucher_axis(
					row.display_title || row.display_code,
					{
						dimension_type: dimensionType,
						selected_dimension_value: row.dimension_value,
					},
					true
				);
				return;
			}
			this.analysis_context.dimension_scope.selected_dimension_value = row.dimension_value;
			this.push_breadcrumb({
				label: row.display_title || row.display_code,
				axis: "dimension",
				dimension_type: dimensionType,
				selected_dimension_value: row.dimension_value,
			});
			this.analysis_context.page = 1;
			this.render_breadcrumbs();
			this._refresh_after_drill();
			return;
		}

		if (axis === "currency") {
			if (!row.currency) {
				return;
			}
			this.document_scope.currency = {
				...this.document_scope.currency,
				currency: row.currency,
			};
			this.switch_to_voucher_axis(row.currency, { currency: row.currency }, true);
			return;
		}

		if (axis !== "account_level") {
			return;
		}

		if (!row.drill_down_enabled && row.drill_down_enabled !== undefined) {
			return;
		}
		const levels = (this.metadata.levels || []).sort((a, b) => a.sequence - b.sequence);
		const current = row.level_sequence;
		const next = levels.find((lvl) => lvl.enabled && lvl.sequence > current);

		if (row.selected_account && !row.is_virtual_group) {
			this.analysis_context.account_scope = {
				mode: "account",
				selected_account: row.selected_account,
				virtual_row_key: null,
				is_virtual_group: 0,
				level_sequence: row.level_sequence,
				tree_root_account: row.selected_account,
			};
			this.push_breadcrumb({
				label: row.display_title,
				axis: "account_level",
				selected_account: row.selected_account,
				virtual_row_key: null,
				level_sequence: row.level_sequence,
			});
		} else if (row.is_virtual_group) {
			this.analysis_context.account_scope = {
				mode: "virtual_prefix",
				selected_account: null,
				virtual_row_key: row.row_key,
				is_virtual_group: 1,
				level_sequence: row.level_sequence,
				tree_root_account: this.analysis_context.account_scope.tree_root_account,
			};
			this.push_breadcrumb({
				label: row.display_title,
				axis: "account_level",
				selected_account: null,
				virtual_row_key: row.row_key,
				level_sequence: row.level_sequence,
				is_virtual_group: 1,
			});
		}

		if (!next && row.selected_account && !row.is_virtual_group && this.is_voucher_analysis_enabled()) {
			this.switch_to_voucher_axis(
				row.display_title,
				{
					selected_account: row.selected_account,
					level_sequence: row.level_sequence,
				},
				true
			);
			return;
		}

		if (next) {
			this.analysis_context.level_sequence = next.sequence;
		}
		this.analysis_context.page = 1;
		this.render_breadcrumbs();
		this._refresh_after_drill();
	}

	push_breadcrumb(chip) {
		if (!chip || chip.axis === "voucher" || chip.detail_mode === "grouped_gl") {
			return;
		}
		const key = this.get_breadcrumb_chip_key(chip);
		const trail = this.get_normalized_breadcrumb_trail();
		const last = trail[trail.length - 1];
		if (last && this.get_breadcrumb_chip_key(last) === key) {
			return;
		}
		this.breadcrumbs.push(chip);
		this._sync_store_context({ emit: false });
	}

	render_breadcrumb_segment($item, segment) {
		const $segment = $('<span class="ae-breadcrumb-segment"></span>');
		if (segment.clickable && !segment.active) {
			$segment.append(
				$('<button type="button" class="ae-breadcrumb-link">')
					.text(segment.label)
					.on("click", () => this.navigate_to_path_step(segment))
			);
		} else {
			$segment.append($('<span class="ae-breadcrumb-text">').text(segment.label));
		}
		if (segment.removable) {
			$segment.append(
				$('<button type="button" class="ae-breadcrumb-remove" aria-hidden="true">')
					.text("×")
					.attr("aria-label", this.get_scope_remove_label(segment))
					.on("click", (event) => {
						event.preventDefault();
						event.stopPropagation();
						this.remove_scope_at(segment.scope_index);
					})
			);
		}
		$item.append($segment);
	}

	render_breadcrumbs() {
		this.sync_scope_trail_from_store();
		this.$context.empty().addClass("ae-breadcrumb-bar");
		const segments = this.build_analysis_path_segments();
		const $trail = $('<nav class="ae-breadcrumb" aria-label="' + __("Analysis Path") + '"></nav>');
		const $list = $('<ol class="ae-breadcrumb-list"></ol>').appendTo($trail);

		segments.forEach((segment, index) => {
			if (index > 0) {
				$list.append($('<li class="ae-breadcrumb-sep" aria-hidden="true"><span>›</span></li>'));
			}
			const $item = $('<li class="ae-breadcrumb-item"></li>')
				.toggleClass("is-active", !!segment.active)
				.toggleClass("is-virtual", !!segment.is_virtual);
			this.render_breadcrumb_segment($item, segment);
			$list.append($item);
		});

		this.$context.append(
			$('<span class="ae-breadcrumb-heading">').text(__("Analysis Path")),
			$trail
		);
		this.update_context_actions();
	}

	restore_context_from_breadcrumbs() {
		const trail = this.get_scope_trail();
		this._reset_breadcrumbs(trail);
		if (!this.breadcrumbs.length) {
			this.navigate_to_axis_root(this.get_path_source_axis());
			return;
		}
		const last = this.breadcrumbs[this.breadcrumbs.length - 1];
		if (last.axis === "unified_party") {
			this.analysis_context.view_axis = "unified_party";
			this.analysis_context.unified_party_scope = {
				selected_unified_party: last.selected_unified_party || null,
				include_unmapped: last.include_unmapped || 0,
			};
		} else if (last.axis === "party") {
			this.analysis_context.view_axis = "party";
			this.analysis_context.party_scope = {
				party_type: last.party_type,
				selected_party: last.selected_party,
			};
		} else if (last.axis === "dimension") {
			this.analysis_context.view_axis = "dimension";
			this.analysis_context.dimension_scope.dimension_type =
				last.dimension_type || this.analysis_context.dimension_scope.dimension_type;
			this.analysis_context.dimension_scope.selected_dimension_value = last.selected_dimension_value;
		} else if (last.axis === "currency") {
			this.analysis_context.view_axis = "currency";
			if (last.currency) {
				this.document_scope.currency = {
					...this.document_scope.currency,
					currency: last.currency,
				};
			}
		} else {
			this.analysis_context.view_axis = last.axis || "account_level";
			this.analysis_context.account_scope = {
				mode: last.selected_account ? "account" : "virtual_prefix",
				selected_account: last.selected_account,
				virtual_row_key: last.virtual_row_key,
				is_virtual_group: last.is_virtual_group ? 1 : 0,
				level_sequence: last.level_sequence,
				tree_root_account: last.selected_account || this.analysis_context.account_scope.tree_root_account,
			};
			this.analysis_context.level_sequence = last.level_sequence;
		}
		this.render_navigator();
		this.render_breadcrumbs();
		this.render_detail_header();
		this.refresh_summary();
	}

	go_back() {
		if (this.analysis_context.detail_mode === "grouped_gl") {
			this.analysis_context.detail_mode = "summary";
			this.render_navigator();
			this.render_breadcrumbs();
			this.render_detail_header();
			this.refresh_summary();
			this.update_context_actions();
			return;
		}
		if (this.analysis_context.view_axis === "voucher" && this.analysis_context.voucher_scope?.voucher_no) {
			this.analysis_context.voucher_scope = {
				voucher_type: this.analysis_context.voucher_scope.voucher_type,
				voucher_no: null,
			};
			this.render_navigator();
			this.render_breadcrumbs();
			this.render_detail_header();
			this.refresh_summary();
			this.update_context_actions();
			return;
		}
		if (this.breadcrumbs.length) {
			this._reset_breadcrumbs(this.get_scope_trail().slice(0, -1));
			if (!this.breadcrumbs.length) {
				this.navigate_to_axis_root(this.get_path_source_axis());
				return;
			}
			this.restore_context_from_breadcrumbs();
		}
	}

	reset_analysis(refresh = true) {
		this._reset_breadcrumbs([]);
		this.analysis_context.view_axis = "account_level";
		this.analysis_context.account_scope = {
			mode: "tree",
			selected_account: null,
			virtual_row_key: null,
			is_virtual_group: 0,
			level_sequence: null,
			tree_root_account: null,
		};
		this.analysis_context.party_scope = {
			party_type: null,
			selected_party: null,
		};
		this.analysis_context.unified_party_scope = {
			selected_unified_party: null,
			include_unmapped: 0,
		};
		this.analysis_context.dimension_scope.selected_dimension_value = null;
		this.analysis_context.voucher_scope = {
			voucher_type: null,
			voucher_no: null,
		};
		this.analysis_context.detail_mode = "summary";
		this.analysis_context.level_sequence = this.metadata?.default_level_sequence;
		this.analysis_context.page = 1;
		this.voucher_header = null;
		this.hide_member_panel();
		this.render_navigator();
		this.render_breadcrumbs();
		this.render_detail_header();
		this._sync_store_context({ emit: true });
		if (refresh) {
			this.refresh_summary();
		}
	}

	reset_document_scope() {
		const defaults = this.metadata?.defaults || {};
		const scopeDefaults = defaults.document_scope || defaults;
		if (scopeDefaults.company) {
			this.company_field.set_value(scopeDefaults.company);
		}
		if (scopeDefaults.fiscal_year) {
			this.fy_field.set_value(scopeDefaults.fiscal_year);
		}
		this.from_date_field.set_value(scopeDefaults.from_date || "");
		this.to_date_field.set_value(scopeDefaults.to_date || "");
		this.document_scope = ae_default_document_scope({
			company: scopeDefaults.company || null,
			fiscal_year: scopeDefaults.fiscal_year || null,
			from_date: scopeDefaults.from_date || null,
			to_date: scopeDefaults.to_date || null,
			hide_zero_rows: scopeDefaults.hide_zero_rows ?? 1,
			status: { ...ae_default_document_scope().status, ...(scopeDefaults.status || {}) },
			currency: { ...ae_default_document_scope().currency, ...(scopeDefaults.currency || {}) },
		});
		this.sync_filter_controls_from_document_scope();
		this.update_advanced_filters_button();
		this.render_filter_summary();
		this.render_prompt(__("Document scope reset. Click Apply to reload."));
	}

	render_totals() {
		this.$totals.empty();
		if (!this.rows.length) {
			this.$totals.hide();
			return;
		}
		this.$totals.show().addClass("ae-totals-bar ae-totals-bar--sticky");
		const currency_label = this.currency_code || frappe.defaults.get_default("currency");
		const $inner = $('<div class="ae-totals-inner"></div>').appendTo(this.$totals);
		const $lead = $('<div class="ae-totals-lead"></div>').appendTo($inner);
		$lead.append($('<div class="ae-totals-title">').text(__("Totals")));
		$lead.append($('<div class="ae-totals-currency-wrap"></div>').append(
			$('<span class="ae-totals-currency-label">').text(__("Currency")),
			$('<span class="ae-totals-currency ae-currency-badge">').text(currency_label)
		));
		const $items = $('<div class="ae-totals-items ae-totals-kpi-row"></div>').appendTo($inner);
		let items;
		if (this.analysis_context.detail_mode === "grouped_gl") {
			items = [
				["debit", __("Debit")],
				["credit", __("Credit")],
			];
		} else if (this.analysis_context.view_axis === "voucher") {
			items = [
				["scoped_debit", __("Scoped Debit")],
				["scoped_credit", __("Scoped Credit")],
				["scoped_net", __("Scoped Net")],
			];
		} else {
			items = [
				["period_debit", __("Debit Turnover")],
				["period_credit", __("Credit Turnover")],
				["debit_balance", __("Debit Balance")],
				["credit_balance", __("Credit Balance")],
			];
		}
		items.forEach(([field, label]) => {
			const { compact, full } = this.format_display_amount(this.totals[field] || 0);
			const $value = $('<div class="ae-total-item-value amount ae-amount-compact">')
				.text(compact)
				.attr("title", full)
				.attr("aria-label", full);
			if (compact !== full) {
				$value.addClass("ae-amount-compact--abbreviated");
			}
			$items.append(
				$('<div class="ae-total-item ae-total-kpi">').append(
					$('<div class="ae-total-item-label">').text(label),
					$value
				)
			);
		});
	}

	render_warnings() {
		if (!this.warnings.length) {
			this.$warnings.empty();
			return;
		}
		this.$warnings
			.empty()
			.addClass("ae-warning-banner")
			.append(
				this.warnings.map((warning) =>
					$('<div class="ae-warning-item">').append($("<span class='ae-warning-indicator'>").text("!"), warning)
				)
			);
	}

	render_pagination() {
		this.$pagination.empty();
		const { page, total_rows, has_next } = this.pagination;
		this.$pagination.append($("<span>").text(`${__("Page")} ${page} — ${total_rows} ${__("rows")}`));
		if (page > 1) {
			this.$pagination.append(
				$('<button class="btn btn-default btn-sm ml-2">')
					.text(__("Previous"))
					.on("click", () => {
						this.clear_grid_selection();
						this.analysis_context.page = page - 1;
						this.refresh_summary();
					})
			);
		}
		if (has_next) {
			this.$pagination.append(
				$('<button class="btn btn-default btn-sm ml-2">')
					.text(__("Next"))
					.on("click", () => {
						this.clear_grid_selection();
						this.analysis_context.page = page + 1;
						this.refresh_summary();
					})
			);
		}
	}
};

$.extend(erpnext_extensions.account_explorer, {
	ae_default_document_scope,
	ae_clone_document_scope,
	ae_clear_advanced_document_scope,
	ae_count_active_document_scope_filters,
	ae_serialize_document_scope,
	ae_normalize_multi_value,
	ae_scope_value_to_control,
	ae_clone_analysis_context,
});
