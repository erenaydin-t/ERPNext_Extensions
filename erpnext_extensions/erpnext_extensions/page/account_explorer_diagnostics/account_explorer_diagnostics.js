frappe.provide("erpnext_extensions.account_explorer_diagnostics");

frappe.pages["account-explorer-diagnostics"].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __("Account Explorer Diagnostics"),
		single_column: true,
	});
	page.main.addClass("account-explorer-diagnostics-page");
	erpnext_extensions.account_explorer_diagnostics = new AccountExplorerDiagnosticsPage(page);
};

class AccountExplorerDiagnosticsPage {
	constructor(page) {
		this.page = page;
		this.api_base = "erpnext_extensions.iran_accounting.account_explorer";
		this.$container = $(page.body);
		this.diagnostics = null;
		this.benchmark = null;
		this.render_shell();
		this.load_metadata();
	}

	render_shell() {
		this.$container.empty();
		this.$toolbar = $('<div class="aed-toolbar"></div>').appendTo(this.$container);
		this.$summary = $('<div class="aed-summary"></div>').appendTo(this.$container);
		this.$diagnostics_panel = $('<div class="aed-panel"></div>').appendTo(this.$container);
		this.$benchmark_panel = $('<div class="aed-panel"></div>').appendTo(this.$container);
	}

	load_metadata() {
		frappe.call({
			method: `${this.api_base}.get_account_explorer_metadata`,
			callback: (r) => {
				this.metadata = r.message || {};
				if (!this.metadata.enabled) {
					this.render_disabled(__("Account Explorer is disabled."));
					return;
				}
				if (!this.metadata.diagnostics_enabled) {
					this.render_disabled(__("Diagnostics are disabled in Iran Accounting Settings."));
					return;
				}
				this.setup_controls();
				this.render_prompt(__("Select a company and run diagnostics."));
			},
		});
	}

	setup_controls() {
		this.$toolbar.empty();
		const defaults = (this.metadata.defaults || {}).document_scope || {};
		const $actions = $('<div class="aed-toolbar-actions"></div>').appendTo(this.$toolbar);

		this.company_field = frappe.ui.form.make_control({
			parent: this.$toolbar,
			df: {
				fieldtype: "Link",
				options: "Company",
				label: __("Company"),
				reqd: 1,
				default: defaults.company,
				change: () => this.sync_fiscal_defaults(),
			},
			render_input: true,
		});

		this.fy_field = frappe.ui.form.make_control({
			parent: this.$toolbar,
			df: {
				fieldtype: "Link",
				options: "Fiscal Year",
				label: __("Fiscal Year"),
				default: defaults.fiscal_year,
			},
			render_input: true,
		});

		$('<button type="button" class="btn btn-primary btn-sm">')
			.text(__("Run Diagnostics"))
			.on("click", () => this.run_diagnostics())
			.appendTo($actions);

		$('<button type="button" class="btn btn-default btn-sm">')
			.text(__("Run Performance Benchmark"))
			.on("click", () => this.run_benchmark())
			.appendTo($actions);
	}

	sync_fiscal_defaults() {
		const company = this.company_field.get_value();
		if (!company) {
			return;
		}
		frappe.call({
			method: "erpnext.accounts.utils.get_fiscal_year",
			args: { company, date: frappe.datetime.get_today() },
			callback: (r) => {
				if (!r.message) {
					return;
				}
				this.fy_field.set_value(r.message[0]);
			},
		});
	}

	run_diagnostics() {
		const company = this.company_field.get_value();
		if (!company) {
			frappe.msgprint(__("Company is required."));
			return;
		}
		frappe.call({
			method: `${this.api_base}.get_account_explorer_diagnostics`,
			args: { company },
			freeze: true,
			freeze_message: __("Running diagnostics..."),
			callback: (r) => {
				this.diagnostics = r.message || null;
				this.render_diagnostics();
			},
		});
	}

	run_benchmark() {
		const company = this.company_field.get_value();
		const fiscal_year = this.fy_field.get_value();
		if (!company || !fiscal_year) {
			frappe.msgprint(__("Company and Fiscal Year are required for benchmarking."));
			return;
		}
		frappe.call({
			method: "erpnext.accounts.utils.get_fiscal_year",
			args: { company, fiscal_year },
			callback: (fy) => {
				const message = fy.message;
				if (!message) {
					frappe.msgprint(__("Unable to resolve fiscal year dates."));
					return;
				}
				frappe.call({
					method: `${this.api_base}.run_account_explorer_performance_benchmark`,
					args: {
						company,
						fiscal_year,
						from_date: message[1],
						to_date: message[2],
					},
					freeze: true,
					freeze_message: __("Running benchmark..."),
					callback: (r) => {
						this.benchmark = r.message || null;
						this.render_benchmark();
					},
				});
			},
		});
	}

