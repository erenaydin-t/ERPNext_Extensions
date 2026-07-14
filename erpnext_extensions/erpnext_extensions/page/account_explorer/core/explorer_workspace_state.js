frappe.provide("erpnext_extensions.account_explorer.core");

const AE_URL_STATE_KEY = "ae";
const AE_URL_MAX_LENGTH = 1800;
const AE_USER_SETTINGS_KEY = "account_explorer_workspace";

/**
 * Workspace URL state and user-settings persistence (ADR-3B-002).
 * Full restore/save is implemented in Wave 3B-2 and 3B-5.
 */
erpnext_extensions.account_explorer.core.ExplorerWorkspaceState = class ExplorerWorkspaceState {
	constructor(store, events) {
		this.store = store;
		this.events = events;
	}

	serialize_workspace_state(state = this.store?.getState()) {
		if (!state) {
			return null;
		}
		return {
			schema_version: 1,
			document_scope: state.document_scope,
			analysis_context: state.analysis_context,
			presentation: state.presentation,
			navigation: {
				breadcrumbs: state.navigation?.breadcrumbs || [],
			},
		};
	}

	deserialize_workspace_state(payload) {
		if (!payload || typeof payload !== "object") {
			return null;
		}
		return {
			document_scope: payload.document_scope,
			analysis_context: payload.analysis_context,
			presentation: payload.presentation,
			navigation: payload.navigation || { breadcrumbs: [] },
		};
	}

	encode_for_url(state) {
		const serialized = JSON.stringify(state);
		return `${AE_URL_STATE_KEY}=${encodeURIComponent(serialized)}`;
	}

	exceeds_url_limit(state) {
		return this.encode_for_url(state).length > AE_URL_MAX_LENGTH;
	}

	/**
	 * Placeholder for compact token flow (3B-2). Stores full state in user settings.
	 */
	async save_compact_token(state) {
		const token = frappe.utils.get_random(8);
		const settings = (await this._load_user_settings()) || {};
		settings.workspace_tokens = settings.workspace_tokens || {};
		settings.workspace_tokens[token] = state;
		await this._save_user_settings(settings);
		return token;
	}

	async restore_from_compact_token(token) {
		if (!token) {
			return null;
		}
		const settings = await this._load_user_settings();
		return settings?.workspace_tokens?.[token] || null;
	}

	async _load_user_settings() {
		try {
			return (await frappe.model.user_settings.get("Account Explorer")) || {};
		} catch (error) {
			console.warn("[Account Explorer] failed to load user settings", error);
			return {};
		}
	}

	async _save_user_settings(settings) {
		if (frappe.session.user === "Guest") {
			return;
		}
		await frappe.model.user_settings.update("Account Explorer", settings);
	}

	read_url_state() {
		const params = frappe.utils.get_query_params();
		if (params[AE_URL_STATE_KEY]) {
			try {
				return JSON.parse(decodeURIComponent(params[AE_URL_STATE_KEY]));
			} catch (error) {
				console.warn("[Account Explorer] invalid URL workspace state", error);
			}
		}
		if (params.ae_token) {
			return { _compact_token: params.ae_token };
		}
		return null;
	}

	apply_to_store(payload, { silent = false } = {}) {
		const restored = this.deserialize_workspace_state(payload);
		if (!restored) {
			return false;
		}
		this.store.patch(restored, { silent });
		this.events?.emit("workspace:restored", { state: restored });
		return true;
	}
};

erpnext_extensions.account_explorer.core.AE_URL_STATE_KEY = AE_URL_STATE_KEY;
erpnext_extensions.account_explorer.core.AE_USER_SETTINGS_KEY = AE_USER_SETTINGS_KEY;
