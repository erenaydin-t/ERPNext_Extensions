# Copyright (c) 2026, ERPNext Extensions contributors

import frappe
from frappe import _
from frappe.model.document import Document


class PDCLifecycleEvent(Document):
	def validate(self):
		if self.is_new():
			return
		if getattr(frappe.flags, "in_pdc_workflow_rollback", None):
			return
		frappe.throw(_("PDC lifecycle events cannot be modified."))

	def on_trash(self):
		if getattr(frappe.flags, "in_pdc_workflow_rollback", None):
			frappe.throw(_("PDC lifecycle events cannot be deleted during rollback."))
		frappe.throw(_("PDC lifecycle events cannot be deleted."))
