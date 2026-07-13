# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_account_explorer,
	enable_wave2a_analysis,
	require_site,
)


class TestAccountExplorerAxisPermissions(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_party_axis_blocked_when_disabled(self):
		enable_account_explorer()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.party_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "party"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_party_summary(payload)

	def test_dimension_axis_blocked_when_disabled(self):
		enable_account_explorer()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.dimension_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_dimension_summary(payload)

	def test_metadata_includes_wave2a_axes(self):
		enable_wave2a_analysis()
		meta = api.get_metadata()
		axis_ids = {axis["id"] for axis in meta.get("axes", [])}
		self.assertIn("party", axis_ids)
		self.assertIn("dimension", axis_ids)
		self.assertTrue(meta.get("party_sources"))

	def test_voucher_axis_blocked_when_disabled(self):
		enable_account_explorer()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.voucher_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_voucher_summary(payload)

	def test_metadata_includes_voucher_axis_when_enabled(self):
		from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import enable_wave2b_voucher

		enable_wave2b_voucher()
		meta = api.get_metadata()
		axis_ids = {axis["id"] for axis in meta.get("axes", [])}
		self.assertIn("voucher", axis_ids)
		self.assertTrue(meta.get("voucher_analysis_enabled"))

	def test_unified_party_axis_blocked_when_disabled(self):
		enable_wave2a_analysis()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.unified_party_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "unified_party"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_unified_party_summary(payload)

	def test_unified_party_requires_party_analysis(self):
		enable_account_explorer()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.party_analysis_enabled = 0
		settings.unified_party_enabled = 1
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "unified_party"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_unified_party_summary(payload)

	def test_metadata_includes_unified_party_axis_when_enabled(self):
		from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import enable_wave2c_unified_party

		enable_wave2c_unified_party()
		meta = api.get_metadata()
		axis_ids = {axis["id"] for axis in meta.get("axes", [])}
		self.assertIn("unified_party", axis_ids)
		self.assertTrue(meta.get("unified_party_enabled"))
		self.assertTrue(meta.get("unified_party_columns"))

	def test_currency_axis_blocked_when_disabled(self):
		enable_wave2a_analysis()
		settings = frappe.get_single("Iran Accounting Settings")
		settings.currency_analysis_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "currency"},
		)
		with self.assertRaises(frappe.ValidationError):
			api.get_currency_summary(payload)

	def test_metadata_includes_currency_axis_when_enabled(self):
		from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import enable_wave2c_unified_party

		enable_wave2c_unified_party()
		meta = api.get_metadata()
		axis_ids = {axis["id"] for axis in meta.get("axes", [])}
		self.assertIn("currency", axis_ids)
		self.assertTrue(meta.get("currency_analysis_enabled"))
		self.assertTrue(meta.get("currency_columns"))
