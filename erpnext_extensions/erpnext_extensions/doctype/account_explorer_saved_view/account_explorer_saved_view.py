# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


class AccountExplorerSavedView(Document):
	def validate(self):
		from erpnext_extensions.iran_accounting.account_explorer.saved_views import validate_saved_view_configuration

		validate_saved_view_configuration(
			self.document_scope,
			self.analysis_context,
			self.presentation,
		)
