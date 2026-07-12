# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer.gle_filters import (
	apply_opening_entry_filters,
	apply_scoped_gle_filters,
	collect_scope_warnings,
)
from erpnext_extensions.iran_accounting.account_explorer.schemas import AccountExplorerQuerySpec
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
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
		spec = AccountExplorerQuerySpec(
			company=self.company,
			from_date=self.from_date,
			to_date=self.to_date,
			fiscal_year=self.fiscal_year,
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
