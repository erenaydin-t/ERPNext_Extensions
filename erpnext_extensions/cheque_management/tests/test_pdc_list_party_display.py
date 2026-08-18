# Copyright (c) 2026, ERPNext Extensions contributors
"""PDC list Party Type / Party display (v4.4.4)."""

from __future__ import annotations

import unittest

import frappe
from frappe.tests.utils import FrappeTestCase


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

	def test_list_js_formats_party_as_type_dash_code(self):
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
		self.assertIn("partyType ? `${partyType} - ${code}`", src)
		self.assertIn("frappe.utils.escape_html", src)

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
