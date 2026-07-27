# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Unit tests: safe party display resolver for Voucher Summary / GL / Print."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe

from erpnext_extensions.iran_accounting.account_explorer.party_sources import (
	PARTY_DISPLAY_FIELD_MAP,
	resolve_party_display_name,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import _party_name
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import require_site


class TestAccountExplorerPartyResolver(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.company = require_site(self)
		_party_name._cache = {}

	def test_customer_returns_customer_name(self):
		name = frappe.db.get_value("Customer", {}, "name", order_by="creation asc")
		if not name:
			self.skipTest("No Customer")
		expected = frappe.db.get_value("Customer", name, "customer_name") or name
		self.assertEqual(resolve_party_display_name("Customer", name), expected)
		self.assertEqual(_party_name("Customer", name), expected)

	def test_supplier_returns_supplier_name(self):
		name = frappe.db.get_value("Supplier", {}, "name", order_by="creation asc")
		if not name:
			self.skipTest("No Supplier")
		expected = frappe.db.get_value("Supplier", name, "supplier_name") or name
		self.assertEqual(resolve_party_display_name("Supplier", name), expected)
		self.assertEqual(_party_name("Supplier", name), expected)

	def test_employee_returns_employee_name(self):
		name = frappe.db.get_value("Employee", {}, "name", order_by="creation asc")
		if not name:
			self.skipTest("No Employee")
		expected = frappe.db.get_value("Employee", name, "employee_name") or name
		self.assertEqual(resolve_party_display_name("Employee", name), expected)
		self.assertEqual(_party_name("Employee", name), expected)

	def test_shareholder_returns_title(self):
		self.assertEqual(PARTY_DISPLAY_FIELD_MAP["Shareholder"], "title")
		meta = frappe.get_meta("Shareholder")
		self.assertTrue(meta.has_field("title"))
		self.assertFalse(meta.has_field("shareholder_name"))

		name = frappe.db.get_value("Shareholder", {}, "name", order_by="creation asc")
		if not name:
			doc = frappe.get_doc(
				{
					"doctype": "Shareholder",
					"title": "AE Resolver Shareholder",
					"company": self.company,
				}
			)
			doc.flags.ignore_permissions = True
			doc.insert()
			name = doc.name
			frappe.db.commit()
		expected = frappe.db.get_value("Shareholder", name, "title") or name
		self.assertEqual(resolve_party_display_name("Shareholder", name), expected)
		self.assertEqual(_party_name("Shareholder", name), expected)

	def test_unknown_party_type_returns_fallback_id(self):
		self.assertEqual(resolve_party_display_name("MadeUpPartyType", "PARTY-ID-1"), "PARTY-ID-1")
		self.assertEqual(_party_name("MadeUpPartyType", "PARTY-ID-1"), "PARTY-ID-1")

	def test_invalid_field_does_not_raise_sql_error(self):
		"""Even if a preferred field were wrong, has_field must prevent SQL errors."""
		name = frappe.db.get_value("Shareholder", {}, "name", order_by="creation asc")
		if not name:
			self.skipTest("No Shareholder")
		# Simulate old buggy field map: must not hit SQL with shareholder_name.
		with patch.dict(
			"erpnext_extensions.iran_accounting.account_explorer.party_sources.PARTY_DISPLAY_FIELD_MAP",
			{"Shareholder": "shareholder_name"},
			clear=False,
		):
			# Preferred field missing → fallback to party id (no OperationalError).
			value = resolve_party_display_name("Shareholder", name)
			self.assertEqual(value, name)
		# Real map still returns title
		title = frappe.db.get_value("Shareholder", name, "title") or name
		self.assertEqual(resolve_party_display_name("Shareholder", name), title)

	def test_empty_inputs(self):
		self.assertEqual(resolve_party_display_name("", "x"), "")
		self.assertEqual(resolve_party_display_name("Customer", ""), "")
		self.assertEqual(_party_name("", "x"), "")
		self.assertEqual(_party_name("Customer", ""), "")
