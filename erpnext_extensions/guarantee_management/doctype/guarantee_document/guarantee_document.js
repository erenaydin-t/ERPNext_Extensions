// Copyright (c) 2026, ERPNext Extensions contributors
// License: MIT

const GD_COLLAPSIBLE_SECTIONS = ["section_lifecycle", "section_reference", "section_notes"];

const GD_FULL_WIDTH_FIELDS = ["purpose", "reference_description", "remarks", "cancelled_date"];

const GD_STATUS_HINTS = {
	Draft: __("Record is being prepared. Document number can be added later."),
	Active: __("Guarantee is in custody and tracked as live."),
	Returned: __("Document was returned to the counterparty or source."),
	Released: __("Issued guarantee was released (e.g. bank guarantee released)."),
	Cancelled: __("Guarantee was voided before or instead of normal closure."),
	Expired: __("Past validity / expiry; update custody if the original was retrieved."),
	Lost: __("Original cannot be located — document for audit trail only."),
};

frappe.ui.form.on("Guarantee Document", {
	onload(frm) {
		gd_load_form_styles();
		frm.$wrapper.addClass("guarantee-document-form");
		gd_collapse_optional_sections(frm);
		gd_apply_layout_classes(frm);
	},

	refresh(frm) {
		gd_set_form_intro(frm);
		gd_apply_layout_classes(frm);
	},

	company(frm) {
		if (!frm.doc.company || frm.doc.currency) {
			return;
		}
		frappe.db.get_value("Company", frm.doc.company, "default_currency", (r) => {
			if (r && r.default_currency) {
				frm.set_value("currency", r.default_currency);
			}
		});
	},

	status(frm) {
		gd_set_form_intro(frm);
	},

	party_type(frm) {
		if (frm.doc.party_type === "Other" && frm.doc.party) {
			frm.set_value("party", "");
		}
		if (frm.doc.party_type !== "Other" && frm.doc.other_party_name) {
			frm.set_value("other_party_name", "");
		}
	},
});

function gd_collapse_optional_sections(frm) {
	if (frm._gd_collapsed_once) {
		return;
	}
	frm._gd_collapsed_once = true;
	GD_COLLAPSIBLE_SECTIONS.forEach((fieldname) => {
		const field = frm.get_field(fieldname);
		if (field && typeof field.collapse === "function") {
			field.collapse();
		}
	});
}

function gd_set_form_intro(frm) {
	const status = (frm.doc.status || "Draft").trim();
	const direction = (frm.doc.guarantee_direction || "").trim();
	let intro = GD_STATUS_HINTS[status] || "";

	if (status === "Active" && direction === "Received") {
		intro += " " + __("Ensure Received Date is set under Lifecycle Dates.");
	} else if (status === "Active" && direction === "Issued") {
		intro += " " + __("Ensure Issued Date is set under Lifecycle Dates.");
	}

	// Frappe appends headline messages; clear before replace to avoid duplicates on refresh/status.
	if (frm.dashboard && typeof frm.dashboard.clear_headline === "function") {
		frm.dashboard.clear_headline();
	}

	frm.set_intro(intro, intro ? "blue" : false);
}

function gd_load_form_styles() {
	if (window.__gd_form_css_loaded) {
		return;
	}
	window.__gd_form_css_loaded = true;
	frappe.require("/assets/erpnext_extensions/css/guarantee_document_form.css");
}

function gd_apply_layout_classes(frm) {
	GD_FULL_WIDTH_FIELDS.forEach((fieldname) => {
		const field = frm.fields_dict[fieldname];
		if (!field || !field.$wrapper) {
			return;
		}
		const col = field.$wrapper.closest(".form-column");
		if (col && col.length) {
			const section = field.$wrapper.closest(".form-section");
			const isRef = section.length && section.attr("data-fieldname") === "section_reference";
			const isLc = fieldname === "cancelled_date";
			col.toggleClass("gd-ref-full", isRef);
			col.toggleClass("gd-lc-full", isLc);
		}
	});
}
