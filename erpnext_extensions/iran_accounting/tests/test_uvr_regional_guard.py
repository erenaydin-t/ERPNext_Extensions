# Copyright (c) 2026, ERPNext Extensions contributors
"""UVR regional upgrade guard (3.8.7) — fail-closed twin of riv_rate_guard.

Covers allow-list, fingerprints, missing symbols, install-once, bootstrap
RuntimeError, original preservation, and live PR / LCV / Return / PI / non-IRR.
"""

from __future__ import annotations

import inspect
import unittest
from unittest import mock

import frappe
from frappe.utils import flt, nowdate, nowtime

from erpnext_extensions.iran_accounting.domain.uvr_regional_guard import (
	_FN_FINGERPRINTS,
	assert_erpnext_uvr_regional_patch_supported,
	collect_fingerprint_report,
)


def _reset_uvr_patch():
	"""Restore vanilla regional symbol and clear install flag (test isolation)."""
	import erpnext.controllers.buying_controller as buying_controller

	saved = getattr(buying_controller, "_iran_original_regional_valuation_rate", None)
	if saved is not None:
		buying_controller.update_regional_item_valuation_rate = saved
	buying_controller._iran_patched_regional_valuation_rate = False
	if hasattr(buying_controller, "_iran_original_regional_valuation_rate"):
		delattr(buying_controller, "_iran_original_regional_valuation_rate")


def _ensure_uvr_patch():
	from erpnext_extensions.iran_accounting.integration.monkey_patches import (
		_patch_buying_regional_valuation_rate,
	)

	_patch_buying_regional_valuation_rate()


