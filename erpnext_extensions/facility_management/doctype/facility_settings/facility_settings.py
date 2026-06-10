# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.facility_management.facility_settings_doc import (
	populate_facility_settings_template_defaults,
)


class FacilitySettings(Document):
	def before_insert(self):
		populate_facility_settings_template_defaults(self)

	def validate(self):
		existing = frappe.db.get_value(
			"Facility Settings",
			{"company": self.company, "name": ("!=", self.name)},
			"name",
		)
		if existing:
			frappe.throw(_("Facility Settings already exists for company {0}.").format(self.company))
