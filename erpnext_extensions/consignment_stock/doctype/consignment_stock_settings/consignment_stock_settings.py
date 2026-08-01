# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class ConsignmentStockSettings(Document):
	def validate(self):
		existing = frappe.db.get_value(
			"Consignment Stock Settings",
			{"company": self.company, "name": ("!=", self.name)},
			"name",
		)
		if existing:
			frappe.throw(_("Consignment Stock Settings already exists for company {0}.").format(self.company))

		from erpnext_extensions.consignment_stock.accounting import validate_settings_accounts

		validate_settings_accounts(self)
