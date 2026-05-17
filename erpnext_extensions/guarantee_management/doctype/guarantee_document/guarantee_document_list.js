// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

frappe.listview_settings["Guarantee Document"] = {
	add_fields: ["party_type", "other_party_name", "guarantee_direction", "document_no", "expiry_date"],

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
		party(value, df, doc) {
			if (doc.party_type === "Other") {
				return doc.other_party_name || value || "";
			}
			return value;
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
