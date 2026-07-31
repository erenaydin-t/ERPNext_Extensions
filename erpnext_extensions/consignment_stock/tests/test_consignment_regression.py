# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from erpnext.stock.doctype.stock_entry.stock_entry_utils import make_stock_entry

from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	enforce_stock_entry_ledger_contract,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_warehouse,
)
from erpnext_extensions.consignment_stock.tests.helpers import ensure_module_ready


class TestConsignmentRegression(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)

	def test_standard_material_receipt_unchanged(self):
		item = ensure_test_item(self.company, "CS-REG-MR")
		se = make_stock_entry(
			item_code=item,
			qty=3,
			target=self.wh,
			rate=1111,
			company=self.company,
			purpose="Material Receipt",
		)
		se.submit()
		contract = enforce_stock_entry_ledger_contract(se.name, self.company, raise_on_fail=True)
		self.assertEqual(contract["status"], "PASS", contract)
		# Must not pick up consignment flags
		self.assertFalse(se.get("custom_is_consignment_receipt"))

	def test_standard_material_issue_unchanged(self):
		item = ensure_test_item(self.company, "CS-REG-MI")
		make_stock_entry(
			item_code=item,
			qty=5,
			target=self.wh,
			rate=2000,
			company=self.company,
			purpose="Material Receipt",
		).submit()
		se = make_stock_entry(
			item_code=item,
			qty=2,
			source=self.wh,
			company=self.company,
			purpose="Material Issue",
		)
		se.submit()
		contract = enforce_stock_entry_ledger_contract(se.name, self.company, raise_on_fail=True)
		self.assertEqual(contract["status"], "PASS", contract)
		self.assertFalse(se.get("custom_is_consignment_return"))
