frappe.provide("erpnext_extensions.account_explorer.core");

const AE_STORE_KEYS = [
	"document_scope",
	"analysis_context",
	"presentation",
	"selection",
	"navigation",
	"loading",
];

function ae_deep_merge(target, source) {
	if (!source || typeof source !== "object") {
		return source;
	}
	if (Array.isArray(source)) {
		return source.slice();
	}
	const output = { ...target };
	Object.keys(source).forEach((key) => {
		const value = source[key];
		if (value && typeof value === "object" && !Array.isArray(value)) {
			output[key] = ae_deep_merge(output[key] || {}, value);
		} else {
			output[key] = value;
		}
	});
	return output;
}

/**
 * Single source of truth for Account Explorer workspace state.
 */
erpnext_extensions.account_explorer.core.ExplorerStore = class ExplorerStore {
	constructor(events, initial = {}) {
		this.events = events;
		this._state = this._default_state();
		this._subscribers = new Set();
		if (initial && Object.keys(initial).length) {
			this.replace(initial, { silent: true });
		}
	}

	_default_state() {
		return {
			document_scope: null,
			analysis_context: null,
			presentation: {
				schema_version: 1,
				visible_columns: [],
				sort_field: null,
				sort_order: "asc",
				page_size: 50,
				show_optional_full_voucher_columns: 0,
			},
			selection: {
				selected_row_key: null,
				checked_row_keys: [],
			},
			navigation: {
				breadcrumbs: [],
			},
			loading: {
				metadata: false,
				summary: false,
			},
		};
	}

	getState() {
		return this._state;
	}

	get(key) {
		return this._state[key];
	}

	replace(next, { silent = false } = {}) {
		const filtered = {};
		AE_STORE_KEYS.forEach((key) => {
			if (next[key] !== undefined) {
				filtered[key] = next[key];
			}
		});
		this._state = ae_deep_merge(this._default_state(), filtered);
		if (!silent) {
			this._notify({ type: "replace", patch: filtered });
		}
	}

	patch(patch, { silent = false } = {}) {
		if (!patch || typeof patch !== "object") {
			return;
		}
		const applied = {};
		AE_STORE_KEYS.forEach((key) => {
			if (patch[key] === undefined) {
				return;
			}
			if (patch[key] && typeof patch[key] === "object" && !Array.isArray(patch[key])) {
				this._state[key] = ae_deep_merge(this._state[key] || {}, patch[key]);
			} else {
				this._state[key] = patch[key];
			}
			applied[key] = this._state[key];
		});
		if (!silent && Object.keys(applied).length) {
			this._notify({ type: "patch", patch: applied });
		}
	}

	subscribe(handler) {
		this._subscribers.add(handler);
		return () => this._subscribers.delete(handler);
	}

	get_subscriber_count() {
		return this._subscribers.size;
	}

	_notify(meta) {
		const payload = { state: this._state, ...meta };
		this._subscribers.forEach((handler) => handler(payload));
		if (this.events) {
			this.events.emit("store:change", payload);
		}
	}
};
