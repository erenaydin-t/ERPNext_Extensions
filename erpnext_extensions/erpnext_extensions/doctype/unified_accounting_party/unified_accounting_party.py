# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	get_party_display_title,
	get_party_identifier,
	get_party_source_config,
)
from erpnext_extensions.iran_accounting.account_explorer.unified_party_registry import (
	validate_member_uniqueness,
	validate_unified_name_uniqueness,
)


class UnifiedAccountingParty(Document):
	def validate(self):
		self._validate_status_and_members()
		self._populate_member_fields()
		self._validate_member_uniqueness()
		self._validate_unified_name()
		self._validate_member_company_consistency()
		self._set_summary_fields()

	def _validate_status_and_members(self):
		if self.status == "Active" and not self.members:
			frappe.throw(_("At least one member is required for an Active Unified Accounting Party."))

	def _populate_member_fields(self):
		primary_count = 0
		for row in self.members or []:
			if not row.party_type or not row.party:
				continue
			if not frappe.db.exists(row.party_type, row.party):
				frappe.throw(_("Party {0} {1} does not exist.").format(row.party_type, row.party))
			source = get_party_source_config(row.party_type)
			if not source or not source.show_in_unified_party:
				frappe.throw(
					_("Party type {0} is not enabled for Unified Accounting Party.").format(row.party_type)
				)
			row.party_display_name = get_party_display_title(row.party_type, row.party)
			row.identifier_value = get_party_identifier(
				row.party_type, row.party, source.identifier_field if source else None
			)
			if row.is_primary:
				primary_count += 1
		if primary_count > 1:
			frappe.throw(_("Only one member can be marked as primary."))

	def _validate_member_uniqueness(self):
		if self.status != "Active":
			return
		for row in self.members or []:
			validate_member_uniqueness(
				row.party_type,
				row.party,
				company=self.company,
				exclude_uap=self.name if not self.is_new() else None,
			)

	def _validate_unified_name(self):
		if self.status != "Active":
			return
		validate_unified_name_uniqueness(self.unified_name, exclude_uap=self.name if not self.is_new() else None)

	def _validate_member_company_consistency(self):
		if not self.company:
			return
		for row in self.members or []:
			self._validate_single_member_company(row.party_type, row.party)

	def _validate_single_member_company(self, party_type: str, party: str):
		if party_type == "Employee":
			employee_company = frappe.db.get_value("Employee", party, "company")
			if employee_company and employee_company != self.company:
				frappe.throw(
					_("Employee {0} belongs to company {1}, which does not match Unified Accounting Party company {2}.").format(
						party, employee_company, self.company
					)
				)
			return

		has_gl = frappe.db.exists(
			"GL Entry",
			{"company": self.company, "party_type": party_type, "party": party, "is_cancelled": 0},
		)
		if not has_gl:
			frappe.throw(
				_("Party {0} {1} has no GL activity in company {2}.").format(party_type, party, self.company)
			)

	def _set_summary_fields(self):
		self.member_count = len(self.members or [])
		primary = next((row for row in self.members or [] if row.is_primary), None)
		if not primary and self.members:
			primary = self.members[0]
		self.primary_identifier = primary.identifier_value if primary else None
