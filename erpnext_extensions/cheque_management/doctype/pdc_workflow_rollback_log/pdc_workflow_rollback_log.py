# Copyright (c) 2026, ERPNext Extensions contributors

import frappe
from frappe import _
from frappe.model.document import Document


class PDCWorkflowRollbackLog(Document):
	def validate(self):
		if not self.is_new() and not getattr(frappe.flags, "in_pdc_workflow_rollback", None):
			frappe.throw(_("Workflow rollback audit entries cannot be modified."))

	def on_trash(self):
		frappe.throw(_("Workflow rollback audit entries cannot be deleted."))
