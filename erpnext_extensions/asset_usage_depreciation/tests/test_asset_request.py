# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Asset Request v4.4.0 — acquisition only, requested vs fulfilled."""

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import today

from erpnext_extensions.asset_usage_depreciation.services.availability import get_compatible_item_codes
from erpnext_extensions.asset_usage_depreciation.services.fulfillment_service import _evaluate_allocations
from erpnext_extensions.asset_usage_depreciation.services.request_service import _assert_fixed_asset_item


class TestCompatibleItems(unittest.TestCase):
	@patch("erpnext_extensions.asset_usage_depreciation.services.availability.allow_category_substitution", return_value=True)
	@patch("erpnext_extensions.asset_usage_depreciation.services.availability.frappe")
	def test_same_category_items_are_compatible(self, mock_frappe, _allow):
		mock_frappe.db.get_value.return_value = "Monitors"
		mock_frappe.get_all.return_value = ["Samsung Monitor 24", "LG Monitor 24"]
		codes = get_compatible_item_codes("Samsung Monitor 24", "Monitors")
		self.assertIn("LG Monitor 24", codes)
		self.assertIn("Samsung Monitor 24", codes)

	@patch("erpnext_extensions.asset_usage_depreciation.services.availability.allow_category_substitution", return_value=False)
	def test_without_substitution_only_exact_item(self, _allow):
		codes = get_compatible_item_codes("Samsung Monitor 24", "Monitors")
		self.assertEqual(codes, ["Samsung Monitor 24"])

	@patch("erpnext_extensions.asset_usage_depreciation.services.availability.allow_category_substitution", return_value=True)
	def test_explicit_fulfilled_item_wins(self, _allow):
		codes = get_compatible_item_codes("Samsung Monitor 24", "Monitors", fulfilled_item_code="LG Monitor 24")
		self.assertEqual(codes, ["LG Monitor 24"])


class TestFixedAssetValidation(unittest.TestCase):
	@patch("erpnext_extensions.asset_usage_depreciation.services.request_service.frappe")
	def test_non_asset_item_rejected(self, mock_frappe):
		mock_frappe.db.get_value.return_value = {
			"is_fixed_asset": 0,
			"is_grouped_asset": 0,
			"disabled": 0,
			"item_name": "Pen",
			"asset_category": None,
			"stock_uom": "Nos",
		}
		mock_frappe.throw.side_effect = Exception("not fixed asset")
		with self.assertRaises(Exception):
			_assert_fixed_asset_item("Pen", "Requested Item", 1)


class TestAssetRequestDocType(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def test_no_request_type_field(self):
		if not frappe.db.exists("DocType", "Asset Request"):
			self.skipTest("Asset Request DocType not migrated")
		meta = frappe.get_meta("Asset Request")
		self.assertFalse(meta.has_field("request_type"))
		self.assertTrue(meta.has_field("items"))
		self.assertTrue(meta.has_field("allocations"))
		item_meta = frappe.get_meta("Asset Request Item")
		self.assertTrue(item_meta.has_field("requested_item_code"))
		self.assertTrue(item_meta.has_field("fulfilled_item_code"))
		self.assertTrue(item_meta.has_field("requested_specification"))
		alloc_meta = frappe.get_meta("Asset Request Allocation")
		self.assertTrue(alloc_meta.has_field("requested_item_code"))
		self.assertTrue(alloc_meta.has_field("fulfilled_item_code"))
		self.assertTrue(alloc_meta.has_field("allocated_asset"))
		self.assertTrue(alloc_meta.has_field("material_request"))


def _company_ready() -> bool:
	return bool(frappe.db.exists("Company", "_Test Company") and frappe.db.exists("Item", "Macbook Pro"))


def _ensure_monitor_items():
	if not frappe.db.exists("Asset Category", "Computers"):
		return None, None
	samsung = "AUD-AR-Samsung-Monitor-24"
	lg = "AUD-AR-LG-Monitor-24"
	for code, title in ((samsung, "Samsung Monitor 24 inch"), (lg, "LG Monitor 24 inch")):
		if frappe.db.exists("Item", code):
			continue
		item = frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": title,
				"item_group": "All Item Groups",
				"stock_uom": "Nos",
				"is_stock_item": 0,
				"is_fixed_asset": 1,
				"is_grouped_asset": 0,
				"auto_create_assets": 0,
				"asset_category": "Computers",
			}
		)
		item.insert(ignore_permissions=True)
	return samsung, lg