class TestUvrRegionalGuardUnit(unittest.TestCase):
	def tearDown(self):
		# Keep site usable for later tests / suite siblings.
		try:
			_ensure_uvr_patch()
		except Exception:
			pass

	def test_supported_version_passes(self):
		assert_erpnext_uvr_regional_patch_supported()
		report = collect_fingerprint_report()
		self.assertIn(report["erpnext_major_minor"], {"16.29", "16.30"})
		self.assertIn(report["frappe_major_minor"], {"16.29", "16.30"})
		for name, expected in _FN_FINGERPRINTS.items():
			got = report["methods"][name]
			self.assertEqual(got["signature"], expected["signature"], name)
			self.assertEqual(got["source_sha256"], expected["source_sha256"], name)
		self.assertTrue(report["methods"]["update_valuation_rate"]["calls_regional_hook"])

	def test_unsupported_version_blocks(self):
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.uvr_regional_guard.major_minor",
			side_effect=lambda v: "99.0",
		):
			with self.assertRaises(RuntimeError) as ctx:
				assert_erpnext_uvr_regional_patch_supported()
			msg = str(ctx.exception).lower()
			self.assertIn("upgrade guard", msg)
			self.assertIn("uvr integerization patch not installed", msg)

	def test_hash_mismatch_blocks(self):
		bad = {
			"update_valuation_rate": {
				"signature": _FN_FINGERPRINTS["update_valuation_rate"]["signature"],
				"source_sha256": "0" * 64,
				"must_contain": ("update_regional_item_valuation_rate",),
			},
			"update_regional_item_valuation_rate": _FN_FINGERPRINTS[
				"update_regional_item_valuation_rate"
			],
		}
		with mock.patch.dict(
			"erpnext_extensions.iran_accounting.domain.uvr_regional_guard._FN_FINGERPRINTS",
			bad,
			clear=True,
		):
			with self.assertRaises(RuntimeError) as ctx:
				assert_erpnext_uvr_regional_patch_supported()
			self.assertIn("fingerprint", str(ctx.exception).lower())
			self.assertIn("uvr integerization patch not installed", str(ctx.exception).lower())

	def test_missing_update_valuation_rate_blocks(self):
		from erpnext.controllers.buying_controller import BuyingController

		real_hasattr = hasattr

		def fake_hasattr(obj, name):
			if obj is BuyingController and name == "update_valuation_rate":
				return False
			return real_hasattr(obj, name)

		with mock.patch("builtins.hasattr", side_effect=fake_hasattr):
			with self.assertRaises(RuntimeError) as ctx:
				assert_erpnext_uvr_regional_patch_supported()
			self.assertIn("update_valuation_rate missing", str(ctx.exception).lower())

	def test_missing_regional_hook_blocks(self):
		import erpnext.controllers.buying_controller as buying_controller

		real_hasattr = hasattr

		def fake_hasattr(obj, name):
			if obj is buying_controller and name == "update_regional_item_valuation_rate":
				return False
			return real_hasattr(obj, name)

		with mock.patch("builtins.hasattr", side_effect=fake_hasattr):
			with self.assertRaises(RuntimeError) as ctx:
				assert_erpnext_uvr_regional_patch_supported()
			self.assertIn("update_regional_item_valuation_rate missing", str(ctx.exception).lower())

	def test_wrapper_installed_once(self):
		import erpnext.controllers.buying_controller as buying_controller

		from erpnext_extensions.iran_accounting.integration.monkey_patches import (
			_patch_buying_regional_valuation_rate,
			apply_monkey_patches,
		)

		_reset_uvr_patch()
		_patch_buying_regional_valuation_rate()
		first = buying_controller.update_regional_item_valuation_rate
		_patch_buying_regional_valuation_rate()
		apply_monkey_patches()
		second = buying_controller.update_regional_item_valuation_rate
		self.assertIs(first, second)
		self.assertTrue(getattr(buying_controller, "_iran_patched_regional_valuation_rate", False))
		self.assertEqual(first.__module__, "erpnext_extensions.iran_accounting.buying_selling")
		orig = buying_controller._iran_original_regional_valuation_rate
		self.assertIsNotNone(orig)
		self.assertNotEqual(orig.__module__, first.__module__)
		self.assertEqual(str(inspect.signature(orig)), "(doc)")

	def test_wrapper_not_installed_on_failure(self):
		import erpnext.controllers.buying_controller as buying_controller

		from erpnext_extensions.iran_accounting.integration.monkey_patches import (
			_patch_buying_regional_valuation_rate,
		)

		_reset_uvr_patch()
		vanilla = buying_controller.update_regional_item_valuation_rate
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.uvr_regional_guard.major_minor",
			side_effect=lambda v: "99.0",
		):
			with self.assertRaises(RuntimeError) as ctx:
				_patch_buying_regional_valuation_rate()
			self.assertIn("uvr integerization patch not installed", str(ctx.exception).lower())
		self.assertFalse(getattr(buying_controller, "_iran_patched_regional_valuation_rate", False))
		self.assertIs(buying_controller.update_regional_item_valuation_rate, vanilla)
		self.assertFalse(hasattr(buying_controller, "_iran_original_regional_valuation_rate"))

	def test_bootstrap_runtime_error(self):
		from erpnext_extensions.iran_accounting.integration.monkey_patches import (
			_patch_buying_regional_valuation_rate,
		)

		_reset_uvr_patch()
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.uvr_regional_guard._SUPPORTED_ERPNEXT_MINOR",
			frozenset({"0.0"}),
		):
			with self.assertRaises(RuntimeError) as ctx:
				_patch_buying_regional_valuation_rate()
			msg = str(ctx.exception)
			self.assertIn("IRR Upgrade Guard", msg)
			self.assertIn("UVR integerization patch not installed", msg)

	def test_original_function_preserved(self):
		import erpnext.controllers.buying_controller as buying_controller

		_reset_uvr_patch()
		_ensure_uvr_patch()
		orig = buying_controller._iran_original_regional_valuation_rate
		self.assertTrue(getattr(orig, "__wrapped__", None) or orig.__module__.startswith("erpnext."))
		from erpnext_extensions.iran_accounting.domain.uvr_regional_guard import (
			normalize_function_source,
		)
		import hashlib

		digest = hashlib.sha256(normalize_function_source(orig).encode()).hexdigest()
		self.assertEqual(
			digest, _FN_FINGERPRINTS["update_regional_item_valuation_rate"]["source_sha256"]
		)


