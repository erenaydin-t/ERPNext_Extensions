# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class FacilityType(Document):
	def validate(self):
		if not (self.facility_type_name or "").strip():
			frappe.throw(_("Facility Type Name is required."))
