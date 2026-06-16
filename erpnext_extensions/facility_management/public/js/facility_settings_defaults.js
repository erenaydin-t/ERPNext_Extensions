// Copyright (c) 2026, ERPNext Extensions contributors

frappe.provide("erpnext_extensions");
frappe.provide("erpnext_extensions.facility_management.defaults");

const FACILITY_DEFAULT_FIELDS = [
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
	"cost_center",
	"department",
	"bank_dimension",
	"bank_account_dimension",
	"receipt_remarks_template",
	"repayment_remarks_template",
];

erpnext_extensions.facility_management.defaults.init_form = function (frm) {
	frm._facility_user_touched = frm._facility_user_touched || new Set();
	frm._facility_defaults_wired_fields =
		frm._facility_defaults_wired_fields || new Set();
	FACILITY_DEFAULT_FIELDS.forEach((fieldname) => {
		if (frm._facility_defaults_wired_fields.has(fieldname)) {
			return;
		}
		const field = frm.fields_dict[fieldname];
		if (!field?.$input) {
			return;
		}
		field.$input.on("change", () => {
			if (frm._facility_applying_defaults) {
				return;
			}
			frm._facility_user_touched.add(fieldname);
		});
		frm._facility_defaults_wired_fields.add(fieldname);
	});
};

erpnext_extensions.facility_management.defaults.apply_from_company = function (frm) {
	if (!frm.doc.company || !frm.doc.__islocal) {
		return;
	}
	erpnext_extensions.facility_management.defaults.init_form(frm);

	const fetchDefaults = () => {
		frappe.call({
			method:
				"erpnext_extensions.facility_management.doctype.facility.facility.get_facility_settings_defaults",
			args: { company: frm.doc.company },
			callback(r) {
				const payload = r.message || {};
				if (!payload.found) {
					frm._facility_defaults_applied_for_company = frm.doc.company;
					if (payload.message) {
						frappe.show_alert({ message: __(payload.message), indicator: "orange" }, 6);
					}
					return;
				}
				frm._facility_defaults_applied_for_company = frm.doc.company;
				frm._facility_applying_defaults = true;
				const tasks = [];
				Object.entries(payload.defaults || {}).forEach(([fieldname, value]) => {
					if (frm._facility_user_touched.has(fieldname)) {
						return;
					}
					if (frm.doc[fieldname]) {
						return;
					}
					tasks.push(frm.set_value(fieldname, value));
				});
				Promise.all(tasks).finally(() => {
					frm._facility_applying_defaults = false;
				});
			},
		});
	};

	const prevCompany = frm._facility_defaults_applied_for_company;
	if (prevCompany && prevCompany !== frm.doc.company) {
		frm._facility_applying_defaults = true;
		const clears = FACILITY_DEFAULT_FIELDS.filter(
			(fieldname) => !frm._facility_user_touched.has(fieldname) && frm.doc[fieldname]
		).map((fieldname) => frm.set_value(fieldname, ""));
		Promise.all(clears.length ? clears : [Promise.resolve()]).then(() => {
			frm._facility_applying_defaults = false;
			fetchDefaults();
		});
		return;
	}
	fetchDefaults();
};

frappe.ui.form.on("Facility", {
	onload(frm) {
		if (!frm.is_new()) {
			return;
		}
		erpnext_extensions.facility_management.defaults.init_form(frm);
		if (frm.doc.company) {
			erpnext_extensions.facility_management.defaults.apply_from_company(frm);
		}
	},
	refresh(frm) {
		if (!frm.is_new()) {
			return;
		}
		erpnext_extensions.facility_management.defaults.init_form(frm);
		if (frm.doc.company) {
			erpnext_extensions.facility_management.defaults.apply_from_company(frm);
		}
	},
	company(frm) {
		erpnext_extensions.facility_management.defaults.apply_from_company(frm);
	},
});
