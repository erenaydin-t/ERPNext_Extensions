// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.listview_settings["Guarantee Document"] = {
	add_fields: [
		"party_type",
		"party",
		"other_party_name",
		"guarantee_direction",
		"status",
		"document_no",
		"expiry_date",
		"guarantee_type",
		"amount",
		"currency",
	],

	onload(listview) {
		// Presentation-only: rename Direction column header to Held By (field identity unchanged).
		(listview.columns || []).forEach((col) => {
			if (col.df && col.df.fieldname === "guarantee_direction") {
				col.df.label = __("Held By");
			}
		});

		if (listview._gd_render_patched) {
			return;
		}
		listview._gd_render_patched = true;
		listview._gd_party_display_cache = {};

		const original_render = listview.render_list.bind(listview);
		listview.render_list = function () {
			if (listview._gd_resolving_parties) {
				original_render();
				return;
			}
			listview._gd_resolving_parties = true;
			gd_batch_resolve_party_displays(listview).finally(() => {
				listview._gd_resolving_parties = false;
				original_render();
			});
		};
	},

	get_indicator(doc) {
		const status = (doc.status || "Draft").trim();
		const colors = {
			Draft: "gray",
			Active: "green",
			Returned: "blue",
			Released: "cyan",
			Cancelled: "darkgrey",
			Expired: "orange",
			Lost: "red",
		};
		const color = colors[status] || "gray";
		return [__(status), color, "status,=," + status];
	},

	formatters: {
		guarantee_direction(value, df, doc) {
			return gd_held_by_label(doc);
		},
		party(value, df, doc) {
			if (doc.party_type === "Other") {
				return doc.other_party_name || value || "";
			}
			const list = typeof cur_list !== "undefined" ? cur_list : null;
			const cache = (list && list._gd_party_display_cache) || {};
			const key = (doc.party_type || "") + "::" + (doc.party || "");
			if (cache[key]) {
				return cache[key];
			}
			return value || "";
		},
		title(value, df, doc) {
			const no = (doc.document_no || "").trim();
			if (no) {
				return no;
			}
			return doc.name;
		},
	},
};

function gd_held_by_label(doc) {
	const status = (doc.status || "").trim();
	const direction = (doc.guarantee_direction || "").trim();
	if (status !== "Active") {
		return "—";
	}
	if (direction === "Received") {
		return __("Held by Us");
	}
	if (direction === "Issued") {
		return __("Held by Others");
	}
	return "—";
}

function gd_batch_resolve_party_displays(listview) {
	const data = listview.data || [];
	const refs = [];
	const seen = {};

	data.forEach((doc) => {
		const pt = (doc.party_type || "").trim();
		if (pt === "Other") {
			const other = (doc.other_party_name || "").trim();
			if (!other) {
				return;
			}
			const key = "Other::" + other;
			if (!seen[key]) {
				seen[key] = true;
				refs.push({
					party_type: "Other",
					party: "",
					other_party_name: other,
				});
			}
			return;
		}
		const party = (doc.party || "").trim();
		if (!pt || !party) {
			return;
		}
		const key = pt + "::" + party;
		if (seen[key]) {
			return;
		}
		seen[key] = true;
		refs.push({
			party_type: pt,
			party: party,
			other_party_name: "",
		});
	});

	if (!refs.length) {
		listview._gd_party_display_cache = {};
		return Promise.resolve();
	}

	return frappe
		.call({
			method:
				"erpnext_extensions.guarantee_management.services.party_display.batch_resolve_party_displays_for_list",
			args: { refs },
		})
		.then((r) => {
			listview._gd_party_display_cache = (r && r.message) || {};
		})
		.catch(() => {
			listview._gd_party_display_cache = {};
		});
}
