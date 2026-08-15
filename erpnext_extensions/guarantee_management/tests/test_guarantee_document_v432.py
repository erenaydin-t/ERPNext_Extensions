# Copyright (c) 2026, ERPNext Extensions contributors
"""Regression tests for Guarantee Document List View v4.3.2."""

from __future__ import annotations

import os
import unittest

import frappe

from erpnext_extensions.guarantee_management.services.party_display import (
	batch_resolve_party_displays,
)
from erpnext_extensions.guarantee_management.services.possession import get_held_by_label


REQUIRED_LIST_FIELDS = (
	"document_no",
	"status",
	"guarantee_direction",
	"party_type",
	"party",
	"guarantee_type",
	"amount",
	"expiry_date",
)


class TestGuaranteeDocumentListViewV432(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		if os.environ.get("CI") and not frappe.db.exists("DocType", "Guarantee Document"):
			raise unittest.SkipTest("Guarantee Document not installed")
		if not frappe.db.exists("DocType", "Guarantee Document"):
			raise unittest.SkipTest("Guarantee Document not installed")

	def test_g01_listview_settings_has_no_default_filters(self):
		"""G01: list JS must not declare automatic filters (empty ID / Status, etc.)."""
		path = frappe.get_app_path(
			"erpnext_extensions",
			"guarantee_management",
			"doctype",
			"guarantee_document",
			"guarantee_document_list.js",
		)
		source = open(path, encoding="utf-8").read()
		self.assertIn("filters: []", source)
		self.assertNotIn('filters: [["status"', source)
		self.assertNotIn('filters: [["Status"', source)
		self.assertIn("gd_sanitize_filter_tuples", source)
		self.assertIn("gd_bind_invalid_empty_filter_cleanup", source)
		# List formatters must return escaped HTML — plain text with "(" breaks Frappe $(column_html).
		self.assertIn("frappe.utils.escape_html", source)
		self.assertIn("party(value, df, doc)", source)

	def test_g02_no_default_status_active_filter(self):
		"""G02: no Status = Active default filter in list settings."""
		path = frappe.get_app_path(
			"erpnext_extensions",
			"guarantee_management",
			"doctype",
			"guarantee_document",
			"guarantee_document_list.js",
		)
		source = open(path, encoding="utf-8").read()
		# Explicit empty filters array; no Status default in settings.
		self.assertRegex(source, r"filters:\s*\[\s*\]")
		self.assertNotIn('["status", "=", "Active"]', source)
		self.assertNotIn('["Status", "=", "Active"]', source)
		self.assertNotIn("status,=,Active", source.split("get_indicator")[0])

	def test_g03_company_not_default_list_column(self):
		"""G03: Company must not be a default List View column."""
		meta = frappe.get_meta("Guarantee Document")
		company = meta.get_field("company")
		self.assertIsNotNone(company)
		self.assertFalse(cint_bool(company.in_list_view))

	def test_g04_company_remains_standard_filter(self):
		"""G04: Company remains available as a standard filter."""
		meta = frappe.get_meta("Guarantee Document")
		company = meta.get_field("company")
		self.assertTrue(cint_bool(company.in_standard_filter))

	def test_g05_required_list_fields_available(self):
		"""G05: intended default list fields remain in_list_view (or title/indicator)."""
		meta = frappe.get_meta("Guarantee Document")
		self.assertEqual(meta.title_field, "document_no")
		for fieldname in REQUIRED_LIST_FIELDS:
			df = meta.get_field(fieldname)
			self.assertIsNotNone(df, fieldname)
			if fieldname == "document_no":
				# title_field becomes Subject column
				continue
			if fieldname == "status":
				# rendered via indicator when present
				continue
			self.assertTrue(cint_bool(df.in_list_view), fieldname)

	def test_g06_guarantee_direction_semantics(self):
		"""G06: guarantee_direction remains Received / Issued."""
		meta = frappe.get_meta("Guarantee Document")
		df = meta.get_field("guarantee_direction")
		options = (df.options or "").split("\n")
		self.assertEqual(options, ["Received", "Issued"])

	def test_g07_held_by_presentation(self):
		"""G07: Held By presentation remains derived only."""
		self.assertEqual(get_held_by_label("Active", "Received"), "Held by Us")
		self.assertEqual(get_held_by_label("Active", "Issued"), "Held by Others")
		self.assertEqual(get_held_by_label("Draft", "Received"), "—")
		meta = frappe.get_meta("Guarantee Document")
		self.assertFalse(meta.has_field("held_by"))

	def test_g08_party_batch_display(self):
		"""G08: batch party display still resolves."""
		resolved = batch_resolve_party_displays(
			[{"party_type": "Other", "party": "", "other_party_name": "طرف تست"}]
		)
		self.assertEqual(resolved.get("Other::طرف تست"), "طرف تست")

	def test_g09_bank_party_type_option(self):
		"""G09: Bank remains a Party Type option."""
		meta = frappe.get_meta("Guarantee Document")
		options = (meta.get_field("party_type").options or "").split("\n")
		self.assertIn("Bank", options)
		self.assertTrue(meta.has_field("issuing_bank"))
		issuing = meta.get_field("issuing_bank")
		self.assertEqual(issuing.options, "Bank")
		self.assertFalse(cint_bool(issuing.in_list_view))

	def test_g10_guarantee_position_summary_report_exists(self):
		"""G10: Guarantee Position Summary remains available."""
		self.assertTrue(frappe.db.exists("Report", "Guarantee Position Summary"))
		from erpnext_extensions.guarantee_management.report.guarantee_position_summary import (
			guarantee_position_summary as report,
		)

		self.assertTrue(callable(report.execute))


def cint_bool(value) -> bool:
	return bool(int(value or 0))
