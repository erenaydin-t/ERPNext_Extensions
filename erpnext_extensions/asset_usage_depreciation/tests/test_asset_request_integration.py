# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""End-to-end business flows for Asset Request acquisition (no Playwright)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string

from erpnext_extensions.asset_usage_depreciation.services.report_service import (
	pending_asset_requests,
	requested_vs_fulfilled,
	substituted_assets,
)
from erpnext_extensions.asset_usage_depreciation.tests import test_helpers as h


class TestAssetRequestIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.skip = h.skip_if_unready()
		if cls.skip:
			return
		h.ensure_settings(
			allow_category_substitution=1,
			require_named_manager_approver=0,
			auto_create_asset_movement=1,
			auto_create_material_request=1,
			auto_submit_asset_movement=0,
			auto_submit_material_request=0,
		)
		cls.company = h.company()
		cls.employee = h.make_employee(company_name=cls.company)

	def _ready(self):
		if getattr(self, "skip", None):
			self.skipTest(self.skip)

	def test_flow1_pool_issue_creates_asset_movement(self):
		self._ready()
		tag = random_string(6)
		category = h.make_isolated_category(tag)
		samsung = h.make_fixed_asset_item(code=f"AUD-AR-S-{tag}", title="Samsung Monitor", category=category)
		lg = h.make_fixed_asset_item(code=f"AUD-AR-L-{tag}", title="LG Monitor", category=category)
		asset = h.make_pool_asset(item_code=lg, company_name=self.company)
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=samsung)
		h.submit_and_approve(doc)
		doc.reload()
		self.assertEqual(doc.docstatus, 1)
		self.assertTrue(doc.allocations)
		alloc = doc.allocations[0]
		self.assertEqual(alloc.method, "Issue Existing")
		self.assertEqual(alloc.allocated_asset, asset)
		self.assertEqual(alloc.requested_item_code, samsung)
		self.assertEqual(alloc.fulfilled_item_code, lg)
		self.assertTrue(alloc.asset_movement)
		self.assertEqual(
			frappe.db.get_value("Asset Movement", alloc.asset_movement, "reference_name"),
			doc.name,
		)
		self.assertEqual(
			frappe.db.get_value("Asset Movement", alloc.asset_movement, "reference_doctype"),
			"Asset Request",
		)

	def test_flow2_shortage_creates_material_request_for_fulfilled_item(self):
		self._ready()
		tag = random_string(6)
		samsung = h.make_fixed_asset_item(code=f"AUD-AR-PS-{tag}", title="Samsung Purchase")
		lg = h.make_fixed_asset_item(code=f"AUD-AR-PL-{tag}", title="LG Purchase")
		h.ensure_settings(allow_category_substitution=0)
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=samsung,
			fulfilled_item_code=lg,
			substitution_reason="Purchasing selected LG as standard",
		)
		h.submit_and_approve(doc)
		doc.reload()
		self.assertTrue(doc.material_request)
		mr = frappe.get_doc("Material Request", doc.material_request)
		self.assertEqual(mr.material_request_type, "Purchase")
		self.assertEqual(mr.custom_asset_request, doc.name)
		self.assertEqual(cint_check(mr.custom_created_from_asset_request), 1)
		self.assertEqual(mr.items[0].item_code, lg)
		alloc = doc.allocations[0]
		self.assertEqual(alloc.method, "Purchase")
		self.assertEqual(alloc.requested_item_code, samsung)
		self.assertEqual(alloc.fulfilled_item_code, lg)
		self.assertEqual(alloc.material_request, mr.name)
		h.ensure_settings(allow_category_substitution=1)

	def test_flow3_substitution_appears_in_reports(self):
		self._ready()
		tag = random_string(6)
		category = h.make_isolated_category(tag)
		samsung = h.make_fixed_asset_item(code=f"AUD-AR-RS-{tag}", title="Samsung Report", category=category)
		lg = h.make_fixed_asset_item(code=f"AUD-AR-RL-{tag}", title="LG Report", category=category)
		h.make_pool_asset(item_code=lg, company_name=self.company)
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=samsung)
		h.submit_and_approve(doc)
		_cols, rows = requested_vs_fulfilled({"company": self.company})
		hit = next((r for r in rows if r.asset_request == doc.name), None)
		self.assertIsNotNone(hit)
		self.assertEqual(hit.requested_item_code, samsung)
		self.assertEqual(hit.fulfilled_item_code, lg)
		self.assertEqual(int(hit.substituted), 1)
		self.assertTrue(hit.substitution_reason)
		_cols, sub = substituted_assets({"company": self.company})
		self.assertTrue(any(r.asset_request == doc.name for r in sub))

	def test_pending_report_includes_unsubmitted(self):
		self._ready()
		item = h.make_fixed_asset_item()
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=item)
		doc.db_set("status", "Pending Manager Approval")
		_cols, rows = pending_asset_requests({"company": self.company})
		self.assertTrue(any(r.name == doc.name for r in rows))


def cint_check(v) -> int:
	from frappe.utils import cint

	return cint(v)
