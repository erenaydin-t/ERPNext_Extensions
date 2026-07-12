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
		this.$filter_panel = $('<div class="ae-filter-panel ae-filter-panel--collapsed"></div>').appendTo(this.$container);
		this.$nav = $('<div class="ae-nav"></div>').appendTo(this.$container);
		this.$context = $('<div class="ae-context-bar"></div>').appendTo(this.$container);
		this.$detail_header = $('<div class="ae-detail-header"></div>').appendTo(this.$container);
		this.$actions = $('<div class="ae-context-actions mb-2"></div>').appendTo(this.$container);
		this.$grid = $('<div class="ae-grid-wrap"></div>').appendTo(this.$container);
		this.$member_panel = $('<div class="ae-member-panel"></div>').appendTo(this.$container).hide();
		this.$pagination = $('<div class="ae-pagination"></div>').appendTo(this.$container);
		this.$totals = $('<div class="ae-totals"></div>').appendTo(this.$container);
		this.$warnings = $('<div class="text-muted small mt-2"></div>').appendTo(this.$container);

		this.render_context_actions();
	}

	render_context_actions() {
		this.$actions.empty();
		this.$actions.append(
			$('<button class="btn btn-default btn-sm">').text(__("Back")).on("click", () => this.go_back()),
			" ",
			$('<button class="btn btn-default btn-sm">').text(__("Reset Analysis")).on("click", () => this.reset_analysis()),
			" ",
			$('<button class="btn btn-default btn-sm">')
				.text(__("Reset Document Scope"))
				.on("click", () => this.reset_document_scope())
		);
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

		this.company_field = frappe.ui.form.make_control({
			parent: this.$toolbar,
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
			parent: this.$toolbar,
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
			parent: this.$toolbar,
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
			parent: this.$toolbar,
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

		const $toolbar_actions = $('<div class="ae-toolbar-actions"></div>').appendTo(this.$toolbar);
		this.$advanced_filters_btn = $('<button type="button" class="btn btn-default btn-sm ae-advanced-filters-btn">')
			.text(__("Advanced Filters"))
			.on("click", () => this.toggle_filter_panel())
			.appendTo($toolbar_actions);
		$('<button type="button" class="btn btn-primary btn-sm">')
			.text(__("Apply"))
			.on("click", () => this.apply_scope())
			.appendTo($toolbar_actions);

		if (this.metadata.saved_views_enabled) {
			this.setup_saved_views_ui($toolbar_actions);
		}

		this.setup_filter_panel(scopeDefaults);
		this.update_advanced_filters_button();
	}

	get_scope_status_defaults() {
		const scopeDefaults = (this.metadata?.defaults || {}).document_scope || this.metadata?.defaults || {};
		return scopeDefaults.status || {};
	}

	setup_saved_views_ui($parent) {
		const $group = $('<div class="ae-saved-views-group"></div>').appendTo($parent);
		this.$saved_view_select = $('<select class="form-control input-sm ae-saved-view-select">')
			.append($("<option>").val("").text(__("Load View")))
			.on("change", () => {
				const name = this.$saved_view_select.val();
				if (name) {
					this.load_saved_view(name);
				}
			})
			.appendTo($group);
		$('<button type="button" class="btn btn-default btn-sm">')
			.text(__("Save View"))
			.on("click", () => this.prompt_save_view())
			.appendTo($group);
		this.$delete_saved_view_btn = $('<button type="button" class="btn btn-default btn-sm">')
			.text(__("Delete View"))
			.prop("disabled", true)
			.on("click", () => this.delete_active_saved_view())
			.appendTo($group);
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
				this.$saved_view_select.empty().append($("<option>").val("").text(__("Load View")));
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
						this.$delete_saved_view_btn.prop("disabled", !this.active_saved_view);
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
				this.$delete_saved_view_btn.prop("disabled", false);
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
					this.$delete_saved_view_btn.prop("disabled", true);
					if (this.$saved_view_select) {
						this.$saved_view_select.val("");
					}
					this.refresh_saved_views_list();
					frappe.show_alert(__("View deleted."));
				},
			});
		});
	}

	toggle_filter_panel(force_open = null) {
		this.filter_panel_open = force_open === null ? !this.filter_panel_open : !!force_open;
		this.$filter_panel.toggleClass("ae-filter-panel--collapsed", !this.filter_panel_open);
		if (this.filter_panel_open) {
			this.sync_filter_controls_from_document_scope();
		}
	}

	make_filter_section(title) {
		const $section = $('<div class="ae-filter-section"></div>').appendTo(this.$filter_panel);
		$('<div class="ae-filter-section-title">').text(title).appendTo($section);
		const $body = $('<div class="ae-filter-section-body"></div>').appendTo($section);
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

		const general_body = this.make_filter_section(__("General"));
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

		const voucher_body = this.make_filter_section(__("Voucher"));
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

		const accounting_body = this.make_filter_section(__("Accounting"));
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

		const dimensions_body = this.make_filter_section(__("Dimensions"));
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

		const currency_body = this.make_filter_section(__("Currency"));
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

		const status_body = this.make_filter_section(__("Status"));
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

		const $actions = $('<div class="ae-filter-panel-actions"></div>').appendTo(this.$filter_panel);
		$('<button type="button" class="btn btn-primary btn-sm">')
			.text(__("Apply"))
			.on("click", () => this.apply_scope())
			.appendTo($actions);
		$('<button type="button" class="btn btn-default btn-sm">')
			.text(__("Clear"))
			.on("click", () => this.clear_filter_panel())
			.appendTo($actions);

		this.sync_filter_controls_from_document_scope(scopeDefaults);
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
		if (!this.$advanced_filters_btn) {
			return;
		}
		const count = ae_count_active_document_scope_filters(this.document_scope);
		const label = count ? `${__("Advanced Filters")} (${count})` : __("Advanced Filters");
		this.$advanced_filters_btn.text(label);
	}

	render_filter_summary() {
		if (!this.$filter_summary) {
			this.$filter_summary = $('<div class="ae-filter-summary"></div>').insertAfter(this.$filter_panel);
		}
		this.$filter_summary.empty();
		const count = ae_count_active_document_scope_filters(this.document_scope);
		if (!count) {
			this.$filter_summary.hide();
			return;
		}
		this.$filter_summary.show().append(
			$('<span class="ae-chip">').text(`${__("Active Filters")}: ${count}`)
		);
	}

	get_account_level_nav_items() {
		return (this.metadata.levels || []).filter(
			(level) => level.enabled && level.sequence != null && level.code_length != null && !level.fieldname
		);
	}

	get_dimension_nav_items() {
		return (this.metadata.dimensions || []).filter((dimension) => dimension.fieldname);
	}

	render_navigator() {
		this.$nav.empty().show();
		const axes = this.metadata.axes || [];

		axes.forEach((axis) => {
			if (!axis.enabled) {
				return;
			}
			if (axis.id === "account_level") {
				const $group = $('<div class="ae-nav-group ae-nav-group--account-levels"></div>').appendTo(this.$nav);
				const $header = $('<div class="ae-nav-group-header"></div>').appendTo($group);
				$('<button type="button" class="btn btn-default btn-sm ae-nav-tab">')
					.text(__("Account Levels"))
					.toggleClass("active", this.analysis_context.view_axis === "account_level")
					.on("click", () => this.switch_axis("account_level"))
					.appendTo($header);
				const $menu = $('<div class="ae-nav-account-levels"></div>').appendTo($group);
				this.get_account_level_nav_items().forEach((level) => {
					$('<button type="button" class="btn btn-xs btn-link ae-nav-level">')
						.text(level.title_fa || level.title)
						.toggleClass(
							"active",
							this.analysis_context.view_axis === "account_level" &&
								this.analysis_context.level_sequence === level.sequence
						)
						.on("click", (e) => {
							e.stopPropagation();
							this.switch_axis("account_level", level.sequence);
						})
						.appendTo($menu);
				});
				return;
			}

			if (axis.id === "dimension") {
				const $group = $('<div class="ae-nav-group ae-nav-group--dimensions"></div>').appendTo(this.$nav);
				const $header = $('<div class="ae-nav-group-header"></div>').appendTo($group);
				$('<button type="button" class="btn btn-default btn-sm ae-nav-tab">')
					.text(__("Dimensions"))
					.toggleClass(
						"active",
						this.analysis_context.view_axis === "dimension" && this.analysis_context.detail_mode === "summary"
					)
					.on("click", () => this.switch_axis("dimension"))
					.appendTo($header);
				const $menu = $('<div class="ae-nav-dimension-types"></div>').appendTo($group);
				this.get_dimension_nav_items().forEach((dimension) => {
					$('<button type="button" class="btn btn-xs btn-link ae-nav-dimension-type">')
						.text(dimension.label || dimension.fieldname)
						.toggleClass(
							"active",
							this.analysis_context.view_axis === "dimension" &&
								this.analysis_context.dimension_scope.dimension_type === dimension.fieldname
						)
						.on("click", (e) => {
							e.stopPropagation();
							this.switch_axis("dimension", dimension.fieldname);
						})
						.appendTo($menu);
				});
				return;
			}

			const label_map = {
				party: __("Parties"),
				unified_party: __("Unified Parties"),
				currency: __("Currencies"),
				voucher: __("Vouchers"),
			};
			const label = label_map[axis.id] || axis.label;
			$('<button type="button" class="btn btn-default btn-sm ae-nav-tab">')
				.text(label)
				.toggleClass(
					"active",
					this.analysis_context.view_axis === axis.id && this.analysis_context.detail_mode === "summary"
				)
				.on("click", () => this.switch_axis(axis.id))
				.appendTo(this.$nav);
		});
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
		const $table = $('<table class="ae-grid"><thead></thead><tbody></tbody></table>');
		const $head = $("<tr></tr>").appendTo($table.find("thead"));
		visible.forEach((col) => {
			const cls = col.fieldtype === "Currency" ? "amount" : "";
			$("<th>").addClass(cls).text(__(col.label)).appendTo($head);
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
			visible.forEach((col) => {
				const cls = col.fieldtype === "Currency" ? "amount" : "";
				let value = row[col.id];
				const $cell = $("<td>").addClass(cls);
				if (col.fieldtype === "Currency") {
					$cell.text(
						format_currency(value ?? 0, this.currency_code || frappe.defaults.get_default("currency"))
					);
				} else {
					$cell.text(value ?? "");
				}
				$cell.appendTo($tr);
			});
			if (show_voucher_actions) {
				const $actions = $('<td class="ae-row-actions">').appendTo($tr);
				$('<button class="btn btn-xs btn-default" title="' + __("View GL") + '">')
					.text(__("GL"))
					.on("click", (e) => {
						e.stopPropagation();
						this.open_grouped_gl_detail(row);
					})
					.appendTo($actions);
				$('<button class="btn btn-xs btn-default ml-1" title="' + __("GL List") + '">')
					.text(__("List"))
					.on("click", (e) => {
						e.stopPropagation();
						this.navigate_gl_list(row);
					})
					.appendTo($actions);
				$('<button class="btn btn-xs btn-default ml-1" title="' + __("Open Voucher") + '">')
					.text(__("Open"))
					.on("click", (e) => {
						e.stopPropagation();
						this.navigate_source_voucher(row);
					})
					.appendTo($actions);
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
		$wrap.append($table);
		this.$grid.empty().append($wrap);
	}

	open_grouped_gl_detail(row) {
		this.analysis_context.voucher_scope = {
			voucher_type: row.voucher_type,
			voucher_no: row.voucher_no,
		};
		this.analysis_context.detail_mode = "grouped_gl";
		this.analysis_context.view_axis = "voucher";
		this.push_breadcrumb({
			label: row.voucher_no,
			axis: "voucher",
			voucher_type: row.voucher_type,
			voucher_no: row.voucher_no,
			detail_mode: "grouped_gl",
		});
		this.render_breadcrumbs();
		this.render_navigator();
		this.render_detail_header();
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
					route_key === "gl_list_route" ? target.can_open_gl_list : target.can_open_source;
				if (!allowed || !route) {
					frappe.msgprint((target.messages || []).join("<br>") || __("Navigation is not allowed."));
					return;
				}
				if (route_key === "gl_list_route") {
					frappe.route_options = route[2] || {};
					frappe.set_route(route[0], route[1]);
					return;
				}
				frappe.set_route(...route);
			},
		});
	}

	navigate_gl_list(row) {
		this.navigate_with_target(row, "gl_list_route");
	}

	navigate_source_voucher(row) {
		this.navigate_with_target(row, "source_route");
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
		if (label) {
			this.push_breadcrumb({ label, axis: "voucher", ...breadcrumb });
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
				$("<td>")
					.addClass("amount")
					.text(
						format_currency(
							member[col] ?? 0,
							this.currency_code || frappe.defaults.get_default("currency")
						)
					)
					.appendTo($tr);
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
		this.breadcrumbs.push(chip);
	}

	render_breadcrumbs() {
		this.$context.empty();
		if (!this.breadcrumbs.length) {
			this.$context.append(
				$('<span class="text-muted">').text(__("Analysis Path")),
				$('<span class="ae-chip">').text(__("Company scope"))
			);
			return;
		}
		this.breadcrumbs.forEach((chip, index) => {
			const $chip = $('<span class="ae-chip">')
				.toggleClass("is-virtual", !!chip.is_virtual_group)
				.text(chip.label);
			const $close = $('<button class="btn btn-xs btn-link">×</button>').on("click", (e) => {
				e.stopPropagation();
				this.breadcrumbs = this.breadcrumbs.slice(0, index);
				this.restore_context_from_breadcrumbs();
			});
			this.$context.append($chip.append($close), " / ");
		});
	}

	restore_context_from_breadcrumbs() {
		const trail = [...this.breadcrumbs];
		this.reset_analysis(false);
		this.breadcrumbs = trail;
		if (!this.breadcrumbs.length) {
			this.render_breadcrumbs();
			this.render_detail_header();
			return;
		}
		const last = this.breadcrumbs[this.breadcrumbs.length - 1];
		if (last.detail_mode === "grouped_gl") {
			this.analysis_context.view_axis = "voucher";
			this.analysis_context.detail_mode = "grouped_gl";
			this.analysis_context.voucher_scope = {
				voucher_type: last.voucher_type,
				voucher_no: last.voucher_no,
			};
		} else if (last.axis === "voucher") {
			this.analysis_context.view_axis = "voucher";
			this.analysis_context.detail_mode = "summary";
			if (last.selected_unified_party) {
				this.analysis_context.unified_party_scope = {
					selected_unified_party: last.selected_unified_party,
					include_unmapped: 0,
				};
			}
		} else if (last.axis === "unified_party") {
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
			const value = format_currency(
				this.totals[field] || 0,
				this.currency_code || frappe.defaults.get_default("currency")
			);
			this.$totals.append(
				$("<div>").html(`<strong>${label}:</strong> <span class="amount">${frappe.utils.escape_html(value)}</span>`)
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