class TestUvrRegionalGuardIntegration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = frappe.db.get_value(
			"Company", {"default_currency": "IRR", "name": "test"}, "name"
		) or frappe.db.get_value("Company", {"default_currency": "IRR"}, "name")
		if not cls.company:
			raise unittest.SkipTest("No IRR company")
		cls.wh = frappe.db.get_value(
			"Warehouse", {"company": cls.company, "is_group": 0}, "name"
		)
		cls.supplier = frappe.db.get_value("Supplier", {"disabled": 0}, "name")
		cls.uom = frappe.db.get_single_value("Stock Settings", "stock_uom") or "Nos"
		cls.ig = frappe.db.get_single_value("Stock Settings", "item_group") or frappe.db.get_value(
			"Item Group", {"is_group": 0}, "name"
		)
		cls.cc = frappe.db.get_value("Company", cls.company, "cost_center")
		cls.exp = frappe.db.get_value("Company", cls.company, "default_expense_account")
		cls.dept = frappe.db.get_value("Department", {"company": cls.company}, "name") or frappe.db.get_value(
			"Department", {}, "name"
		)

	def _item(self, prefix: str) -> str:
		code = f"{prefix}-{frappe.generate_hash(length=5)}"
		frappe.get_doc(
			{
				"doctype": "Item",
				"item_code": code,
				"item_name": code,
				"item_group": self.ig,
				"stock_uom": self.uom,
				"is_stock_item": 1,
			}
		).insert(ignore_permissions=True)
		return code

	def _assert_integer_vr(self, parent: str, doctype_item: str = "Purchase Receipt Item"):
		vr = frappe.db.get_value(doctype_item, {"parent": parent}, "valuation_rate")
		self.assertIsNotNone(vr)
		self.assertEqual(flt(vr), float(int(flt(vr))), msg=f"non-integer VR {vr} on {parent}")

	def test_pr_submit_integerizes_valuation_rate(self):
		_ensure_uvr_patch()
		code = self._item("UVR-PR")
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = self.supplier
		pr.currency = "IRR"
		pr.conversion_rate = 1
		pr.posting_date = nowdate()
		pr.posting_time = nowtime()
		pr.set_posting_time = 1
		if self.dept:
			pr.department = self.dept
		pr.append(
			"items",
			{
				"item_code": code,
				"qty": 10,
				"rate": 1000000,
				"uom": self.uom,
				"stock_uom": self.uom,
				"conversion_factor": 1,
				"warehouse": self.wh,
				"department": self.dept,
				"cost_center": self.cc,
			},
		)
		pr.insert()
		pr.submit()
		frappe.db.commit()
		self._assert_integer_vr(pr.name)

	def test_lcv_integerizes_valuation_rate(self):
		_ensure_uvr_patch()
		code = self._item("UVR-LCV")
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = self.supplier
		pr.currency = "IRR"
		pr.conversion_rate = 1
		pr.posting_date = nowdate()
		pr.posting_time = nowtime()
		pr.set_posting_time = 1
		if self.dept:
			pr.department = self.dept
		pr.append(
			"items",
			{
				"item_code": code,
				"qty": 10,
				"rate": 1000000,
				"uom": self.uom,
				"stock_uom": self.uom,
				"conversion_factor": 1,
				"warehouse": self.wh,
				"department": self.dept,
				"cost_center": self.cc,
			},
		)
		pr.insert()
		pr.submit()
		frappe.db.commit()

		lcv = frappe.new_doc("Landed Cost Voucher")
		lcv.company = self.company
		lcv.posting_date = nowdate()
		lcv.append(
			"purchase_receipts",
			{"receipt_document_type": "Purchase Receipt", "receipt_document": pr.name},
		)
		lcv.append(
			"taxes",
			{"expense_account": self.exp, "description": "UVR-GUARD-F", "amount": 1},
		)
		lcv.get_items_from_purchase_receipts()
		lcv.insert()
		lcv.submit()
		frappe.db.commit()
		self._assert_integer_vr(pr.name)
		vr = flt(frappe.db.get_value("Purchase Receipt Item", {"parent": pr.name}, "valuation_rate"))
		self.assertEqual(vr, 1000000.0)

	def test_purchase_return_integerizes(self):
		_ensure_uvr_patch()
		code = self._item("UVR-RET")
		pr = frappe.new_doc("Purchase Receipt")
		pr.company = self.company
		pr.supplier = self.supplier
		pr.currency = "IRR"
		pr.conversion_rate = 1
		pr.posting_date = nowdate()
		pr.posting_time = nowtime()
		pr.set_posting_time = 1
		if self.dept:
			pr.department = self.dept
		pr.append(
			"items",
			{
				"item_code": code,
				"qty": 5,
				"rate": 100000,
				"uom": self.uom,
				"stock_uom": self.uom,
				"conversion_factor": 1,
				"warehouse": self.wh,
				"department": self.dept,
				"cost_center": self.cc,
			},
		)
		pr.insert()
		pr.submit()
		frappe.db.commit()

		ret = frappe.new_doc("Purchase Receipt")
		ret.company = self.company
		ret.supplier = self.supplier
		ret.currency = "IRR"
		ret.conversion_rate = 1
		ret.posting_date = nowdate()
		ret.posting_time = nowtime()
		ret.set_posting_time = 1
		ret.is_return = 1
		ret.return_against = pr.name
		if self.dept:
			ret.department = self.dept
		ret.append(
			"items",
			{
				"item_code": code,
				"qty": -2,
				"rate": 100000,
				"uom": self.uom,
				"stock_uom": self.uom,
				"conversion_factor": 1,
				"warehouse": self.wh,
				"department": self.dept,
				"cost_center": self.cc,
				"purchase_receipt_item": frappe.db.get_value(
					"Purchase Receipt Item", {"parent": pr.name}, "name"
				),
			},
		)
		ret.insert()
		ret.submit()
		frappe.db.commit()
		self._assert_integer_vr(ret.name)

	def test_pi_update_stock_integerizes(self):
		_ensure_uvr_patch()
		code = self._item("UVR-PI")
		pi = frappe.new_doc("Purchase Invoice")
		pi.company = self.company
		pi.supplier = self.supplier
		pi.currency = "IRR"
		pi.conversion_rate = 1
		pi.posting_date = nowdate()
		pi.update_stock = 1
		pi.set_posting_time = 1
		pi.posting_time = nowtime()
		if self.dept:
			pi.department = self.dept
		pi.append(
			"items",
			{
				"item_code": code,
				"qty": 3,
				"rate": 50000,
				"uom": self.uom,
				"stock_uom": self.uom,
				"conversion_factor": 1,
				"warehouse": self.wh,
				"department": self.dept,
				"cost_center": self.cc,
				"expense_account": self.exp,
			},
		)
		pi.insert()
		pi.submit()
		frappe.db.commit()
		self._assert_integer_vr(pi.name, "Purchase Invoice Item")

	def test_non_irr_passthrough(self):
		"""Regional Iran binding is installed, but align no-ops for non-IRR companies."""
		from erpnext_extensions.iran_accounting.buying_selling import (
			update_regional_item_valuation_rate,
		)

		non_irr = frappe.db.get_value(
			"Company", {"default_currency": ("!=", "IRR")}, "name"
		)
		if not non_irr:
			self.skipTest("No non-IRR company")

		class _R:
			valuation_rate = 12.345

			def get(self, k, default=None):
				return getattr(self, k, default)

		class _D:
			company = non_irr
			currency = frappe.db.get_value("Company", non_irr, "default_currency")
			items = None

			def __init__(self):
				self.items = [_R()]

			def get(self, k, default=None):
				return getattr(self, k, default)

		doc = _D()
		update_regional_item_valuation_rate(doc)
		self.assertEqual(doc.items[0].valuation_rate, 12.345)


def run_uvr_regional_guard_suite():
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	suite = unittest.defaultTestLoader.loadTestsFromTestCase(TestUvrRegionalGuardUnit)
	suite.addTests(
		unittest.defaultTestLoader.loadTestsFromTestCase(TestUvrRegionalGuardIntegration)
	)
	result = unittest.TextTestRunner(verbosity=2).run(suite)
	return {
		"ok": result.wasSuccessful(),
		"tests": result.testsRun,
		"failures": len(result.failures),
		"errors": len(result.errors),
	}
