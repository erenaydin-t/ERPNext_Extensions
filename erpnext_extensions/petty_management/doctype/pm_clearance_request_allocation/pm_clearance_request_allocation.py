# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe.exceptions import QueryTimeoutError
from frappe.model.document import Document

from erpnext_extensions.petty_management.services.clearance_lock_diagnostics import (
	log_pm_clearance_lock_diagnostics,
)


class PMClearanceRequestAllocation(Document):
	def db_insert(self, *args, **kwargs):
		frappe.logger("pm_clearance").info(
			"PM Clearance Request Allocation db_insert parent=%s idx=%s",
			getattr(self, "parent", None),
			getattr(self, "idx", None),
		)
		try:
			return super().db_insert(*args, **kwargs)
		except QueryTimeoutError:
			log_pm_clearance_lock_diagnostics(
				phase="db_insert_tabPM Clearance Request Allocation",
				last_sql=getattr(frappe.db, "last_query", None),
			)
			raise
