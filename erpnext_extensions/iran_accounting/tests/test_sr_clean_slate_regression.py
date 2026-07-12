# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.sr_clean_slate_regression import (
	CLEAN_SLATE_PREFIX,
	assert_stock_reconciliation_voucher,
	hard_reset_test_stock_data,
	run_clean_slate_regression,
)


class TestSrCleanSlateRegression(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")

	def test_hard_reset_runs(self):
		out = hard_reset_test_stock_data(self.company, item_prefixes=(CLEAN_SLATE_PREFIX,))
		self.assertEqual(out["company"], self.company)
		frappe.db.commit()

	def test_full_clean_slate_regression(self):
		result = run_clean_slate_regression(
			self.company,
			item_prefixes=(CLEAN_SLATE_PREFIX,),
		)
		frappe.db.commit()
		self.assertEqual(result["overall"], "PASS", msg=result)
		for v in result["vouchers"]:
			self.assertEqual(v["status"], "PASS", msg=v)
			self.assertEqual(flt(v["header"]), flt(v["sum_amount_difference"]))
			if v.get("case") == "A_opening_9877":
				self.assertEqual(flt(v["header"]), 29631)
				self.assertNotEqual(flt(v["header"]), 29630)
			if flt(v["sum_amount_gross"]) != flt(v["sum_amount_difference"]):
				self.assertNotEqual(flt(v["header"]), flt(v["sum_amount_gross"]))
		for s in result.get("system_settings_sweep") or []:
			self.assertEqual(s["status"], "PASS", msg=s)
			self.assertEqual(flt(s["header"]), 29631)

	def test_regression_9877_isolated(self):
		from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory, get_warehouse
		from erpnext_extensions.iran_accounting.sr_clean_slate_regression import (
			_make_clean_item,
			_submit_opening_sr,
		)

		enable_perpetual_inventory(self.company)
		wh = get_warehouse(self.company)
		hard_reset_test_stock_data(self.company, item_prefixes=(CLEAN_SLATE_PREFIX,))
		item = _make_clean_item(self.company, "9877")
		sr = _submit_opening_sr(self.company, wh, item, 3, 9877)
		frappe.db.commit()
		res = assert_stock_reconciliation_voucher(sr.name, self.company)
		self.assertEqual(res["status"], "PASS", res)
		self.assertEqual(flt(res["header"]), 29631)
