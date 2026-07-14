frappe.provide("erpnext_extensions.account_explorer.adapters");

/**
 * Single integration point for Frappe DataTable (ADR-3B-001 / Wave 3B-1).
 *
 * Public API:
 * - mount(container, columns, rows, options)
 * - update(columns, rows, options)
 * - destroy()
 * - is_mounted()
 * - get_checked_rows()
 * - clear_selection()
 * - get_column_state()
 * - apply_column_state(state)
 * - set_loading(is_loading)
 * - show_empty_state(message)
 */
erpnext_extensions.account_explorer.adapters.AEDataTableAdapter = class AEDataTableAdapter {
	constructor(events) {
		this.events = events;
		this._container = null;
		this._host = null;
		this._datatable = null;
		this._options = {};
		this._mounted = false;
		this._source_rows = [];
		this._rows_by_key = new Map();
		this._column_defs = [];
		this._delegate_namespace = ".aeDatatableAdapter";
		this._loading = false;
		this._mount_generation = 0;
		this._interaction_handlers = null;
	}

	is_mounted() {
		return this._mounted;
	}

	is_available() {
		return typeof window.DataTable === "function";
	}

	async ensure_datatable() {
		if (this.is_available()) {
			return window.DataTable;
		}
		if (frappe.DataTable) {
			window.DataTable = frappe.DataTable;
			return window.DataTable;
		}
		return new Promise((resolve, reject) => {
			frappe.require(
				[
					"/assets/frappe/node_modules/frappe-datatable/dist/frappe-datatable.css",
					"/assets/frappe/node_modules/frappe-datatable/dist/frappe-datatable.js",
				],
				() => {
					if (typeof DataTable !== "undefined") {
						window.DataTable = DataTable;
						frappe.DataTable = DataTable;
						resolve(window.DataTable);
						return;
					}
					reject(new Error("Frappe DataTable failed to load"));
				}
			);
		});
	}

	map_columns(ae_columns, options = {}) {
		const sort_field = options.sort_field;
		const sort_order = options.sort_order || "asc";
		const columns = (ae_columns || []).map((col, index) => {
			const mapped = {
				id: col.id,
				name: options.translate ? options.translate(col.label) : col.label,
				width: parseInt(col.width, 10) || 120,
				editable: false,
				focusable: false,
				sortOrder:
					sort_field === col.id ? sort_order : "none",
				format: (value, row, column) => this._format_cell(value, row, column, col, options),
			};
			if (index === 0) {
				mapped.column_class = "ae-dt-first-col";
			}
			return mapped;
		});
		if (options.actions_column) {
			columns.push({
				id: "__ae_actions",
				name: options.translate ? options.translate(__("Actions")) : __("Actions"),
				width: options.actions_column.width || 220,
				editable: false,
				focusable: false,
				sortOrder: "none",
				format: (value, row) => options.render_actions_html?.(this._resolve_source_row(row)) || "",
			});
		}
		return columns;
	}

	map_rows(source_rows, column_defs, options = {}) {
		this._source_rows = source_rows || [];
		this._rows_by_key = new Map();
		const ids = column_defs.map((col) => col.id);
		return this._source_rows.map((row) => {
			if (row?.row_key) {
				this._rows_by_key.set(row.row_key, row);
			}
			const mapped = { row_key: row?.row_key || null };
			ids.forEach((id) => {
				mapped[id] = row[id] ?? "";
			});
			if (options.actions_column) {
				mapped.__ae_actions = "";
			}
			return mapped;
		});
	}

	cancel_pending_mount() {
		this._mount_generation += 1;
	}

	_is_stale_mount(generation) {
		return generation !== this._mount_generation;
	}

	async mount(container, columns = [], rows = [], options = {}) {
		this.cancel_pending_mount();
		const generation = this._mount_generation;
		const DataTable = await this.ensure_datatable();
		if (this._is_stale_mount(generation)) {
			return null;
		}
		this._teardown_instance();
		this._container = container;
		this._options = options || {};
		this._column_defs = columns || [];
		const dt_columns = this.map_columns(this._column_defs, options);
		const dt_rows = this.map_rows(rows, dt_columns, options);
		if (this._is_stale_mount(generation)) {
			return null;
		}
		this._host = document.createElement("div");
		this._host.className = "ae-datatable-host";
		container.innerHTML = "";
		container.appendChild(this._host);
		this._datatable = new DataTable(this._host, this._build_options(dt_columns, dt_rows, options));
		if (this._is_stale_mount(generation)) {
			this._teardown_instance();
			return null;
		}
		this._mounted = true;
		this._apply_sticky_first_column();
		this._sync_loading_state();
		await this._finalize_mount(generation);
		if (this._is_stale_mount(generation)) {
			this._teardown_instance();
			return null;
		}
		this.events?.emit("grid:mounted", { columns: dt_columns, row_count: rows.length });
		return this._datatable;
	}

	async update(columns = [], rows = [], options = {}) {
		if (!this._mounted || !this._datatable || !this._container?.isConnected) {
			return this.mount(this._container, columns, rows, options);
		}
		const generation = this._mount_generation;
		this._options = { ...this._options, ...(options || {}) };
		this._column_defs = columns || [];
		const dt_columns = this.map_columns(this._column_defs, this._options);
		const dt_rows = this.map_rows(rows, dt_columns, this._options);
		if (this._is_stale_mount(generation)) {
			return null;
		}
		this._datatable.refresh(dt_rows, dt_columns);
		if (this._is_stale_mount(generation)) {
			return null;
		}
		this._apply_sticky_first_column();
		this._sync_loading_state();
		await this._finalize_mount(generation);
		if (this._is_stale_mount(generation)) {
			return null;
		}
		this.events?.emit("grid:updated", { columns: dt_columns, row_count: rows.length });
		return this._datatable;
	}

	async _await_frames(frame_count = 2) {
		for (let index = 0; index < frame_count; index += 1) {
			await new Promise((resolve) => requestAnimationFrame(resolve));
		}
	}

	async _finalize_mount(generation) {
		await this._await_frames(2);
		if (this._is_stale_mount(generation)) {
			return false;
		}
		this._sync_row_dom_keys();
		await this._await_frames(1);
		if (this._is_stale_mount(generation)) {
			return false;
		}
		this._sync_row_dom_keys();
		return this.is_interaction_ready();
	}

	is_interaction_ready() {
		if (!this._mounted || !this._host) {
			return false;
		}
		const rows = this._host.querySelectorAll(".dt-row:not(.dt-row-header):not(.dt-row-filter)");
		if (!rows.length) {
			return !this._source_rows.length;
		}
		return [...rows].every((row) => row.getAttribute("data-ae-row-key"));
	}

	_build_options(columns, rows, options) {
		const adapter = this;
		return {
			columns,
			data: rows,
			language: frappe.boot?.lang,
			translations: frappe.utils.datatable?.get_translations?.(),
			checkboxColumn: options.checkbox_column ?? true,
			serialNoColumn: false,
			inlineFilters: options.inline_filters ?? true,
			layout: "fixed",
			cellHeight: options.cell_height ?? 33,
			clusterize: options.clusterize ?? false,
			disableReorderColumn: false,
			direction: frappe.utils.is_rtl() ? "rtl" : "ltr",
			noDataMessage: options.empty_message || __("No rows in the current result"),
			events: {
				onCheckRow: () => adapter._emit_selection_change(),
				onSortColumn: (column) => {
					if (!column?.id || column.id.startsWith("__")) {
						return;
					}
					options.on_server_sort?.(column.id, column);
				},
				onRemoveColumn: (column) => {
					options.on_column_removed?.(column);
					adapter.events?.emit("grid:column_state_changed", {
						columns: adapter.get_column_state(),
					});
				},
				onSwitchColumn: (column1, column2) => {
					options.on_column_switched?.(column1, column2);
					adapter.events?.emit("grid:column_state_changed", {
						columns: adapter.get_column_state(),
					});
				},
			},
		};
	}

	_format_cell(value, row, column, source_col, options) {
		const source_row = this._resolve_source_row(row);
		if (column.id === "__ae_actions") {
			return options.render_actions_html?.(source_row) || "";
		}
		if (source_col?.fieldtype === "Currency") {
			const formatted = options.format_amount?.(value, source_row, source_col) || {
				compact: value ?? "",
				full: value ?? "",
			};
			const compact = frappe.utils.escape_html(String(formatted.compact ?? ""));
			const full = frappe.utils.escape_html(String(formatted.full ?? compact));
			return `<span class="ae-amount-compact" title="${full}" aria-label="${full}">${compact}</span>`;
		}
		const display = value ?? "";
		const col_index = this._column_defs.findIndex((col) => col.id === source_col.id);
		const drillable =
			col_index === 0 &&
			source_row &&
			source_row.drill_down_enabled !== 0 &&
			source_row.drill_down_enabled !== false;
		if (drillable) {
			const label = frappe.utils.escape_html(String(display));
			return `<span class="ae-drill-cell"><span class="ae-drill-icon" aria-hidden="true">›</span><span class="ae-drill-label">${label}</span></span>`;
		}
		return frappe.utils.escape_html(String(display));
	}

	_resolve_source_row(row) {
		if (!row) {
			return null;
		}
		if (row.row_key && this._rows_by_key.has(row.row_key)) {
			return this._rows_by_key.get(row.row_key);
		}
		const row_index = row.meta?.rowIndex;
		if (row_index !== undefined && this._source_rows[row_index]) {
			return this._source_rows[row_index];
		}
		if (row.row_key) {
			return this._source_rows.find((item) => item.row_key === row.row_key) || null;
		}
		return null;
	}

	resolve_source_row_by_key(row_key) {
		if (!row_key) {
			return null;
		}
		return this._rows_by_key.get(row_key) || this._source_rows.find((item) => item.row_key === row_key) || null;
	}

	is_interactive_grid_target(target) {
		if (!target?.closest) {
			return true;
		}
		const element = target.nodeType === Node.ELEMENT_NODE ? target : target.parentElement;
		if (!element) {
			return true;
		}
		return !!element.closest(
			[
				"button",
				"a[href]",
				"input",
				"select",
				"textarea",
				"label",
				'[type="checkbox"]',
				".dt-cell__checkbox",
				".ae-voucher-action",
				".dt-row-filter",
				".dt-row-header",
				".dt-cell__resize-handle",
				".dt-cell--dragging",
				".dt-dropdown",
				".dt-cell__edit",
				".dt-scrollable__cursor",
			].join(", ")
		);
	}

	resolve_row_from_event(event) {
		const row_element = event?.target?.closest?.(
			".dt-row:not(.dt-row-header):not(.dt-row-filter)"
		);
		if (!row_element || !this._host?.contains(row_element)) {
			return null;
		}
		const row_key = row_element.getAttribute("data-ae-row-key");
		if (row_key) {
			return this.resolve_source_row_by_key(row_key);
		}
		const row_index = Number(row_element.getAttribute("data-row-index"));
		if (!Number.isNaN(row_index) && this._source_rows[row_index]) {
			return this._source_rows[row_index];
		}
		return this._resolve_source_row({ meta: { rowIndex: row_index } });
	}

	_sync_row_dom_keys() {
		if (!this._host || !this._datatable) {
			return;
		}
		const apply_keys = () => {
			if (!this._host || !this._datatable) {
				return;
			}
			const dom_rows = this._host.querySelectorAll(".dt-row:not(.dt-row-header):not(.dt-row-filter)");
			const visible_indices = this._datatable.bodyRenderer?.visibleRowIndices;
			if (visible_indices?.length === dom_rows.length) {
				dom_rows.forEach((element, index) => {
					const source_row = this._source_rows[visible_indices[index]];
					if (source_row?.row_key && element.getAttribute("data-ae-row-key") !== source_row.row_key) {
						element.setAttribute("data-ae-row-key", source_row.row_key);
					}
					this._apply_row_drillable_class(element, source_row);
				});
				return;
			}
			dom_rows.forEach((element) => {
				const row_index = Number(element.getAttribute("data-row-index"));
				const source_row = Number.isNaN(row_index) ? null : this._source_rows[row_index];
				if (source_row?.row_key && element.getAttribute("data-ae-row-key") !== source_row.row_key) {
					element.setAttribute("data-ae-row-key", source_row.row_key);
				}
				this._apply_row_drillable_class(element, source_row);
			});
		};
		apply_keys();
	}

	_apply_row_drillable_class(element, source_row) {
		if (!element) {
			return;
		}
		const drillable =
			source_row &&
			source_row.drill_down_enabled !== 0 &&
			source_row.drill_down_enabled !== false;
		element.classList.toggle("ae-grid-row--drillable", !!drillable);
		if (drillable) {
			element.setAttribute("title", __("Click to select · Double-click to drill down"));
		} else {
			element.removeAttribute("title");
		}
	}

	_apply_sticky_first_column() {
		if (!this._datatable?.setColumnSticky) {
			return;
		}
		const offset = this._options.checkbox_column === false ? 0 : 1;
		try {
			this._datatable.setColumnSticky(offset, true);
		} catch (error) {
			console.warn("[Account Explorer] unable to sticky first summary column", error);
		}
	}

	_emit_selection_change() {
		const checked = this.get_checked_rows();
		this._options.on_selection_change?.(checked);
		this.events?.emit("grid:selection_changed", { checked_rows: checked });
	}

	get_checked_rows() {
		const indices = this._datatable?.rowmanager?.getCheckedRows?.() || [];
		return indices
			.map((index) => this._source_rows[Number(index)])
			.filter(Boolean)
			.map((row) => (row.row_key ? this.resolve_source_row_by_key(row.row_key) || row : row));
	}

	clear_selection() {
		if (!this._datatable?.datamanager?.rows) {
			return;
		}
		this._datatable.datamanager.rows.forEach((row) => {
			if (row[0]?.content) {
				row[0].content = this._datatable.datamanager.getCheckboxHTML();
			}
		});
		this._datatable.rowmanager?.refreshRows?.();
		this._emit_selection_change();
	}

	get_column_state() {
		return (this._datatable?.getColumns?.() || []).map((col) => ({
			id: col.id,
			name: col.name,
			width: col.width,
			sortOrder: col.sortOrder,
		}));
	}

	apply_column_state(state) {
		if (!this._datatable || !state?.length) {
			return;
		}
		this._datatable.refresh(this._datatable.getColumns(), this._datatable.getData());
		this.events?.emit("grid:column_state_changed", { columns: this.get_column_state() });
	}

	set_loading(is_loading) {
		this._loading = !!is_loading;
		this._sync_loading_state();
	}

	show_empty_state(message) {
		this._options.empty_message = message || __("No rows in the current result");
		if (this._datatable?.options) {
			this._datatable.options.noDataMessage = this._options.empty_message;
		}
	}

	_sync_loading_state() {
		if (!this._host) {
			return;
		}
		this._host.classList.toggle("ae-datatable-host--loading", this._loading);
	}

	get_instance() {
		return this._datatable;
	}

	_teardown_instance() {
		if (this._container) {
			$(this._container).off(this._delegate_namespace);
		}
		if (this._datatable?.destroy) {
			this._datatable.destroy();
		}
		this._datatable = null;
		this._mounted = false;
		this._source_rows = [];
		this._rows_by_key = new Map();
		this._column_defs = [];
		if (this._container) {
			this._container.innerHTML = "";
		}
		this._host = null;
	}

	destroy() {
		this.cancel_pending_mount();
		const was_mounted = this._mounted;
		this._teardown_instance();
		if (was_mounted) {
			this.events?.emit("grid:destroyed");
		}
	}
};
