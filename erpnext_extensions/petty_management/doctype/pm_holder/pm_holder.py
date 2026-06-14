# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.petty_management.services.holder_service import validate_holder


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pm_holder_query(doctype, txt, searchfield, start, page_len, filters):
	from erpnext_extensions.petty_management.services.holder_display import pm_holder_query as _query

	return _query(doctype, txt, searchfield, start, page_len, filters)


class PMHolder(Document):
	def autoname(self):
		if not self.employee or not self.company:
			frappe.throw(_("Employee and Company are required before naming"))
		base = f"{self.employee}-{self.company}"
		if len(base) > 120:
			base = base[:120]
		self.name = base

	def get_title(self):
		from erpnext_extensions.petty_management.services.holder_display import format_pm_holder_title

		return format_pm_holder_title(self.employee_name, self.employee, self.name)

	def validate(self):
		validate_holder(self)
