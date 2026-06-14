# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.exceptions import QueryTimeoutError
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from erpnext_extensions.petty_management.services.opening_advance_service import (
	enforce_immutable_submitted_amounts,
	opening_advance_has_reserving_clearances,
	stamp_opening_advance_display_balances,
	sync_opening_advance_from_holder,
	validate_opening_advance_amounts,
)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def pm_opening_advance_link_query(doctype, txt, searchfield, start, page_len, filters):
	from erpnext_extensions.petty_management.services.opening_advance_service import (
		pm_opening_advance_query_for_link,
	)

	return pm_opening_advance_query_for_link(doctype, txt, searchfield, start, page_len, filters)


class PMOpeningAdvance(Document):
	def autoname(self):
		try:
			self.name = make_autoname("PM-OPA-.YYYY.-.MM.-.#####", doc=self)
		except QueryTimeoutError:
			frappe.throw(
				_("PM Opening Advance numbering is busy. Please try again."),
				title=_("Please try again"),
			)

	def validate(self):
		if not self.holder:
			frappe.throw(_("PM Holder is required"))
		sync_opening_advance_from_holder(self)
		validate_opening_advance_amounts(self)
		enforce_immutable_submitted_amounts(self)
		if self.docstatus == 0:
			self.status = "Draft"
		stamp_opening_advance_display_balances(self)

	def before_submit(self):
		return

	def on_submit(self):
		self.status = "Submitted"
		self.db_set("status", "Submitted", update_modified=False)

	def on_cancel(self):
		if opening_advance_has_reserving_clearances(self.name):
			frappe.throw(
				_("Cannot cancel: submitted PM Clearances still reserve this opening balance."),
				title=_("Opening advance in use"),
			)
		self.status = "Cancelled"
		self.db_set("status", "Cancelled", update_modified=False)
