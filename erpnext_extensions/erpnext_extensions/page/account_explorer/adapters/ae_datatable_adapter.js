frappe.provide("erpnext_extensions.account_explorer.adapters");

/**
 * Single integration point for Frappe DataTable (ADR-3B-001).
 *
 * Wave 3B-0: skeleton only — do not call mount/init until Wave 3B-1.
 *
 * Planned public interface (3B-1):
 * - mount(container, columns, rows, options)
 * - update(columns, rows)
 * - destroy()
 * - get_checked_rows()
 * - get_column_state()
 * - apply_column_state(state)
 * - set_loading(is_loading)
 * - show_empty_state(message)
 *
 * Dependency direction:
 *   Account Explorer Controller → AEDataTableAdapter → Frappe DataTable
 */
erpnext_extensions.account_explorer.adapters.AEDataTableAdapter = class AEDataTableAdapter {
	constructor() {
		this._container = null;
		this._datatable = null;
		this._options = {};
		this._mounted = false;
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
		await frappe.require("frappe-datatable/dist/frappe-datatable.css");
		const module = await import("frappe-datatable");
		window.DataTable = module.default || module;
		return window.DataTable;
	}

	/** @deprecated Wave 3B-1 — use mount() */
	async init(container, options = {}) {
		return this.mount(container, options.columns || [], options.data || [], options);
	}

	/**
	 * Wave 3B-1 entry point. Not used in 3B-0.
	 */
	async mount(container, columns = [], rows = [], options = {}) {
		const DataTable = await this.ensure_datatable();
		this.destroy();
		this._container = container;
		this._options = options;
		this._datatable = new DataTable(container, this._build_options({ ...options, columns, data: rows }));
		this._mounted = true;
		return this._datatable;
	}

	_build_options(options) {
		return {
			columns: options.columns || [],
			data: options.data || [],
			language: frappe.boot?.lang,
			translations: frappe.utils.datatable?.get_translations?.(),
			checkboxColumn: options.checkboxColumn ?? false,
			inlineFilters: options.inlineFilters ?? false,
			cellHeight: options.cellHeight ?? 33,
			direction: frappe.utils.is_rtl() ? "rtl" : "ltr",
			noDataMessage: options.noDataMessage || __("No rows in the current result"),
			events: options.events || {},
			hooks: options.hooks || {},
			...options.datatable_options,
		};
	}

	update(columns, rows) {
		this.refresh({ columns, data: rows });
	}

	refresh({ columns, data } = {}) {
		if (!this._datatable) {
			return;
		}
		if (columns) {
			this._datatable.refresh(columns, data ?? this._datatable.getData());
			return;
		}
		if (data) {
			this._datatable.refresh(this._datatable.getColumns(), data);
		}
	}

	get_checked_rows() {
		return this._datatable?.getCheckedRows?.() || [];
	}

	get_column_state() {
		return this._datatable?.getColumns?.() || [];
	}

	apply_column_state(state) {
		if (!this._datatable || !state) {
			return;
		}
		this._datatable.refresh(state, this._datatable.getData());
	}

	set_loading(is_loading) {
		this._options.loading = is_loading;
	}

	show_empty_state(message) {
		this._options.noDataMessage = message || __("No rows in the current result");
	}

	get_instance() {
		return this._datatable;
	}

	destroy() {
		if (this._datatable?.destroy) {
			this._datatable.destroy();
		}
		this._datatable = null;
		this._mounted = false;
		if (this._container) {
			this._container.innerHTML = "";
		}
	}
};
