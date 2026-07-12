# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.iran_accounting.account_explorer.constants import NATIVE_PARTY_TYPES


class IranAccountingSettings(Document):
	def validate(self):
		self._validate_levels()
		self._validate_party_sources()
		self._validate_identifier_fields()
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

	def _validate_party_sources(self):
		seen_types = set()
		for row in self.account_explorer_party_sources or []:
			if row.party_type not in NATIVE_PARTY_TYPES:
				frappe.throw(_("Unsupported party type {0}.").format(row.party_type))
			if not row.enabled:
				continue
			if row.party_type in seen_types:
				frappe.throw(_("Duplicate enabled party type {0}.").format(row.party_type))
			seen_types.add(row.party_type)

	def _validate_identifier_fields(self):
		for row in self.account_explorer_party_sources or []:
			if not row.identifier_field:
				continue
			meta = frappe.get_meta(row.party_type)
			if not meta.has_field(row.identifier_field):
				frappe.throw(
					_("Identifier field {0} does not exist on {1}.").format(
						row.identifier_field, row.party_type
					)
				)

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
			) or self.has_value_changed("party_analysis_enabled") or self.has_value_changed(
				"dimension_analysis_enabled"
			) or self.has_value_changed("voucher_analysis_enabled") or self.has_value_changed(
				"account_explorer_party_sources"
			):
				self.metadata_cache_version = int(previous) + 1
