# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_member_tuple_filter,
	apply_opening_entry_filters,
	apply_scoped_gle_filters,
	collect_scope_warnings,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	_load_settings_defaults,
	build_document_scope,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import (
	AccountExplorerQuerySpec,
	AnalysisContext,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	default_document_scope,
	enable_account_explorer,
	require_site,
)


class TestAccountExplorerGleFilters(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_account_explorer()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def _spec(self, **overrides) -> AccountExplorerQuerySpec:
		account = frappe.db.get_value("Account", {"company": self.company}, "name")
		document_raw = default_document_scope(
			self.company, self.fiscal_year, self.from_date, self.to_date
		)
		status_overrides = {}
		if "include_opening_entries" in overrides:
			status_overrides["include_opening_entries"] = overrides.pop("include_opening_entries")
		if "include_cancelled_entries" in overrides:
			status_overrides["include_cancelled_entries"] = overrides.pop("include_cancelled_entries")
		if status_overrides:
			document_raw["status"] = {**document_raw["status"], **status_overrides}
		document_scope = build_document_scope(document_raw, _load_settings_defaults())
		spec = AccountExplorerQuerySpec(
			document_scope=document_scope,
			analysis=AnalysisContext(),
			included_account_names=[account] if account else [],
		)
		for key, value in overrides.items():
			setattr(spec, key, value)
		return spec

	def test_opening_entries_excluded_warning(self):
		spec = self._spec(include_opening_entries=False)
		warnings = collect_scope_warnings(spec)
		self.assertTrue(any("Opening entries" in warning for warning in warnings))

	def test_cancelled_filter_applied(self):
		gle = frappe.qb.DocType("GL Entry")
		spec = self._spec(include_cancelled_entries=False)
		query = apply_scoped_gle_filters(frappe.qb.from_(gle).select(gle.name), gle, spec)
		sql = query.get_sql()
		self.assertIn("is_cancelled", sql.lower())

	def test_opening_entry_filter_excludes_opening_by_default(self):
		gle = frappe.qb.DocType("GL Entry")
		spec = self._spec(include_opening_entries=False)
		query = apply_opening_entry_filters(
			frappe.qb.from_(gle).select(gle.name).where(gle.company == self.company),
			gle,
			spec,
		)
		sql = query.get_sql()
		self.assertIn("is_opening", sql.lower())

	def test_member_tuple_filter_applied(self):
		gle = frappe.qb.DocType("GL Entry")
		spec = self._spec(resolved_member_tuples=[("Customer", "CUST-0001")])
		query = apply_scoped_gle_filters(frappe.qb.from_(gle).select(gle.name), gle, spec)
		sql = query.get_sql()
		self.assertIn("party_type", sql.lower())
		self.assertIn("party", sql.lower())

	def test_empty_member_tuple_filter_matches_nothing(self):
		gle = frappe.qb.DocType("GL Entry")
		query = frappe.qb.from_(gle).select(gle.name)
		query = apply_member_tuple_filter(query, gle, [])
		sql = query.get_sql()
		self.assertIn("name", sql.lower())
