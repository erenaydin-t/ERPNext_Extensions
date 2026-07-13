// Copyright (c) 2026, Farbod Siyahpoosh and contributors
// For license information, please see license.txt

frappe.ui.form.on("PM Holder", {
	setup(frm) {
		frm.set_query("default_employee_bank_account", () => {
			if (!frm.doc.employee) {
				return {
					query: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_employee_bank_account_query",
					filters: { employee: "", company: frm.doc.company || "" },
				};
			}
			return {
				query: "erpnext_extensions.petty_management.doctype.pm_request.pm_request.get_employee_bank_account_query",
				filters: { employee: frm.doc.employee, company: frm.doc.company || "" },
			};
		});
	},
	employee(frm) {
		frm.set_value("default_employee_bank_account", null);
		frm.trigger("sync_default_employee_bank_account");
	},
	company(frm) {
		frm.set_value("default_employee_bank_account", null);
		frm.trigger("sync_default_employee_bank_account");
	},
	sync_default_employee_bank_account(frm) {
		if (!frm.doc.employee || !frm.doc.company) {
			return;
		}
		const filters = {
			party_type: "Employee",
			party: frm.doc.employee,
			disabled: 0,
			docstatus: ["!=", 2],
		};
		if (frappe.meta.has_field("Bank Account", "company")) {
			filters.company = frm.doc.company;
		}
		frappe.db
			.get_list("Bank Account", { filters, fields: ["name"], limit: 2 })
			.then((rows) => {
				if (rows.length === 1) {
					frm.set_value("default_employee_bank_account", rows[0].name);
				}
			});
	},
	refresh(frm) {
		if (!frm.is_new()) {
			frm.add_custom_button(__("Refresh balances"), () => {
				frm.reload_doc();
			});
		}
		frm.trigger("sync_default_employee_bank_account");
	},
});
