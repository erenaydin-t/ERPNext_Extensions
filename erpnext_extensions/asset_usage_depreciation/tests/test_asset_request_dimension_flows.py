# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Integration flows A–F for Asset Request Accounting Dimensions."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string

from erpnext_extensions.asset_usage_depreciation.tests import test_helpers as h


class TestAssetRequestDimensionFlows(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.skip = h.skip_if_unready()
		if cls.skip:
			return
		h.ensure_settings(
			prevent_duplicate_active_requests=0,
			require_named_manager_approver=0,
			allow_category_substitution=0,
			auto_create_material_request=1,
			auto_submit_material_request=0,
			auto_create_asset_movement=1,
			auto_submit_asset_movement=0,
		)
		cls.company = h.company()
		cls.employee = h.make_employee(company_name=cls.company)
		cls.cost_center = h.company_cost_center(cls.company)
		cls.dim = h.ensure_test_dimension("AR QA Region")
		cls.fieldname = cls.dim["fieldname"]
		cls.tehran = h.make_dimension_value(cls.dim["doctype"], "AR-QA-Tehran", company=cls.company)
		cls.shiraz = h.make_dimension_value(cls.dim["doctype"], "AR-QA-Shiraz", company=cls.company)

	def _ready(self):
		if getattr(self, "skip", None):
			self.skipTest(self.skip)
		if not self.cost_center:
			self.skipTest("No Cost Center")
		if not frappe.get_meta("Asset Request Item").has_field(self.fieldname):
			self.skipTest("Dimension field missing on Asset Request Item")
		if not frappe.get_meta("Material Request Item").has_field(self.fieldname):
			self.skipTest("Dimension field missing on Material Request Item")

	def _purchase_item(self, tag: str, title: str) -> str:
		return h.make_fixed_asset_item(code=f"AUD-AR-DIM-{tag}", title=title)

	def test_flow_a_header_inheritance_to_mr(self):
		self._ready()
		tag = random_string(6)
		item = self._purchase_item(f"A-{tag}", "Monitor A")
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			cost_center=self.cost_center,
			**{self.fieldname: self.tehran},
		)
		h.submit_and_approve(doc)
		doc.reload()
		self.assertTrue(doc.material_request)
		mr = frappe.get_doc("Material Request", doc.material_request)
		self.assertEqual(mr.items[0].item_code, item)
		self.assertEqual(mr.items[0].cost_center, self.cost_center)
		self.assertEqual(mr.items[0].get(self.fieldname), self.tehran)

	def test_flow_b_item_override_to_mr(self):
		self._ready()
		tag = random_string(6)
		item = self._purchase_item(f"B-{tag}", "Monitor B")
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			extra_item={self.fieldname: self.shiraz, "cost_center": self.cost_center},
			**{self.fieldname: self.tehran, "cost_center": self.cost_center},
		)
		h.submit_and_approve(doc)
		doc.reload()
		mr = frappe.get_doc("Material Request", doc.material_request)
		self.assertEqual(mr.items[0].get(self.fieldname), self.shiraz)

	def test_flow_c_same_item_different_dimensions_not_merged(self):
		self._ready()
		tag = random_string(6)
		lg = self._purchase_item(f"C-{tag}", "LG Monitor")
		doc = frappe.get_doc(
			{
				"doctype": "Asset Request",
				"company": self.company,
				"employee": self.employee,
				"transaction_date": frappe.utils.nowdate(),
				"required_date": frappe.utils.nowdate(),
				"purpose": "Same SKU different dims",
				"cost_center": self.cost_center,
				self.fieldname: self.tehran,
				"items": [
					{
						"requested_item_code": lg,
						"qty": 1,
						self.fieldname: self.tehran,
						"cost_center": self.cost_center,
					},
					{
						"requested_item_code": lg,
						"qty": 1,
						self.fieldname: self.shiraz,
						"cost_center": self.cost_center,
					},
				],
			}
		)
		doc.insert(ignore_permissions=True)
		h.submit_and_approve(doc)
		doc.reload()
		mr = frappe.get_doc("Material Request", doc.material_request)
		self.assertEqual(len(mr.items), 2)
		values = {row.get(self.fieldname) for row in mr.items}
		self.assertEqual(values, {self.tehran, self.shiraz})
		self.assertTrue(all(row.item_code == lg for row in mr.items))

	def test_flow_d_substitution_keeps_dimensions(self):
		self._ready()
		tag = random_string(6)
		samsung = self._purchase_item(f"DS-{tag}", "Samsung Monitor")
		lg = self._purchase_item(f"DL-{tag}", "LG Monitor")
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=samsung,
			fulfilled_item_code=lg,
			substitution_reason="Procurement selected LG",
			extra_item={self.fieldname: self.tehran, "cost_center": self.cost_center},
			**{self.fieldname: self.tehran, "cost_center": self.cost_center},
		)
		h.submit_and_approve(doc)
		doc.reload()
		self.assertEqual(doc.items[0].requested_item_code, samsung)
		mr = frappe.get_doc("Material Request", doc.material_request)
		self.assertEqual(mr.items[0].item_code, lg)
		self.assertEqual(mr.items[0].get(self.fieldname), self.tehran)
		self.assertEqual(mr.items[0].cost_center, self.cost_center)

	def test_flow_e_native_mr_to_po_mapping(self):
		self._ready()
		from erpnext.stock.doctype.material_request.material_request import make_purchase_order

		tag = random_string(6)
		item = self._purchase_item(f"E-{tag}", "PO Map Monitor")
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			cost_center=self.cost_center,
			**{self.fieldname: self.tehran},
		)
		h.submit_and_approve(doc)
		doc.reload()
		mr = frappe.get_doc("Material Request", doc.material_request)
		if int(mr.docstatus or 0) == 0:
			mr.submit()
		po = make_purchase_order(mr.name)
		self.assertTrue(po.items)
		self.assertEqual(po.items[0].item_code, item)
		if frappe.get_meta("Purchase Order Item").has_field(self.fieldname):
			self.assertEqual(po.items[0].get(self.fieldname), self.tehran)
		if frappe.get_meta("Purchase Order Item").has_field("cost_center"):
			self.assertEqual(po.items[0].cost_center, self.cost_center)

	def test_flow_f_existing_asset_movement_not_overwritten(self):
		self._ready()
		tag = random_string(6)
		category = h.make_isolated_category(tag)
		samsung = h.make_fixed_asset_item(code=f"AUD-AR-DIM-FS-{tag}", title="Samsung Pool", category=category)
		lg = h.make_fixed_asset_item(code=f"AUD-AR-DIM-FL-{tag}", title="LG Pool", category=category)
		asset_name = h.make_pool_asset(item_code=lg, company_name=self.company)
		asset = frappe.get_doc("Asset", asset_name)
		original_cc = asset.get("cost_center")
		original_dim = asset.get(self.fieldname) if asset.meta.has_field(self.fieldname) else None
		h.ensure_settings(allow_category_substitution=1)
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=samsung,
			cost_center=self.cost_center,
			**{self.fieldname: self.tehran},
		)
		h.submit_and_approve(doc)
		doc.reload()
		alloc = doc.allocations[0]
		self.assertEqual(alloc.method, "Issue Existing")
		self.assertTrue(alloc.asset_movement)
		am = frappe.get_doc("Asset Movement", alloc.asset_movement)
		# We must not copy AR dimensions onto the movement.
		if am.meta.has_field(self.fieldname):
			self.assertNotEqual(am.get(self.fieldname), self.tehran)
		asset.reload()
		self.assertEqual(asset.get("cost_center"), original_cc)
		if asset.meta.has_field(self.fieldname):
			self.assertEqual(asset.get(self.fieldname), original_dim)
		h.ensure_settings(allow_category_substitution=0)
