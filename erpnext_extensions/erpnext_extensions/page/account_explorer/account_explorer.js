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

function ae_format_compact_amount(value, currency_code) {
	const num = flt(value);
	const full = format_currency(num, currency_code);
	const abs = Math.abs(num);
	if (abs >= 1000000000) {
		return {
			compact: `${ae_trim_compact_decimals((num / 1000000000).toFixed(1))} B`,
			full,
		};
	}
	if (abs >= 1000000) {
		return {
			compact: `${ae_trim_compact_decimals((num / 1000000).toFixed(1))} M`,
			full,
		};
	}
	if (abs >= 1000) {
		return {
			compact: `${ae_trim_compact_decimals((num / 1000).toFixed(2))} K`,
			full,
		};
	}
	return { compact: full, full };
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
		this.show_optional_full_voucher_columns = false;
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
		this.setup_actions();
		this.render_shell();
		this.load_metadata();
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
		this.$grid = $('<div class="ae-grid-wrap"></div>').appendTo(this.$container);
		this.$member_panel = $('<div class="ae-member-panel"></div>').appendTo(this.$container).hide();
		this.$totals = $('<div class="ae-totals"></div>').appendTo(this.$container);
		this.$pagination = $('<div class="ae-pagination"></div>').appendTo(this.$container);
		this.$warnings = $('<div class="text-muted small mt-2"></div>').appendTo(this.$container);
	}

	update_context_actions() {
		const has_voucher_drill =
			this.analysis_context.view_axis === "voucher" &&
			(this.analysis_context.detail_mode === "grouped_gl" ||
				this.analysis_context.voucher_scope?.voucher_no);
		if (this.$back_btn) {
			this.$back_btn.toggle(!!this.breadcrumbs?.length || has_voucher_drill);
		}
	}

	load_metadata() {
		frappe.call({
			method: `${this.api_base}.get_account_explorer_metadata`,
			callback: (r) => {
				this.metadata = r.message || {};
				if (!this.metadata.enabled) {
					this.show_disabled(
						__("Account Explorer is not enabled. Open Iran Accounting Settings to configure and enable it.")
					);
					return;
				}
				this.$disabled.hide();
				this.setup_toolbar();
				this.render_navigator();
				this.render_breadcrumbs();
				if (this.metadata.saved_views_enabled) {
					this.refresh_saved_views_list();
				}
			},
		});
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
		this.analysis_context.page_size = defaults.page_size || 50;
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
			visible_columns: this.get_default_visible_columns(),
			sort_field: this.analysis_context.sort_field,
			sort_order: this.analysis_context.sort_order,
			page_size: this.analysis_context.page_size,
			show_optional_full_voucher_columns: this.show_optional_full_voucher_columns ? 1 : 0,
		};
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

		this.breadcrumbs = [];
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
		return ae_format_compact_amount(
			value ?? 0,
			this.currency_code || frappe.defaults.get_default("currency")
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
				clickable: true,
			},
		];
		const trail = this.get_normalized_breadcrumb_trail();

		trail.forEach((chip, index) => {
			segments.push({
				step: `crumb:${index}`,
				label: chip.label,
				kind: "crumb",
				crumb_index: index,
				is_virtual: !!chip.is_virtual_group,
				clickable: true,
			});
		});

		if (this.analysis_context.view_axis === "voucher") {
			const voucher_scope = this.analysis_context.voucher_scope || {};
			const has_type = !!voucher_scope.voucher_type;
			const has_no = !!voucher_scope.voucher_no;
			const is_gl = this.analysis_context.detail_mode === "grouped_gl";

			segments.push({
				step: "voucher_axis",
				label: __("Voucher"),
				kind: "axis",
				clickable: has_type || has_no || is_gl,
			});

			if (has_type) {
				segments.push({
					step: "voucher_type",
					label: voucher_scope.voucher_type,
					kind: "voucher_meta",
					clickable: has_no || is_gl,
				});
			}
			if (has_no) {
				segments.push({
					step: "voucher_no",
					label: voucher_scope.voucher_no,
					kind: "voucher_meta",
					clickable: is_gl,
				});
			}
			if (is_gl) {
				segments.push({
					step: "gl_detail",
					label: __("GL Detail"),
					kind: "detail",
					active: true,
				});
			} else {
				segments[segments.length - 1].active = true;
			}
			return segments;
		}

		if (!trail.length) {
			segments.push({
				step: "view",
				label: this.get_current_view_path_label(),
				kind: "view",
				active: true,
			});
			return segments;
		}

		segments.push({
			step: "view",
			label: this.get_axis_path_label(this.analysis_context.view_axis),
			kind: "view",
			active: true,
		});
		return segments;
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
			return;
		}
		if (segment.step && segment.step.startsWith("crumb:")) {
			const trail = this.get_normalized_breadcrumb_trail();
			this.breadcrumbs = trail.slice(0, segment.crumb_index + 1);
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
		this.render_navigator();
		this.render_detail_header();
		if (this.document_scope.from_date && this.document_scope.to_date) {
			this.refresh_summary();
		}
	}

	is_voucher_analysis_enabled() {
		return !!(this.metadata && this.metadata.voucher_analysis_enabled);
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
		this.update_advanced_filters_button();
		this.render_filter_summary();
		this.refresh_summary();
	}

	refresh_summary() {
		if (!this.metadata || !this.metadata.enabled) {
			return;
		}
		if (!this.document_scope.company || !this.document_scope.from_date || !this.document_scope.to_date) {
			this.render_prompt(__("Select Company and date range, then click Apply."));
			return;
		}

		frappe.call({
			method: this.get_summary_method(),
			args: { payload: JSON.stringify(this.build_payload()) },
			freeze: true,
			freeze_message: __("Loading..."),
			callback: (r) => {
				const data = r.message || {};
				this.rows = data.rows || [];
				this.totals = data.totals || {};
				this.currency_code = data.currency?.code || this.currency_code;
				this.pagination = data.pagination || this.pagination;
				this.warnings = data.warnings || [];
				this.voucher_header = data.voucher_header || null;
				this.render_detail_header();
				this.render_grid(data.columns || []);
				this.render_totals();
				this.render_warnings();
				this.render_pagination();
				if (this.analysis_context.view_axis !== "unified_party") {
					this.hide_member_panel();
				}
			},
		});
	}

	get_default_visible_columns() {
		if (this.analysis_context.detail_mode === "grouped_gl") {
			const cols = ["account", "account_name", "party_type", "party_name", "debit", "credit", "against"];
			if (this.analysis_context.dimension_scope.dimension_type) {
				cols.splice(4, 0, "dimension_value");
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
		this.$detail_header.empty();
		if (this.analysis_context.detail_mode !== "grouped_gl") {
			this.$detail_header.hide();
			return;
		}
		this.$detail_header.show();
		const header = this.voucher_header || this.analysis_context.voucher_scope || {};
		const title = header.voucher_title || header.voucher_no || "";
		this.$detail_header.append(
			$('<button class="btn btn-default btn-sm ae-back-vouchers">')
				.text(__("Back to Vouchers"))
				.on("click", () => this.back_to_voucher_summary()),
			" ",
			$("<span>").text(
				`${header.voucher_type || ""} ${header.voucher_no || ""}${title ? ` — ${title}` : ""}`
			)
		);
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

	render_grid(columns) {
		if (!this.rows.length) {
			this.render_prompt(__("No rows match the current scope."));
			return;
		}
		const allowed = new Set(this.get_default_visible_columns());
		const visible = columns.filter((c) => allowed.has(c.id));
		const show_voucher_actions =
			this.analysis_context.view_axis === "voucher" && this.analysis_context.detail_mode === "summary";
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
				const action_specs = [
					{
						key: "gl",
						label: __("GL"),
						title: __("Grouped GL detail in Account Explorer"),
						handler: () => this.open_grouped_gl_detail(row),
					},
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
					},
				];
				if (this.metadata?.voucher_print_format) {
					action_specs.push({
						key: "print",
						label: __("Print"),
						title: __("Print voucher using configured format"),
						handler: () => this.navigate_print_voucher(row),
					});
				}
				action_specs.forEach((spec, index) => {
					if (index > 0) {
						$actions.append($('<span class="ae-voucher-action-sep" aria-hidden="true">|</span>'));
					}
					$('<button type="button" class="btn btn-xs btn-default ae-voucher-action">')
						.addClass(`ae-voucher-action--${spec.key}`)
						.text(spec.label)
						.attr("title", spec.title)
						.on("click", (e) => {
							e.stopPropagation();
							spec.handler();
						})
						.appendTo($actions);
				});
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

		const $wrap = $('<div class="ae-grid-container"></div>');
		if (this.analysis_context.view_axis === "voucher" && this.analysis_context.detail_mode === "summary") {
			$wrap.append(
				$('<div class="ae-grid-options mb-2">').append(
					$('<label class="small text-muted">').append(
						$("<input type='checkbox'>")
							.prop("checked", this.show_optional_full_voucher_columns)
							.on("change", (e) => {
								this.show_optional_full_voucher_columns = e.target.checked;
								this.render_grid(columns);
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
		$wrap.append($meta);
		$wrap.append($('<div class="ae-grid-scroll"></div>').append($table));
		this.$grid.empty().append($wrap);
	}

	open_grouped_gl_detail(row) {
		this.analysis_context.voucher_scope = {
			voucher_type: row.voucher_type,
			voucher_no: row.voucher_no,
		};
		this.analysis_context.detail_mode = "grouped_gl";
		this.analysis_context.view_axis = "voucher";
		this.render_breadcrumbs();
		this.render_navigator();
		this.render_detail_header();
		this.refresh_summary();
		this.update_context_actions();
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

	switch_to_voucher_axis(label, breadcrumb = {}) {
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
				this.switch_to_voucher_axis(row.display_title || row.party, {
					party_type: row.party_type,
					selected_party: row.party,
				});
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
			this.refresh_summary();
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
			this.switch_to_voucher_axis(row.display_title || row.unified_party, {
				selected_unified_party: row.unified_party,
			});
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
				this.switch_to_voucher_axis(row.display_title || row.display_code, {
					dimension_type: dimensionType,
					selected_dimension_value: row.dimension_value,
				});
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
			this.refresh_summary();
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
			this.switch_to_voucher_axis(row.currency, { currency: row.currency });
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
			this.switch_to_voucher_axis(row.display_title, {
				selected_account: row.selected_account,
				level_sequence: row.level_sequence,
			});
			return;
		}

		if (next) {
			this.analysis_context.level_sequence = next.sequence;
		}
		this.analysis_context.page = 1;
		this.render_breadcrumbs();
		this.refresh_summary();
	}

	push_breadcrumb(chip) {
		if (!chip || chip.axis === "voucher" || chip.detail_mode === "grouped_gl") {
			return;
		}
		const key = this.get_breadcrumb_chip_key(chip);
		const last = this.breadcrumbs[this.breadcrumbs.length - 1];
		if (last && this.get_breadcrumb_chip_key(last) === key) {
			return;
		}
		this.breadcrumbs.push(chip);
	}

	render_breadcrumbs() {
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
			if (segment.clickable && !segment.active) {
				$item.append(
					$('<button type="button" class="ae-breadcrumb-link">')
						.text(segment.label)
						.on("click", () => this.navigate_to_path_step(segment))
				);
			} else {
				$item.append($('<span class="ae-breadcrumb-text">').text(segment.label));
			}
			$list.append($item);
		});

		this.$context.append(
			$('<span class="ae-breadcrumb-heading">').text(__("Analysis Path")),
			$trail
		);
		this.update_context_actions();
	}

	restore_context_from_breadcrumbs() {
		const trail = this.get_normalized_breadcrumb_trail();
		this.reset_analysis(false);
		this.breadcrumbs = trail;
		if (!this.breadcrumbs.length) {
			this.render_breadcrumbs();
			this.render_detail_header();
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
			this.analysis_context.view_axis = "account_level";
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
			this.breadcrumbs.pop();
			this.restore_context_from_breadcrumbs();
		}
	}

	reset_analysis(refresh = true) {
		this.breadcrumbs = [];
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
		this.render_breadcrumbs();
		this.render_detail_header();
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
		this.$totals.show().addClass("ae-totals-bar");
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
