frappe.provide("erpnext_extensions.account_explorer.core");

const AE_BUILTIN_AXIS_PLUGINS = [
	{
		id: "account_level",
		label: __("Account Levels"),
		scope_key: "account_scope",
		sort_field: "display_code",
	},
	{
		id: "party",
		label: __("Parties"),
		scope_key: "party_scope",
		sort_field: "party_type",
	},
	{
		id: "unified_party",
		label: __("Unified Parties"),
		scope_key: "unified_party_scope",
		sort_field: "display_title",
	},
	{
		id: "dimension",
		label: __("Dimensions"),
		scope_key: "dimension_scope",
		sort_field: "dimension_value",
	},
	{
		id: "currency",
		label: __("Currencies"),
		scope_key: null,
		sort_field: "currency",
	},
	{
		id: "voucher",
		label: __("Vouchers"),
		scope_key: "voucher_scope",
		sort_field: "posting_date",
	},
];

/**
 * Plugin registry for analysis axes. Future axes register here without
 * modifying controller navigation logic.
 */
erpnext_extensions.account_explorer.core.ExplorerPluginRegistry = class ExplorerPluginRegistry {
	constructor(events, store) {
		this.events = events;
		this.store = store;
		this._plugins = new Map();
		AE_BUILTIN_AXIS_PLUGINS.forEach((plugin) => this.register(plugin));
	}

	register(plugin) {
		if (!plugin?.id) {
			throw new Error("Account Explorer plugin requires an id");
		}
		this._plugins.set(plugin.id, { ...plugin });
		this.events?.emit("plugin:registered", { plugin: this._plugins.get(plugin.id) });
		return () => this.unregister(plugin.id);
	}

	unregister(id) {
		this._plugins.delete(id);
		this.events?.emit("plugin:unregistered", { id });
	}

	get(id) {
		return this._plugins.get(id);
	}

	list() {
		return Array.from(this._plugins.values());
	}

	/**
	 * Axes enabled in server metadata, ordered for navigator rendering.
	 */
	get_enabled_axes(metadata = {}) {
		const axes = metadata.axes || [];
		const enabled_ids = new Set(axes.filter((axis) => axis.enabled).map((axis) => axis.id));
		return this.list().filter((plugin) => enabled_ids.has(plugin.id));
	}

	activate(id, controller, options = {}) {
		const plugin = this.get(id);
		if (!plugin) {
			return;
		}
		if (typeof plugin.activate === "function") {
			plugin.activate(controller, options);
			return;
		}
		if (typeof controller?.switch_axis === "function") {
			controller.switch_axis(id, options.level_or_dimension ?? null);
		}
	}
};