	render_disabled(message) {
		this.$toolbar.empty();
		this.$summary.empty();
		this.$diagnostics_panel.empty();
		this.$benchmark_panel.empty();
		$('<div class="aed-disabled"></div>').text(message).appendTo(this.$container);
	}

	render_prompt(message) {
		this.$summary.empty();
		this.$diagnostics_panel.empty().append($('<div class="aed-empty"></div>').text(message));
		this.$benchmark_panel.empty();
	}

	render_diagnostics() {
		const data = this.diagnostics || {};
		const findings = data.findings || [];
		this.$summary.empty();
		const summary = data.summary || {};
		this._append_summary_chip(__("Errors"), summary.error || 0, "error");
		this._append_summary_chip(__("Warnings"), summary.warning || 0, "warning");
		this._append_summary_chip(__("Checks Passed"), summary.info || 0, "info");

		this.$diagnostics_panel.empty();
		$('<div class="aed-panel-title"></div>').text(__("Configuration Diagnostics")).appendTo(this.$diagnostics_panel);
		const $table = $('<table class="aed-grid"></table>').appendTo(this.$diagnostics_panel);
		$("<thead><tr><th>Category</th><th>Check</th><th>Severity</th><th>Count</th><th>Message</th></tr></thead>").appendTo(
			$table
		);
		const $body = $("<tbody></tbody>").appendTo($table);
		findings.forEach((row) => {
			const severity_class = `aed-severity-${row.severity || "info"}`;
			$("<tr></tr>")
				.append($("<td></td>").text(__(row.category)))
				.append($("<td></td>").text(row.title || row.check_id))
				.append($("<td></td>").addClass(severity_class).text(row.severity))
				.append($("<td></td>").text(cint(row.count)))
				.append($("<td></td>").text(row.message))
				.appendTo($body);
		});
	}

	render_benchmark() {
		const data = this.benchmark || {};
		this.$benchmark_panel.empty();
		$('<div class="aed-panel-title"></div>')
			.text(__("Performance Benchmark (Documentation Only)"))
			.appendTo(this.$benchmark_panel);
		$("<p></p>")
			.text(
				data.note ||
					__("Benchmark results are observational. No database indexes are created automatically.")
			)
			.appendTo(this.$benchmark_panel);
		$("<p></p>")
			.text(__("GL Entry rows: {0}", [cint(data.gl_row_count)]))
			.appendTo(this.$benchmark_panel);

		const $table = $('<table class="aed-grid"></table>').appendTo(this.$benchmark_panel);
		$(
			"<thead><tr><th>Target GL Rows</th><th>Scenario</th><th>Elapsed (ms)</th><th>Result Rows</th><th>Scale Reached</th></tr></thead>"
		).appendTo($table);
		const $body = $("<tbody></tbody>").appendTo($table);
		(data.measurements || []).forEach((row) => {
			if (row.skipped) {
				return;
			}
			$("<tr></tr>")
				.append($("<td></td>").text(format_number(row.target_gl_rows)))
				.append($("<td></td>").text(row.scenario))
				.append($("<td></td>").text(row.elapsed_ms))
				.append($("<td></td>").text(cint(row.result_row_count)))
				.append($("<td></td>").text(row.scale_reached ? __("Yes") : __("No")))
				.appendTo($body);
		});

		const recommendations = data.index_recommendations || [];
		if (recommendations.length) {
			$('<div class="aed-panel-title"></div>').text(__("Index Recommendations")).appendTo(this.$benchmark_panel);
			const $rec_table = $('<table class="aed-grid"></table>').appendTo(this.$benchmark_panel);
			$("<thead><tr><th>Table</th><th>Columns</th><th>Status</th><th>Reason</th></tr></thead>").appendTo(
				$rec_table
			);
			const $rec_body = $("<tbody></tbody>").appendTo($rec_table);
			recommendations.forEach((row) => {
				$("<tr></tr>")
					.append($("<td></td>").text(row.table))
					.append($("<td></td>").text((row.columns || []).join(", ")))
					.append($("<td></td>").text(row.status))
					.append($("<td></td>").text(row.reason))
					.appendTo($rec_body);
			});
		}
	}

	_append_summary_chip(label, count, kind) {
		$('<div class="aed-summary-chip"></div>')
			.addClass(kind === "error" && count ? "is-error" : kind === "warning" && count ? "is-warning" : "")
			.text(`${label}: ${count}`)
			.appendTo(this.$summary);
	}
}
