# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Unit tests for v4.6.1 E1 GL account-tree narrowing."""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import frappe

from erpnext_extensions.iran_accounting.account_explorer.e1_gl_scope import resolve_narrowed_gl_accounts


class TestE1GlScope(unittest.TestCase):
	def test_full_company_returns_none(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not company:
			self.skipTest("no company")
		all_names = frappe.get_all("Account", filters={"company": company}, pluck="name")
		spec = SimpleNamespace(company=company, included_account_names=list(all_names))
		self.assertIsNone(resolve_narrowed_gl_accounts(spec))

	def test_subset_returns_names(self):
		company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_value(
			"Company", {}, "name"
		)
		if not company:
			self.skipTest("no company")
		all_names = frappe.get_all("Account", filters={"company": company}, pluck="name")
		if len(all_names) < 2:
			self.skipTest("need 2+ accounts")
		subset = all_names[:1]
		spec = SimpleNamespace(company=company, included_account_names=subset)
		self.assertEqual(resolve_narrowed_gl_accounts(spec), subset)
