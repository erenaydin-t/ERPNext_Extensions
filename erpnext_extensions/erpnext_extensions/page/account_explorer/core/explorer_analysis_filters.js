frappe.provide("erpnext_extensions.account_explorer.core");

/**
 * Analysis Filters — normalize, lifetime, legacy scope mapping, summary rows.
 * ADR-3B-004. No rendering, grid access, or SQL.
 */
const AE_AF_TOP_KEYS = ["account", "party", "unified_party", "voucher", "currency"];
const AE_AF_LIFETIMES = new Set(["session", "drill", "temporary"]);
const AE_AF_ORIGINS = new Set([
	"drill_graph",
	"filters_panel",
	"url_hydrate",
	"legacy_url",
	"saved_view",
	"user",
	"compat",
]);

function ae_af_clone(value) {
	return JSON.parse(JSON.stringify(value ?? null));
}

function ae_af_is_empty(value) {
	return (
		value === undefined ||
		value === null ||
		value === "" ||
		(Array.isArray(value) && !value.length)
	);
}

function ae_af_normalize_value(value) {
	if (ae_af_is_empty(value)) {
		return null;
	}
	if (Array.isArray(value)) {
		const items = [...new Set(value.map((item) => String(item ?? "").trim()).filter((v) => v !== ""))];
		if (!items.length) {
			return null;
		}
		return items.length === 1 ? items[0] : items;
	}
	if (typeof value === "object") {
		return ae_af_clone(value);
	}
	return String(value);
}

function ae_af_empty_bag() {
	return {
		account: null,
		party: null,
		unified_party: null,
		voucher: null,
		currency: null,
		dimensions: {},
	};
}

function ae_af_parse_key(key) {
	const text = String(key || "").trim();
	if (!text) {
		return null;
	}
	if (text.startsWith("dimensions.")) {
		return { kind: "dimension", fieldname: text.slice("dimensions.".length) };
	}
	if (AE_AF_TOP_KEYS.includes(text)) {
		return { kind: "top", fieldname: text };
	}
	return { kind: "dimension", fieldname: text };
}