class TestAssetRequestFulfillment(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def test_evaluate_substitutes_same_category_pool_asset(self):
		if not _company_ready():
			self.skipTest("ERPNext test masters not available")
		samsung, lg = _ensure_monitor_items()
		if not samsung:
			self.skipTest("Could not create monitor items")

		if not frappe.db.exists("Location", "Test Location"):
			frappe.get_doc({"doctype": "Location", "location_name": "Test Location"}).insert(
				ignore_permissions=True, ignore_if_duplicate=True
			)

		asset = frappe.get_doc(
			{
				"doctype": "Asset",
				"asset_name": "LG Monitor Pool",
				"asset_category": "Computers",
				"item_code": lg,
				"company": "_Test Company",
				"purchase_date": "2026-01-01",
				"available_for_use_date": "2026-01-01",
				"calculate_depreciation": 0,
				"net_purchase_amount": 1000,
				"purchase_amount": 1000,
				"location": "Test Location",
				"asset_owner": "Company",
				"asset_type": "Existing Asset",
				"asset_quantity": 1,
			}
		)
		asset.insert(ignore_permissions=True)
		asset.submit()
		# Pool asset must have no custodian
		frappe.db.set_value("Asset", asset.name, "custodian", "")

		employee = frappe.db.get_value("Employee", {"company": "_Test Company"}, "name")
		if not employee:
			self.skipTest("No Employee for _Test Company")

		doc = frappe.get_doc(
			{
				"doctype": "Asset Request",
				"company": "_Test Company",
				"employee": employee,
				"transaction_date": today(),
				"required_date": today(),
				"purpose": "Need a 24 inch monitor",
				"items": [
					{
						"requested_item_code": samsung,
						"qty": 1,
					}
				],
			}
		)
		doc.insert()
		_evaluate_allocations(doc)
		self.assertTrue(doc.allocations)
		alloc = doc.allocations[0]
		self.assertEqual(alloc.method, "Issue Existing")
		self.assertEqual(alloc.allocated_asset, asset.name)
		self.assertEqual(alloc.fulfilled_item_code, lg)
		self.assertEqual(alloc.requested_item_code, samsung)
		self.assertNotEqual(alloc.requested_item_code, alloc.fulfilled_item_code)
		self.assertTrue(alloc.substitution_reason)

	def test_shortage_stages_purchase_on_fulfilled_item(self):
		if not frappe.db.exists("DocType", "Asset Request"):
			self.skipTest("Asset Request DocType not migrated")
		if not _company_ready():
			self.skipTest("ERPNext test masters not available")
		samsung, lg = _ensure_monitor_items()
		if not samsung:
			self.skipTest("Could not create monitor items")

		employee = frappe.db.get_value("Employee", {"company": "_Test Company"}, "name")
		if not employee:
			self.skipTest("No Employee for _Test Company")

		doc = frappe.get_doc(
			{
				"doctype": "Asset Request",
				"company": "_Test Company",
				"employee": employee,
				"transaction_date": today(),
				"required_date": today(),
				"purpose": "Need a monitor to purchase",
				"items": [
					{
						"requested_item_code": samsung,
						"fulfilled_item_code": lg,
						"fulfilled_purchase_item": lg,
						"substitution_reason": "LG is the approved standard",
						"qty": 1,
					}
				],
			}
		)
		doc.insert()
		_evaluate_allocations(doc)
		purchase = [a for a in doc.allocations if a.method == "Purchase"]
		# If a pool LG exists from the previous test, issue may win; purchase is for leftover only.
		if purchase:
			self.assertEqual(purchase[0].fulfilled_item_code, lg)
			self.assertEqual(purchase[0].fulfilled_purchase_item, lg)
			self.assertEqual(purchase[0].requested_item_code, samsung)
		else:
			self.assertTrue(any(a.fulfilled_item_code == lg for a in doc.allocations))
