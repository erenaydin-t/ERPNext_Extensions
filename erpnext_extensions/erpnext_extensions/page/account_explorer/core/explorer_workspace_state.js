frappe.provide("erpnext_extensions.account_explorer.core");

/**
 * Account Explorer workspace URL orchestration (Wave 3B-3 / ADR-3B-002 + ADR-3B-004).
 * Hydration, history, scheduling. Codec/tokens live in sibling modules.
 */

const ae_ws_core = erpnext_extensions.account_explorer.core;
const ae_ws_codec = () => ae_ws_core.AEWorkspaceCodec;
const ae_ws_tokens = () => ae_ws_core.AEWorkspaceTokens;

erpnext_extensions.account_explorer.core.ExplorerWorkspaceState = class ExplorerWorkspaceState {
	constructor(store, events) {
		this.store = store;
		this.events = events;
		this.controller = null;
		this._hydrating = false;
		this._updating_url = false;
		this._url_timer = null;
		this._generation = 0;
		this._warnings = [];
		this._last_url_signature = null;
		this._on_popstate = null;
		this._pending_push = false;
	}

	destroy() {
		this._clear_url_timer();
		if (this._on_popstate && typeof window !== "undefined") {
			window.removeEventListener("popstate", this._on_popstate);
		}
		this._on_popstate = null;
		this.controller = null;
	}

	bind_controller(controller) {
		this.controller = controller;
		if (typeof window === "undefined") {
			return;
		}
		if (this._on_popstate) {
			window.removeEventListener("popstate", this._on_popstate);
		}
		this._on_popstate = () => {
			if (this._updating_url || this._hydrating) {
				return;
			}
			void (async () => {
				const result = await this.hydrate_from_location({ reason: "popstate", push: false });
				if (result.applied && result.auto_refresh && this.controller?.refresh_summary) {
					await this.controller.refresh_summary();
				}
			})();
		};
		window.addEventListener("popstate", this._on_popstate);
	}

	is_hydrating() {
		return this._hydrating;
	}

	get_warnings() {
		return [...this._warnings];
	}

	capture_workspace(controller = this.controller) {
		return ae_ws_codec().capture_from_controller(controller);
	}

	workspace_to_params(workspace, metadata = {}) {
		return ae_ws_codec().workspace_to_params(workspace, metadata);
	}

	params_to_workspace(params, metadata = {}) {
		return ae_ws_codec().params_to_workspace(params, metadata);
	}

	validate_workspace(workspace, metadata = {}) {
		return ae_ws_codec().validate_workspace(workspace, metadata);
	}

	build_url_search(workspace, metadata = {}) {
		return ae_ws_codec().build_url_search(workspace, metadata);
	}

	signature_for(workspace, metadata = {}) {
		return ae_ws_codec().signature_for(workspace, metadata);
	}

	exceeds_url_limit(workspace, metadata = {}) {
		const path = this._base_path();
		return (path + this.build_url_search(workspace, metadata)).length > ae_ws_core.AE_URL_MAX_LENGTH;
	}

	_base_path() {
		if (typeof window === "undefined") {
			return "/app/account-explorer";
		}
		return window.location.href.replace(window.location.search, "").replace(window.location.hash, "");
	}

	read_location_params() {
		if (typeof window === "undefined") {
			return new URLSearchParams();
		}
		const from_frappe =
			typeof frappe !== "undefined" && frappe.utils?.get_query_params
				? frappe.utils.get_query_params()
				: null;
		if (from_frappe && typeof from_frappe === "object") {
			const params = new URLSearchParams();
			Object.entries(from_frappe).forEach(([key, value]) => {
				if (value !== undefined && value !== null && value !== "") {
					params.set(key, Array.isArray(value) ? JSON.stringify(value) : String(value));
				}
			});
			return params;
		}
		return new URLSearchParams(window.location.search || "");
	}

	async resolve_from_params(params, metadata = {}) {
		this.events?.emit("workspace:hydrating");
		const token = params.get(ae_ws_core.AE_URL_STATE_TOKEN_KEY) || params.get("ae_token");
		if (token) {
			const payload = await this.restore_from_compact_token(token);
			this.events?.emit("workspace:token_loaded", { token, ok: !!payload });
			if (!payload) {
				return {
					workspace: null,
					warnings: [__("Workspace link token was missing or expired.")],
					from_token: true,
				};
			}
			const validated = this.validate_workspace(payload, metadata);
			return { ...validated, from_token: true };
		}
		if (params.get("ae") && !params.get(ae_ws_core.AE_URL_VERSION_KEY)) {
			try {
				const raw = JSON.parse(decodeURIComponent(params.get("ae")));
				return this.validate_workspace(
					{
						schema_version: ae_ws_core.AE_URL_VERSION,
						document_scope: raw.document_scope,
						analysis_context: raw.analysis_context,
						saved_view: raw.saved_view || null,
					},
					metadata
				);
			} catch (_error) {
				return { workspace: null, warnings: [__("Corrupt workspace URL state was ignored.")] };
			}
		}
		if (
			![...params.keys()].some(
				(key) => key === ae_ws_core.AE_URL_VERSION_KEY || ae_ws_core.AE_PARAM_ORDER.includes(key)
			)
		) {
			return { workspace: null, warnings: [], empty: true };
		}
		const parsed = this.params_to_workspace(params, metadata);
		const validated = this.validate_workspace(parsed.workspace, metadata);
		return {
			workspace: validated.workspace,
			warnings: [...parsed.warnings, ...validated.warnings],
			empty: false,
		};
	}

	apply_workspace_to_controller(controller, workspace, warnings = []) {
		if (!controller || !workspace) {
			return false;
		}
		this._hydrating = true;
		this._generation += 1;
		this._warnings = [...warnings];
		try {
			controller.document_scope = {
				...controller.document_scope,
				...workspace.document_scope,
				voucher: { ...(controller.document_scope.voucher || {}), ...(workspace.document_scope.voucher || {}) },
				accounting: {
					...(controller.document_scope.accounting || {}),
					...(workspace.document_scope.accounting || {}),
				},
				accounting_dimensions: { ...(workspace.document_scope.accounting_dimensions || {}) },
				currency: {
					...(controller.document_scope.currency || {}),
					...(workspace.document_scope.currency || {}),
				},
				status: { ...(controller.document_scope.status || {}), ...(workspace.document_scope.status || {}) },
			};
			const analysis = workspace.analysis_context || {};
			controller.analysis_context = {
				...controller.analysis_context,
				...analysis,
				account_scope: {
					...(controller.analysis_context.account_scope || {}),
					...(analysis.account_scope || {}),
				},
				party_scope: {
					...(controller.analysis_context.party_scope || {}),
					...(analysis.party_scope || {}),
				},
				unified_party_scope: {
					...(controller.analysis_context.unified_party_scope || {}),
					...(analysis.unified_party_scope || {}),
				},
				dimension_scope: {
					...(controller.analysis_context.dimension_scope || {}),
					...(analysis.dimension_scope || {}),
				},
				voucher_scope: {
					...(controller.analysis_context.voucher_scope || {}),
					...(analysis.voucher_scope || {}),
				},
			};
			if (workspace.saved_view) {
				controller._pending_saved_view_from_url = workspace.saved_view;
			}
			const AF = erpnext_extensions.account_explorer.core.AnalysisFilters;
			let filters = AF.normalize_bag(workspace.analysis_filters);
			if (!AF.list_entries(filters).length) {
				filters = AF.hydrate_from_legacy_scopes(
					filters,
					controller.analysis_context,
					controller.document_scope,
					"legacy_url"
				);
			}
			controller.analysis_filters = filters;
			controller._reset_breadcrumbs?.([]);
			controller._sync_store_context?.({ emit: false });
			this.store?.patch(
				{
					document_scope: controller.document_scope,
					analysis_filters: controller.analysis_filters,
					analysis_context: controller.analysis_context,
					navigation: { breadcrumbs: controller.breadcrumbs || [] },
				},
				{ silent: true }
			);
			this.events?.emit("workspace:hydrated", {
				warnings: this._warnings,
				generation: this._generation,
			});
			return true;
		} finally {
			this._hydrating = false;
		}
	}

	sync_controls_from_controller(controller) {
		if (!controller) {
			return;
		}
		controller.company_field?.set_value(controller.document_scope.company || "");
		controller.fy_field?.set_value(controller.document_scope.fiscal_year || "");
		controller.from_date_field?.set_value(controller.document_scope.from_date || "");
		controller.to_date_field?.set_value(controller.document_scope.to_date || "");
		controller.sync_filter_controls_from_document_scope?.(controller.document_scope);
		controller.render_navigator?.();
		controller.render_breadcrumbs?.();
		controller.render_detail_header?.();
		controller.update_advanced_filters_button?.();
		controller.render_filter_summary?.();
		controller.update_context_actions?.();
	}

	async hydrate_from_location({ reason = "init", push = false } = {}) {
		const controller = this.controller;
		if (!controller?.metadata) {
			return { applied: false, auto_refresh: false };
		}
		const resolved = await this.resolve_from_params(this.read_location_params(), controller.metadata);
		this._warnings = resolved.warnings || [];
		if (resolved.empty || !resolved.workspace) {
			if (this._warnings.length) {
				this._show_warnings(this._warnings);
				this.events?.emit("workspace:error", { warnings: this._warnings, reason });
			}
			return { applied: false, auto_refresh: false, warnings: this._warnings };
		}
		const applied = this.apply_workspace_to_controller(controller, resolved.workspace, this._warnings);
		this.sync_controls_from_controller(controller);
		this._last_url_signature = this.signature_for(resolved.workspace, controller.metadata);
		if (this._warnings.length) {
			this._show_warnings(this._warnings);
		}
		const auto_refresh = !!(
			resolved.workspace.document_scope?.company &&
			resolved.workspace.document_scope?.from_date &&
			resolved.workspace.document_scope?.to_date
		);
		this.events?.emit("workspace:changed", { reason, push, auto_refresh });
		return { applied, auto_refresh, warnings: this._warnings };
	}

	schedule_url_update({ push = false } = {}) {
		if (this._hydrating || this._updating_url || !this.controller) {
			return;
		}
		this._clear_url_timer();
		this._pending_push = !!push || this._pending_push;
		this._url_timer = setTimeout(() => {
			void this.write_url({ push: this._pending_push });
			this._pending_push = false;
		}, ae_ws_core.AE_URL_DEBOUNCE_MS);
	}

	write_url_now({ push = false } = {}) {
		this._clear_url_timer();
		return this.write_url({ push });
	}

	async write_url({ push = false } = {}) {
		if (this._hydrating || this._updating_url || !this.controller || typeof window === "undefined") {
			return null;
		}
		const workspace = this.capture_workspace();
		if (!workspace) {
			return null;
		}
		const metadata = this.controller.metadata || {};
		let search = this.build_url_search(workspace, metadata);
		if (this.exceeds_url_limit(workspace, metadata)) {
			const token = await this.save_compact_token(workspace);
			if (token) {
				const params = new URLSearchParams();
				params.set(ae_ws_core.AE_URL_VERSION_KEY, String(ae_ws_core.AE_URL_VERSION));
				params.set(ae_ws_core.AE_URL_STATE_TOKEN_KEY, token);
				search = `?${params.toString()}`;
			}
		}
		const signature = search;
		if (signature === this._last_url_signature) {
			return signature;
		}
		this._updating_url = true;
		try {
			const url = this._base_path() + search;
			if (push) {
				window.history.pushState({ ae_workspace: 1 }, "", url);
			} else {
				window.history.replaceState({ ae_workspace: 1 }, "", url);
			}
			this._last_url_signature = signature;
			this.events?.emit("workspace:url_updated", { push, search });
			return signature;
		} finally {
			this._updating_url = false;
		}
	}

	async copy_workspace_link() {
		await this.write_url_now({ push: false });
		const href = typeof window !== "undefined" ? window.location.href : "";
		if (navigator?.clipboard?.writeText) {
			await navigator.clipboard.writeText(href);
		}
		frappe.show_alert({ message: __("Workspace link copied."), indicator: "green" });
		return href;
	}

	save_compact_token(workspace) {
		return ae_ws_tokens().save_compact_token(workspace);
	}

	restore_from_compact_token(token) {
		return ae_ws_tokens().restore_from_compact_token(token);
	}

	_show_warnings(warnings) {
		const list = (warnings || []).slice(0, 3);
		if (!list.length) {
			return;
		}
		frappe.show_alert({ message: list.join("<br>"), indicator: "orange" });
	}

	_clear_url_timer() {
		if (this._url_timer) {
			clearTimeout(this._url_timer);
			this._url_timer = null;
		}
	}
};
