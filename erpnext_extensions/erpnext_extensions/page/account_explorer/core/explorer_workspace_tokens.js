frappe.provide("erpnext_extensions.account_explorer.core");

/**
 * Account Explorer workspace URL compact tokens (Wave 3B-3 / ADR-3B-002).
 * Soft URL length limit → User Settings Workspace.tokens + ?ae_state=<token>.
 * Preserves Grid section; only mutates Workspace.tokens.
 */

(function () {
	const core = erpnext_extensions.account_explorer.core;
	const AE_WORKSPACE_SETTINGS_SECTION = core.AE_WORKSPACE_SETTINGS_SECTION;
	const AE_WORKSPACE_TOKEN_LIMIT = core.AE_WORKSPACE_TOKEN_LIMIT;
	const codec = () => core.AEWorkspaceCodec;

	function payload_fingerprint(workspace) {
		const clean = codec().clone(workspace || {});
		delete clean._stored_at;
		return JSON.stringify(clean);
	}

	core.AEWorkspaceTokens = {
		payload_fingerprint,

		async save_compact_token(workspace) {
			// Re-read latest settings before mutate so concurrent Grid updates are preserved.
			let current = {};
			try {
				current = (await frappe.model.user_settings.get("Account Explorer")) || {};
			} catch (_error) {
				current = frappe.model.user_settings["Account Explorer"] || {};
			}
			current = $.extend(true, {}, current);
			const section = $.extend(true, {}, current[AE_WORKSPACE_SETTINGS_SECTION] || {});
			section.tokens = section.tokens || {};

			const fingerprint = payload_fingerprint(workspace);
			const existing_key = Object.keys(section.tokens).find((key) => {
				try {
					return payload_fingerprint(section.tokens[key]) === fingerprint;
				} catch (_error) {
					return false;
				}
			});
			if (existing_key) {
				return existing_key;
			}

			const token = frappe.utils.get_random(10);
			section.tokens[token] = {
				...codec().clone(workspace),
				_stored_at: frappe.datetime?.now_datetime?.() || Date.now(),
			};

			// FIFO prune by _stored_at when over AE_WORKSPACE_TOKEN_LIMIT.
			const keys = Object.keys(section.tokens);
			if (keys.length > AE_WORKSPACE_TOKEN_LIMIT) {
				keys
					.sort((a, b) =>
						String(section.tokens[a]._stored_at).localeCompare(String(section.tokens[b]._stored_at))
					)
					.slice(0, keys.length - AE_WORKSPACE_TOKEN_LIMIT)
					.forEach((old_key) => delete section.tokens[old_key]);
			}

			// Only set Workspace.tokens; leave Grid (and other sections) intact.
			current[AE_WORKSPACE_SETTINGS_SECTION] = section;
			frappe.model.user_settings["Account Explorer"] = current;
			await Promise.resolve(frappe.model.user_settings.update("Account Explorer", current));
			return token;
		},

		async restore_from_compact_token(token) {
			if (!token || frappe.session.user === "Guest") {
				return null;
			}
			try {
				const settings = (await frappe.model.user_settings.get("Account Explorer")) || {};
				frappe.model.user_settings["Account Explorer"] = settings;
				const payload = settings?.[AE_WORKSPACE_SETTINGS_SECTION]?.tokens?.[token] || null;
				if (!payload || typeof payload !== "object") {
					return null;
				}
				const clean = codec().clone(payload);
				delete clean._stored_at;
				return clean;
			} catch (error) {
				console.warn("[Account Explorer] failed to restore workspace token", error);
				return null;
			}
		},
	};
})();
