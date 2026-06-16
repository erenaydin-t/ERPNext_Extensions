# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe


class TestFacilityDimensionFieldtypes(unittest.TestCase):
	def test_facility_settings_dimension_links(self) -> None:
		meta = frappe.get_meta("Facility Settings")
		expect = {
			"default_department": "Department",
			"default_bank_dimension": "Bank",
			"default_bank_account_dimension": "Bank Account",
		}
		for fn, options in expect.items():
			df = meta.get_field(fn)
			self.assertEqual(df.fieldtype, "Link", fn)
			self.assertEqual(df.options, options, fn)

	def test_facility_dimension_links(self) -> None:
		meta = frappe.get_meta("Facility")
		expect = {
			"department": "Department",
			"bank_dimension": "Bank",
			"bank_account_dimension": "Bank Account",
		}
		for fn, options in expect.items():
			df = meta.get_field(fn)
			self.assertEqual(df.fieldtype, "Link", fn)
			self.assertEqual(df.options, options, fn)