erpnext_extensions.account_explorer.core.AnalysisFilters = class AnalysisFilters {
	static empty() {
		return ae_af_empty_bag();
	}

	static clone(bag) {
		return ae_af_clone(bag || ae_af_empty_bag()) || ae_af_empty_bag();
	}

	static normalize_entry(partial = {}, defaults = {}) {
		if (!partial || typeof partial !== "object") {
			return null;
		}
		const key = String(partial.key || defaults.key || "").trim();
		const lifetime = AE_AF_LIFETIMES.has(partial.lifetime)
			? partial.lifetime
			: defaults.lifetime || "session";
		const origin = AE_AF_ORIGINS.has(partial.origin)
			? partial.origin
			: defaults.origin || "user";
		const value = ae_af_normalize_value(
			partial.value !== undefined ? partial.value : defaults.value
		);
		if (!key || ae_af_is_empty(value)) {
			return null;
		}
		const entry = {
			key,
			value,
			origin,
			lifetime,
			removable: partial.removable === undefined ? true : !!partial.removable,
		};
		if (partial.bound_to != null && partial.bound_to !== "") {
			entry.bound_to = partial.bound_to;
		} else if (defaults.bound_to != null && defaults.bound_to !== "") {
			entry.bound_to = defaults.bound_to;
		}
		if (partial.label) {
			entry.label = String(partial.label);
		}
		if (partial.meta && typeof partial.meta === "object") {
			entry.meta = ae_af_clone(partial.meta);
		}
		return entry;
	}

	static normalize_bag(raw) {
		const bag = ae_af_empty_bag();
		if (!raw || typeof raw !== "object") {
			return bag;
		}
		AE_AF_TOP_KEYS.forEach((key) => {
			if (!raw[key]) {
				return;
			}
			bag[key] = this.normalize_entry(
				typeof raw[key] === "object" && raw[key].key
					? raw[key]
					: { key, value: raw[key].value ?? raw[key], ...raw[key] },
				{ key, lifetime: "session", origin: "compat" }
			);
		});
		const dims = raw.dimensions && typeof raw.dimensions === "object" ? raw.dimensions : {};
		Object.keys(dims).forEach((fieldname) => {
			const entry = dims[fieldname];
			const normalized = this.normalize_entry(
				typeof entry === "object" && entry !== null
					? { ...entry, key: entry.key || `dimensions.${fieldname}` }
					: { key: `dimensions.${fieldname}`, value: entry },
				{ key: `dimensions.${fieldname}`, lifetime: "session", origin: "compat" }
			);
			if (normalized) {
				bag.dimensions[fieldname] = normalized;
			}
		});
		return bag;
	}

	static get_entry(bag, key) {
		const parsed = ae_af_parse_key(key);
		if (!parsed) {
			return null;
		}
		const normalized = this.normalize_bag(bag);
		if (parsed.kind === "top") {
			return normalized[parsed.fieldname] || null;
		}
		return normalized.dimensions[parsed.fieldname] || null;
	}

	static set_entry(bag, entry_or_partial, defaults = {}) {
		const next = this.normalize_bag(bag);
		const entry = this.normalize_entry(entry_or_partial, defaults);
		if (!entry) {
			return next;
		}
		const parsed = ae_af_parse_key(entry.key);
		if (!parsed) {
			return next;
		}
		if (parsed.kind === "top") {
			next[parsed.fieldname] = { ...entry, key: parsed.fieldname };
			return next;
		}
		next.dimensions = { ...next.dimensions, [parsed.fieldname]: { ...entry, key: `dimensions.${parsed.fieldname}` } };
		return next;
	}

	static remove_entry(bag, key) {
		const next = this.normalize_bag(bag);
		const parsed = ae_af_parse_key(key);
		if (!parsed) {
			return next;
		}
		if (parsed.kind === "top") {
			next[parsed.fieldname] = null;
			return next;
		}
		const dims = { ...next.dimensions };
		delete dims[parsed.fieldname];
		next.dimensions = dims;
		return next;
	}

	static clear(bag, { lifetimes = null } = {}) {
		if (!lifetimes || !lifetimes.length) {
			return ae_af_empty_bag();
		}
		const allowed = new Set(lifetimes);
		const next = ae_af_empty_bag();
		const current = this.normalize_bag(bag);
		AE_AF_TOP_KEYS.forEach((key) => {
			const entry = current[key];
			if (entry && !allowed.has(entry.lifetime)) {
				next[key] = entry;
			}
		});
		Object.entries(current.dimensions || {}).forEach(([field, entry]) => {
			if (entry && !allowed.has(entry.lifetime)) {
				next.dimensions[field] = entry;
			}
		});
		return next;
	}

	static list_entries(bag) {
		const current = this.normalize_bag(bag);
		const entries = [];
		AE_AF_TOP_KEYS.forEach((key) => {
			if (current[key]) {
				entries.push(current[key]);
			}
		});
		Object.keys(current.dimensions || {})
			.sort()
			.forEach((field) => {
				if (current.dimensions[field]) {
					entries.push(current.dimensions[field]);
				}
			});
		return entries;
	}

	static evaluate_lifetimes(bag, { active_bound_paths = null, consume_temporary = false } = {}) {
		const current = this.normalize_bag(bag);
		const next = ae_af_empty_bag();
		const active = active_bound_paths == null ? null : new Set(active_bound_paths);
		const keep = (entry) => {
			if (!entry) {
				return false;
			}
			if (entry.lifetime === "temporary" && consume_temporary) {
				return false;
			}
			if (entry.lifetime === "drill" && active) {
				if (entry.bound_to == null || entry.bound_to === "") {
					return false;
				}
				return active.has(entry.bound_to);
			}
			return true;
		};
		AE_AF_TOP_KEYS.forEach((key) => {
			if (keep(current[key])) {
				next[key] = current[key];
			}
		});
		Object.entries(current.dimensions || {}).forEach(([field, entry]) => {
			if (keep(entry)) {
				next.dimensions[field] = entry;
			}
		});
		return next;
	}

	static consume_temporary(bag) {
		return this.evaluate_lifetimes(bag, { consume_temporary: true });
	}

	static apply_policy(bag, policy, entry_partial, defaults = {}) {
		const current = this.normalize_bag(bag);
		let next = current;
		const entry = this.normalize_entry(entry_partial, defaults);

		switch (policy) {
			case "keep_filters":
				return current;
			case "clear_drill_filters":
				return this.clear(current, { lifetimes: ["drill"] });
			case "consume_temporary":
				return this.consume_temporary(current);
			case "append_filter":
				if (!entry) {
					return current;
				}
				return this.set_entry(current, entry, defaults);
			case "replace_filter":
				if (!entry) {
					return current;
				}
				return this.set_entry(current, entry, defaults);
			case "replace_dimension": {
				if (!entry) {
					return current;
				}
				const parsed = ae_af_parse_key(entry.key);
				const fieldname = parsed?.kind === "dimension" ? parsed.fieldname : entry.meta?.dimension_type;
				if (!fieldname) {
					return this.set_entry(current, entry, defaults);
				}
				next = this.set_entry(current, { ...entry, key: `dimensions.${fieldname}` }, defaults);
				return next;
			}
			default:
				if (entry) {
					return this.set_entry(current, entry, defaults);
				}
				return current;
		}
	}

	/**
	 * Project analysis_filters into legacy analysis_context scopes + document currency.
	 * Analysis filters are authoritative; returns shallow-cloned scopes.
	 */
	static build_legacy_scope_payload_from_analysis_filters(bag, analysis_context, document_scope) {
		const filters = this.normalize_bag(bag);
		const ctx = ae_af_clone(analysis_context || {}) || {};
		const doc = ae_af_clone(document_scope || {}) || {};
		const account_scope = { ...(ctx.account_scope || {}) };
		const party_scope = { ...(ctx.party_scope || {}) };
		const unified_party_scope = { ...(ctx.unified_party_scope || {}) };
		const dimension_scope = { ...(ctx.dimension_scope || {}) };
		const voucher_scope = { ...(ctx.voucher_scope || {}) };
		const accounting = { ...(doc.accounting || {}) };
		const accounting_dimensions = { ...(doc.accounting_dimensions || {}) };
		const currency = { ...(doc.currency || {}) };
		const warnings = [];

		if (filters.account) {
			const meta = filters.account.meta || {};
			const raw_value =
				typeof filters.account.value === "object"
					? filters.account.value.selected_account || filters.account.value.virtual_row_key
					: filters.account.value;
			const is_virtual =
				meta.mode === "virtual_prefix" ||
				!!meta.is_virtual_group ||
				!!meta.virtual_row_key ||
				String(raw_value || "").startsWith("virtual:");
			if (is_virtual) {
				account_scope.mode = "virtual_prefix";
				account_scope.selected_account = null;
				account_scope.virtual_row_key = meta.virtual_row_key || raw_value;
				account_scope.is_virtual_group = 1;
			} else {
				account_scope.selected_account = raw_value;
				account_scope.mode = meta.mode || account_scope.mode || "account";
				account_scope.virtual_row_key = null;
				account_scope.is_virtual_group = 0;
				account_scope.tree_root_account = raw_value;
			}
			if (meta.level_sequence != null) {
				account_scope.level_sequence = meta.level_sequence;
			}
			if (
				!is_virtual &&
				accounting.account &&
				String(accounting.account) !== String(account_scope.selected_account)
			) {
				warnings.push({
					code: "analysis_overrides_document",
					field: "account",
					message: "Analysis filter account overrides document_scope.accounting.account",
				});
			}
		}

		if (filters.party) {
			const value = filters.party.value;
			const meta = filters.party.meta || {};
			party_scope.selected_party = typeof value === "object" ? value.party || value.selected_party : value;
			party_scope.party_type =
				meta.party_type ||
				(typeof value === "object" ? value.party_type : null) ||
				party_scope.party_type;
			if (accounting.party && String(accounting.party) !== String(party_scope.selected_party)) {
				warnings.push({
					code: "analysis_overrides_document",
					field: "party",
					message: "Analysis filter party overrides document_scope.accounting.party",
				});
			}
		}

		if (filters.unified_party) {
			unified_party_scope.selected_unified_party =
				typeof filters.unified_party.value === "object"
					? filters.unified_party.value.unified_party
					: filters.unified_party.value;
		}

		if (filters.voucher) {
			const value = filters.voucher.value;
			const meta = filters.voucher.meta || {};
			voucher_scope.voucher_no =
				typeof value === "object" ? value.voucher_no || value.voucher : value;
			voucher_scope.voucher_type =
				meta.voucher_type ||
				(typeof value === "object" ? value.voucher_type : null) ||
				voucher_scope.voucher_type;
		}

		if (filters.currency) {
			currency.currency =
				typeof filters.currency.value === "object"
					? filters.currency.value.currency
					: filters.currency.value;
			if (filters.currency.meta?.currency_type) {
				currency.currency_type = filters.currency.meta.currency_type;
			}
		}

		Object.entries(filters.dimensions || {}).forEach(([fieldname, entry]) => {
			if (!entry) {
				return;
			}
			const value = typeof entry.value === "object" ? entry.value.dimension_value ?? entry.value : entry.value;
			if (dimension_scope.dimension_type === fieldname || !dimension_scope.selected_dimension_value) {
				dimension_scope.dimension_type = dimension_scope.dimension_type || fieldname;
			}
			// Multi-dimension: park all in accounting_dimensions; primary axis type also in dimension_scope
			if (Object.keys(filters.dimensions).length === 1 || dimension_scope.dimension_type === fieldname) {
				dimension_scope.dimension_type = fieldname;
				dimension_scope.selected_dimension_value = value;
			}
			accounting_dimensions[fieldname] = value;
			if (
				doc.accounting_dimensions &&
				!ae_af_is_empty(doc.accounting_dimensions[fieldname]) &&
				String(doc.accounting_dimensions[fieldname]) !== String(value)
			) {
				warnings.push({
					code: "analysis_overrides_document",
					field: fieldname,
					message: `Analysis filter dimensions.${fieldname} overrides document_scope.accounting_dimensions`,
				});
			}
		});

		return {
			analysis_context: {
				...ctx,
				account_scope,
				party_scope,
				unified_party_scope,
				dimension_scope,
				voucher_scope,
			},
			document_scope: {
				...doc,
				accounting,
				accounting_dimensions,
				currency,
			},
			warnings,
		};
	}

	/**
	 * Hydrate analysis_filters from legacy analysis_context scopes / document currency.
	 * Only fills empty keys; existing bag entries win.
	 */
	static hydrate_from_legacy_scopes(bag, analysis_context, document_scope, origin = "compat") {
		let next = this.normalize_bag(bag);
		const ctx = analysis_context || {};
		const doc = document_scope || {};
		const lifetime = "session";

		const account = ctx.account_scope || {};
		if (!next.account && (account.selected_account || account.virtual_row_key)) {
			next = this.set_entry(
				next,
				{
					key: "account",
					value: account.selected_account || account.virtual_row_key,
					origin,
					lifetime,
					meta: {
						mode: account.mode,
						virtual_row_key: account.virtual_row_key,
						is_virtual_group: account.is_virtual_group,
						level_sequence: account.level_sequence,
					},
				},
				{ key: "account", origin, lifetime }
			);
		}

		const party = ctx.party_scope || {};
		if (!next.party && party.selected_party) {
			next = this.set_entry(
				next,
				{
					key: "party",
					value: party.selected_party,
					origin,
					lifetime,
					meta: { party_type: party.party_type },
				},
				{ key: "party", origin, lifetime }
			);
		}

		const unified = ctx.unified_party_scope || {};
		if (!next.unified_party && unified.selected_unified_party) {
			next = this.set_entry(
				next,
				{
					key: "unified_party",
					value: unified.selected_unified_party,
					origin,
					lifetime,
				},
				{ key: "unified_party", origin, lifetime }
			);
		}

		const dim = ctx.dimension_scope || {};
		if (dim.dimension_type && dim.selected_dimension_value != null && dim.selected_dimension_value !== undefined) {
			const key = `dimensions.${dim.dimension_type}`;
			if (!this.get_entry(next, key)) {
				next = this.set_entry(
					next,
					{
						key,
						value: dim.selected_dimension_value,
						origin,
						lifetime,
						meta: { dimension_type: dim.dimension_type },
					},
					{ key, origin, lifetime }
				);
			}
		}

		const voucher = ctx.voucher_scope || {};
		if (!next.voucher && voucher.voucher_no) {
			next = this.set_entry(
				next,
				{
					key: "voucher",
					value: voucher.voucher_no,
					origin,
					lifetime,
					meta: { voucher_type: voucher.voucher_type },
				},
				{ key: "voucher", origin, lifetime }
			);
		}

		// Currency framing stays in document_scope; do not invent analysis currency here.

		return next;
	}

	static serialize(bag) {
		const entries = this.list_entries(bag).map((entry) => ({
			key: entry.key,
			value: entry.value,
			origin: entry.origin,
			lifetime: entry.lifetime,
			removable: entry.removable !== false,
			bound_to: entry.bound_to || null,
			label: entry.label || null,
			meta: entry.meta || null,
		}));
		return entries.length ? entries : null;
	}

	static deserialize(raw, origin = "url_hydrate") {
		let next = ae_af_empty_bag();
		if (!raw) {
			return next;
		}
		let list = raw;
		if (typeof raw === "string") {
			try {
				list = JSON.parse(raw);
			} catch (_error) {
				return next;
			}
		}
		if (!Array.isArray(list)) {
			return this.normalize_bag(list);
		}
		list.forEach((item) => {
			next = this.set_entry(next, item, {
				key: item?.key,
				origin: item?.origin || origin,
				lifetime: item?.lifetime || "session",
			});
		});
		return next;
	}

	static build_summary_rows(bag, { document_scope = null, analysis_context = null, metadata = null } = {}) {
		const rows = [];
		const doc = document_scope || {};
		const ctx = analysis_context || {};

		const push_doc = (key, label, value, removable = false) => {
			if (ae_af_is_empty(value) && value !== 0) {
				return;
			}
			rows.push({
				group: "document_scope",
				key: `document.${key}`,
				label,
				value: Array.isArray(value) ? value.join(", ") : String(value),
				origin: "document_scope",
				lifetime: "session",
				removable: !!removable,
			});
		};

		push_doc("company", __("Company"), doc.company);
		push_doc("fiscal_year", __("Fiscal Year"), doc.fiscal_year);
		if (doc.from_date || doc.to_date) {
			push_doc("date_range", __("Date Range"), `${doc.from_date || "…"} → ${doc.to_date || "…"}`);
		}
		push_doc("finance_book", __("Finance Book"), doc.finance_book);
		if (cint(doc.hide_zero_rows) === 0) {
			push_doc("hide_zero_rows", __("Hide Zero Rows"), __("Off"));
		}
		const status = doc.status || {};
		if (cint(status.include_cancelled_entries)) {
			push_doc("include_cancelled", __("Include Cancelled"), __("Yes"));
		}
		if (!cint(status.include_opening_entries)) {
			push_doc("include_opening", __("Include Opening"), __("No"));
		}
		if (!cint(status.include_default_finance_book_entries)) {
			push_doc("include_default_book", __("Default Finance Book Entries"), __("No"));
		}
		if (cint(status.include_period_closing_vouchers)) {
			push_doc("include_pcv", __("Period Closing Vouchers"), __("Yes"));
		}
		if (doc.voucher?.voucher_type || doc.voucher?.voucher_no) {
			push_doc(
				"document_voucher",
				__("Document Voucher"),
				[doc.voucher.voucher_type, doc.voucher.voucher_no].filter(Boolean).join(" / ")
			);
		}
		if (doc.accounting?.account) {
			push_doc("document_account", __("Document Account"), doc.accounting.account);
		}
		if (doc.accounting?.party) {
			push_doc(
				"document_party",
				__("Document Party"),
				[doc.accounting.party_type, doc.accounting.party].filter(Boolean).join(" / ")
			);
		}
		Object.entries(doc.accounting_dimensions || {}).forEach(([field, value]) => {
			if (ae_af_is_empty(value)) {
				return;
			}
			const dim = (metadata?.dimensions || []).find((item) => item.fieldname === field);
			push_doc(`document_dim_${field}`, dim?.label || field, Array.isArray(value) ? value.join(", ") : value);
		});

		this.list_entries(bag).forEach((entry) => {
			const label = this._label_for_entry(entry, metadata);
			const display = this._display_value(entry);
			rows.push({
				group: "analysis_filters",
				key: entry.key,
				label,
				value: display,
				origin: entry.origin,
				origin_label: entry.meta?.source_axis_label || entry.origin,
				lifetime: entry.lifetime,
				lifetime_label: this._lifetime_label(entry.lifetime),
				removable: entry.removable !== false,
				bound_to: entry.bound_to || null,
				meta: entry.meta || null,
			});
		});

		const axis_map = {
			account_level: __("Account Levels"),
			party: __("Parties"),
			unified_party: __("Unified Parties"),
			dimension: __("Dimensions"),
			currency: __("Currencies"),
			voucher: __("Vouchers"),
		};
		rows.push({
			group: "presentation",
			key: "presentation.axis",
			label: __("Axis"),
			value: axis_map[ctx.view_axis] || ctx.view_axis || "",
			origin: "presentation",
			lifetime: "session",
			removable: false,
		});
		if (ctx.view_axis === "account_level" && ctx.level_sequence != null) {
			const level = (metadata?.levels || []).find(
				(item) => Number(item.sequence) === Number(ctx.level_sequence)
			);
			const level_label =
				(level && (level.title || level.title_fa || level.label)) || String(ctx.level_sequence);
			rows.push({
				group: "presentation",
				key: "presentation.level",
				label: __("Level"),
				value: level_label,
				origin: "presentation",
				lifetime: "session",
				removable: false,
			});
		}
		if (ctx.view_axis === "dimension" && ctx.dimension_scope?.dimension_type) {
			const field = ctx.dimension_scope.dimension_type;
			const dim = (metadata?.dimensions || []).find((item) => item.fieldname === field);
			rows.push({
				group: "presentation",
				key: "presentation.dimension_type",
				label: __("Dimension Type"),
				value: dim?.label || field,
				origin: "presentation",
				lifetime: "session",
				removable: false,
			});
		}
		if (ctx.detail_mode && ctx.detail_mode !== "summary") {
			rows.push({
				group: "presentation",
				key: "presentation.detail_mode",
				label: __("Detail Mode"),
				value: ctx.detail_mode,
				origin: "presentation",
				lifetime: "session",
				removable: false,
			});
		}

		return rows;
	}

	static _label_for_entry(entry, metadata) {
		const parsed = ae_af_parse_key(entry.key);
		if (parsed?.kind === "dimension") {
			const dim = (metadata?.dimensions || []).find((item) => item.fieldname === parsed.fieldname);
			return dim?.label || parsed.fieldname;
		}
		if (entry.key === "account") {
			const meta = entry.meta || {};
			if (meta.is_virtual_group || meta.mode === "virtual_prefix" || cint(meta.is_group)) {
				return __("Account Group");
			}
			return __("Account");
		}
		const map = {
			party: __("Party"),
			unified_party: __("Unified Party"),
			voucher: __("Voucher"),
			currency: __("Currency"),
		};
		return map[entry.key] || entry.label || entry.key;
	}

	static _lifetime_label(lifetime) {
		return { session: __("Session"), drill: __("Drill"), temporary: __("Temporary") }[lifetime] || lifetime || "—";
	}

	static _display_value(entry) {
		if (entry.meta?.display_label) {
			return String(entry.meta.display_label);
		}
		const value = entry.value;
		if (value && typeof value === "object" && !Array.isArray(value)) {
			return (
				value.display ||
				value.selected_account ||
				value.party ||
				value.unified_party ||
				value.voucher_no ||
				value.currency ||
				value.dimension_value ||
				JSON.stringify(value)
			);
		}
		if (Array.isArray(value)) {
			return value.join(", ");
		}
		return String(value ?? "");
	}
};
