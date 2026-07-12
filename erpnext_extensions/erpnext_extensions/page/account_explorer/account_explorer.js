frappe.provide("erpnext_extensions.account_explorer");

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

		this.document_scope = {
			company: null,
			fiscal_year: null,
			from_date: null,
			to_date: null,
			hide_zero_rows: 1,
		};

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
		this.$context = $('<div class="ae-context-bar"></div>').appendTo(this.$container);
		this.$actions = $('<div class="ae-context-actions mb-2"></div>').appendTo(this.$container);
		this.$grid = $('<div class="ae-grid-wrap"></div>').appendTo(this.$container);
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
			$('<button class="btn btn-default btn-sm">').text(__("Reset Document Scope")).on("click", () => this.reset_document_scope()),
			" ",
			$('<button class="btn btn-primary btn-sm">').text(__("Apply")).on("click", () => this.apply_scope())
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
				this.render_breadcrumbs();
			},
		});
	}

	show_disabled(message) {
		this.$disabled.text(message).show();
		this.$toolbar.hide();
	}

	setup_toolbar() {
		this.$toolbar.empty();
		const defaults = this.metadata.defaults || {};

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
		if (defaults.company) {
			this.company_field.set_value(defaults.company);
			this.document_scope.company = defaults.company;
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
		if (defaults.fiscal_year) {
			this.fy_field.set_value(defaults.fiscal_year);
			this.document_scope.fiscal_year = defaults.fiscal_year;
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

		if (defaults.from_date) {
			this.from_date_field.set_value(defaults.from_date);
			this.document_scope.from_date = defaults.from_date;
		}
		if (defaults.to_date) {
			this.to_date_field.set_value(defaults.to_date);
			this.document_scope.to_date = defaults.to_date;
		}

		this.analysis_context.level_sequence = this.metadata.default_level_sequence;
		this.analysis_context.page_size = defaults.page_size || 50;
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
			document_scope: { ...this.document_scope },
			analysis_context: {
				...this.analysis_context,
				account_scope: { ...this.analysis_context.account_scope },
			},
		};
	}

	apply_scope() {
		if (!this.document_scope.company) {
			frappe.msgprint(__("Company is required."));
			return;
		}
		if (!this.document_scope.from_date || !this.document_scope.to_date) {
			frappe.msgprint(__("From Date and To Date are required before running queries."));
			return;
		}
		this.analysis_context.page = 1;
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
			method: `${this.api_base}.get_account_summary`,
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
				this.render_grid(data.columns || []);
				this.render_totals();
				this.render_warnings();
				this.render_pagination();
			},
		});
	}

	render_prompt(message) {
		this.$grid.html(`<div class="ae-empty">${frappe.utils.escape_html(message)}</div>`);
	}

	render_grid(columns) {
		if (!this.rows.length) {
			this.render_prompt(__("No rows match the current scope."));
			return;
		}
		const visible = columns.filter((c) =>
			["display_code", "display_title", "period_debit", "period_credit", "debit_balance", "credit_balance"].includes(
				c.id
			)
		);
		const $table = $('<table class="ae-grid"><thead></thead><tbody></tbody></table>');
		const $head = $("<tr></tr>").appendTo($table.find("thead"));
		visible.forEach((col) => {
			const cls = col.fieldtype === "Currency" ? "amount" : "";
			$("<th>").addClass(cls).text(__(col.label)).appendTo($head);
		});

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
			$tr.on("dblclick", () => this.drill_row(row));
			$tr.on("click", () => {
				$body.find("tr.selected").removeClass("selected");
				$tr.addClass("selected");
			});
		});
		this.$grid.empty().append($table);
	}

	drill_row(row) {
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
				selected_account: null,
				virtual_row_key: row.row_key,
				level_sequence: row.level_sequence,
				is_virtual_group: 1,
			});
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
				$('<span class="text-muted">').text(__("Analysis Path")) ,
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
		this.reset_analysis(false);
		if (!this.breadcrumbs.length) {
			this.render_breadcrumbs();
			return;
		}
		const last = this.breadcrumbs[this.breadcrumbs.length - 1];
		this.analysis_context.account_scope = {
			mode: last.selected_account ? "account" : "virtual_prefix",
			selected_account: last.selected_account,
			virtual_row_key: last.virtual_row_key,
			is_virtual_group: last.is_virtual_group ? 1 : 0,
			level_sequence: last.level_sequence,
			tree_root_account: last.selected_account || this.analysis_context.account_scope.tree_root_account,
		};
		this.analysis_context.level_sequence = last.level_sequence;
		this.render_breadcrumbs();
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
		this.analysis_context.level_sequence = this.metadata?.default_level_sequence;
		this.analysis_context.page = 1;
		this.render_breadcrumbs();
		if (refresh) {
			this.refresh_summary();
		}
	}

	reset_document_scope() {
		const defaults = this.metadata?.defaults || {};
		if (defaults.company) {
			this.company_field.set_value(defaults.company);
		}
		if (defaults.fiscal_year) {
			this.fy_field.set_value(defaults.fiscal_year);
		}
		this.from_date_field.set_value(defaults.from_date || "");
		this.to_date_field.set_value(defaults.to_date || "");
		this.document_scope = {
			company: defaults.company || null,
			fiscal_year: defaults.fiscal_year || null,
			from_date: defaults.from_date || null,
			to_date: defaults.to_date || null,
			hide_zero_rows: 1,
		};
		this.render_prompt(__("Document scope reset. Click Apply to reload."));
	}

	render_totals() {
		this.$totals.empty();
		const items = [
			["period_debit", __("Debit Turnover")],
			["period_credit", __("Credit Turnover")],
			["debit_balance", __("Debit Balance")],
			["credit_balance", __("Credit Balance")],
		];
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
		this.$warnings.text(this.warnings.join(" | "));
	}

	render_pagination() {
		this.$pagination.empty();
		const { page, page_size, total_rows, has_next } = this.pagination;
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
