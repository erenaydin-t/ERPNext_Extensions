# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""v4.6.2 — scoped E1 period GL must not FORCE INDEX(posting_date_company_index)."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from erpnext_extensions.iran_accounting.account_explorer.opening_balance import (
	_set_period_gl_entries_for_e1,
)


class _Cmp:
	"""Minimal stand-in so PyPika-style field comparisons succeed under mocks."""

	def __eq__(self, other):
		return self

	def __ne__(self, other):
		return self

	def __le__(self, other):
		return self

	def __lt__(self, other):
		return self

	def __ge__(self, other):
		return self

	def __gt__(self, other):
		return self

	def __and__(self, other):
		return self

	def __or__(self, other):
		return self

	def isin(self, other):
		return self

	def as_(self, name):
		return self


class TestE1ScopedPeriodIndex(unittest.TestCase):
	def test_restricted_period_query_skips_force_index(self):
		"""Account-scoped E1 period path must let the optimizer pick account index."""
		spec = SimpleNamespace(
			company="Test Company",
			from_date="2026-03-21",
			to_date="2027-03-20",
			include_period_closing_vouchers=0,
		)
		filters = SimpleNamespace(company="Test Company")
		gl_entries_by_account: dict = {}
		restrict_accounts = ["Leaf Account - TC"]

		fake_query = MagicMock(name="qb_query")
		fake_query.select.return_value = fake_query
		fake_query.where.return_value = fake_query
		fake_query.groupby.return_value = fake_query
		fake_query.force_index.return_value = fake_query
		fake_query.run.return_value = []

		fake_from = MagicMock(return_value=fake_query)
		fake_doctype = MagicMock(return_value=SimpleNamespace(
			account=_Cmp(),
			debit=_Cmp(),
			credit=_Cmp(),
			debit_in_account_currency=_Cmp(),
			credit_in_account_currency=_Cmp(),
			account_currency=_Cmp(),
			posting_date=_Cmp(),
			is_opening=_Cmp(),
			fiscal_year=_Cmp(),
			company=_Cmp(),
			is_cancelled=_Cmp(),
		))

		with (
			patch("frappe.qb.from_", fake_from),
			patch("frappe.qb.DocType", fake_doctype),
			patch(
				"erpnext_extensions.iran_accounting.account_explorer.opening_balance.Sum",
				side_effect=lambda field: field,
			),
			patch(
				"erpnext_extensions.iran_accounting.account_explorer.opening_balance.apply_additional_conditions",
				side_effect=lambda *a, **k: fake_query,
			),
			patch(
				"frappe.desk.reportview.build_match_conditions",
				return_value="",
			),
		):
			_set_period_gl_entries_for_e1(
				spec,
				filters,
				gl_entries_by_account,
				restrict_accounts=restrict_accounts,
			)

		fake_query.force_index.assert_not_called()
		fake_query.run.assert_called_once()

	def test_unrestricted_period_uses_erpnext_helper(self):
		"""Root E1 keeps ERPNext set_gl_entries_by_account (date/company force index)."""
		spec = SimpleNamespace(
			company="Test Company",
			from_date="2026-03-21",
			to_date="2027-03-20",
			include_period_closing_vouchers=0,
		)
		filters = SimpleNamespace(company="Test Company")
		gl_entries_by_account: dict = {}

		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.opening_balance.set_gl_entries_by_account"
		) as set_gl:
			_set_period_gl_entries_for_e1(
				spec,
				filters,
				gl_entries_by_account,
				restrict_accounts=None,
			)
			set_gl.assert_called_once()

	def test_source_omits_force_index_on_scoped_path(self):
		import inspect

		from erpnext_extensions.iran_accounting.account_explorer import opening_balance as ob

		src = inspect.getsource(ob._set_period_gl_entries_for_e1)
		self.assertNotIn("force_index", src)
		self.assertIn("restrict_accounts", src)
		self.assertIn("set_gl_entries_by_account", src)
