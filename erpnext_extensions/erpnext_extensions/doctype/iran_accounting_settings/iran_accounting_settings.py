# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class IranAccountingSettings(Document):
	def validate(self):
		self._validate_levels()
		self._bump_cache_version()

	def _validate_levels(self):
		seen_lengths = set()
		for row in self.account_explorer_levels or []:
			if not row.enabled:
				continue
			if row.code_length in seen_lengths:
				frappe.throw(
					_("Duplicate code length {0} in Account Explorer levels.").format(row.code_length)
				)
			seen_lengths.add(row.code_length)

	def _bump_cache_version(self):
		if not self.is_new():
			previous = (
				frappe.db.get_value(
					"Iran Accounting Settings", "Iran Accounting Settings", "metadata_cache_version"
				)
				or 1
			)
			if self.has_value_changed("account_explorer_levels") or self.has_value_changed(
				"account_explorer_enabled"
			):
				self.metadata_cache_version = int(previous) + 1
