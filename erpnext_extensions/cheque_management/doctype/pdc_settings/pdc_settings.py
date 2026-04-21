# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class PDCSettings(Document):
	def validate(self):
		if not self.company:
			frappe.throw("Company is required")
