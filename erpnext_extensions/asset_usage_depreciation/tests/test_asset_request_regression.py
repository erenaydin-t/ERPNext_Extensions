# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Regression: Asset Request must not disturb usage depreciation or PM workflows."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.asset_usage_depreciation.constants import DEFAULT_USAGE_FACTOR
from erpnext_extensions.asset_usage_depreciation.services.usage_timeline import mode_to_factor


class TestAssetRequestRegression(unittest.TestCase):
	def test_usage_factor_default_unchanged(self):
		self.assertEqual(DEFAULT_USAGE_FACTOR, 1.0)
		self.assertEqual(mode_to_factor("Normal"), 1.0)
		self.assertEqual(mode_to_factor("No Depreciation"), 0.0)

	def test_asset_usage_period_doctype_intact(self):
		self.assertTrue(frappe.db.exists("DocType", "Asset Usage Period"))
		meta = frappe.get_meta("Asset Usage Period")
		self.assertTrue(meta.has_field("depreciation_mode"))
		self.assertTrue(meta.has_field("asset"))
		self.assertTrue(meta.is_submittable)

	def test_pm_request_workflow_still_active(self):
		if not frappe.db.exists("Workflow", "PM Request Workflow"):
			self.skipTest("PM Request Workflow not installed on this site")
		wf = frappe.get_doc("Workflow", "PM Request Workflow")
		self.assertEqual(wf.document_type, "PM Request")
		self.assertTrue(int(wf.is_active or 0))

	def test_asset_movement_purposes_unchanged(self):
		meta = frappe.get_meta("Asset Movement")
		options = (meta.get_field("purpose").options or "").split("\n")
		for purpose in ("Issue", "Receipt", "Transfer", "Transfer and Issue"):
			self.assertIn(purpose, options)
		self.assertFalse(frappe.get_meta("Asset Request").has_field("request_type"))
