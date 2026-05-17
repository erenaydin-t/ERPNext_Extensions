# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.petty_management.services.holder_service import validate_holder


class PMHolder(Document):
	def autoname(self):
		if not self.employee or not self.company:
			frappe.throw(_("Employee and Company are required before naming"))
		base = f"{self.employee}-{self.company}"
		if len(base) > 120:
			base = base[:120]
		self.name = base

	def validate(self):
		validate_holder(self)
