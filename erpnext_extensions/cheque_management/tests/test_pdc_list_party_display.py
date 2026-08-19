# Copyright (c) 2026, ERPNext Extensions contributors
"""PDC list Party title display (v4.4.5)."""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.guarantee_management.services.party_display import (
	batch_resolve_party_displays,
	format_party_title,
)


class TestPDCListPartyEnhancement(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		if not frappe.db.exists("DocType", "Post Dated Cheque"):
			raise unittest.SkipTest("Post Dated Cheque not installed")

	def test_party_type_and_party_are_list_columns(self):
		meta = frappe.get_meta("Post Dated Cheque")
		party_type = meta.get_field("party_type")
		party = meta.get_field("party")
		self.assertTrue(party_type.in_list_view)
		self.assertTrue(party_type.in_standard_filter)
		self.assertTrue(party.in_list_view)
		self.assertTrue(party.in_standard_filter)
		self.assertEqual(party.fieldtype, "Dynamic Link")
		self.assertEqual(party.options, "party_type")

	def test_company_not_default_list_column(self):
		meta = frappe.get_meta("Post Dated Cheque")
		company = meta.get_field("company")
		self.assertIsNotNone(company)
		self.assertFalse(bool(int(company.in_list_view or 0)))
		self.assertTrue(bool(int(company.in_standard_filter or 0)))

	def test_list_js_batch_resolves_party_title(self):
		path = frappe.get_app_path(
			"erpnext_extensions",
			"cheque_management",
			"doctype",
			"post_dated_cheque",
			"post_dated_cheque_list.js",
		)
		src = open(path, encoding="utf-8").read()
		self.assertIn("formatters", src)
		self.assertIn("party(value, df, doc)", src)
		self.assertIn("pdc_batch_resolve_party_displays", src)
		self.assertIn("batch_resolve_party_displays_for_list", src)
		self.assertIn("pdc_strip_company_from_list_columns", src)
		self.assertIn("frappe.utils.escape_html", src)
		self.assertNotIn("partyType ? `${partyType} - ${code}`", src)

	def test_form_js_sets_party_description(self):
		path = frappe.get_app_path(
			"erpnext_extensions",
			"cheque_management",
			"doctype",
			"post_dated_cheque",
			"post_dated_cheque.js",
		)
		src = open(path, encoding="utf-8").read()
		self.assertIn("pdc_set_party_description", src)
		self.assertIn("batch_resolve_party_displays_for_list", src)

	def test_no_denormalized_party_display_field(self):
		meta = frappe.get_meta("Post Dated Cheque")
		self.assertFalse(meta.has_field("party_display"))
		self.assertFalse(meta.has_field("party_name_display"))

	def test_historical_party_fields_are_stored_on_doctype(self):
		meta = frappe.get_meta("Post Dated Cheque")
		self.assertTrue(meta.has_field("party"))
		self.assertTrue(meta.has_field("party_type"))
		self.assertIn("Customer", (meta.get_field("party_type").options or "").split("\n"))
		self.assertIn("Supplier", (meta.get_field("party_type").options or "").split("\n"))

	def test_format_party_title_returns_name_only(self):
		self.assertEqual(
			format_party_title("Customer", "CUS-00003", title="شرکت میلان"),
			"شرکت میلان",
		)
		self.assertEqual(
			format_party_title("Supplier", "SUP-00724", title="تامین کننده نمونه"),
			"تامین کننده نمونه",
		)
		self.assertEqual(
			format_party_title("Employee", "HR-EMP-0211", title="Ali Ahmadi"),
			"Ali Ahmadi",
		)
		self.assertEqual(format_party_title("Customer", "CUS-00003", title=""), "CUS-00003")

	def test_batch_resolve_returns_title_not_composite(self):
		customer = frappe.db.get_value("Customer", {}, "name")
		if not customer:
			self.skipTest("No Customer in database")
		title = frappe.db.get_value("Customer", customer, "customer_name")
		resolved = batch_resolve_party_displays([{"party_type": "Customer", "party": customer}])
		self.assertEqual(resolved[f"Customer::{customer}"], format_party_title("Customer", customer, title=title))
		if title and title != customer:
			self.assertNotIn(" - ", resolved[f"Customer::{customer}"])
