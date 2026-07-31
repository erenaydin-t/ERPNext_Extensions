# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company
from erpnext_extensions.consignment_stock.api import (
	create_consignment_recognition_entry,
	create_consignment_return_settlement,
)
from erpnext_extensions.consignment_stock.settlement_service import compute_settlement_amounts
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_module_ready,
	ensure_settings,
	ensure_stock_entry_types,
	ensure_supplier,
	make_consignment_receipt,
	make_consignment_return,
)


class TestConsignmentSettlement(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings = frappe.get_doc("Consignment Stock Settings", ensure_settings(cls.company))
		cls.types = ensure_stock_entry_types()
		cls.supplier = ensure_supplier(cls.company)
		cls.wh = cls.settings.default_consignment_warehouse

	def _return_after_receipt(self, prefix, qty=10, rate=1000):
		item = ensure_test_item(self.company, prefix)
		receipt = make_consignment_receipt(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=qty,
			rate=rate,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["receipt"],
		)
		je = create_consignment_recognition_entry(receipt.name)["journal_entry"]
		frappe.get_doc("Journal Entry", je).submit()
		ret = make_consignment_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=qty,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["return"],
			receipt_name=receipt.name,
			receipt_detail=receipt.items[0].name,
		)
		return receipt, ret

	def test_settlement_draft_balanced_equal_rates(self):
		_receipt, ret = self._return_after_receipt("CS-SET-EQ", qty=10, rate=1000)
		amounts = compute_settlement_amounts(ret)
		self.assertEqual(amounts["receipt_settlement_amount"], 10000)
		# A should equal warehouse outgoing value (~10000 if no other movements)
		out = create_consignment_return_settlement(ret.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		self.assertEqual(je.docstatus, 0)
		total_debit = sum(flt(r.debit_in_account_currency) for r in je.accounts)
		total_credit = sum(flt(r.credit_in_account_currency) for r in je.accounts)
		self.assertEqual(total_debit, total_credit)

	def test_settlement_difference_formula(self):
		# Create receipt then return; A comes from SE outgoing value
		_receipt, ret = self._return_after_receipt("CS-SET-D", qty=5, rate=2000)
		amounts = compute_settlement_amounts(ret)
		R = amounts["receipt_settlement_amount"]
		A = amounts["actual_return_valuation_amount"]
		D = amounts["valuation_difference"]
		self.assertEqual(D, flt(A - R))
		self.assertEqual(R, 10000)

		out = create_consignment_return_settlement(ret.name)
		je = frappe.get_doc("Journal Entry", out["journal_entry"])
		diff_account = self.settings.consignment_valuation_difference_account
		if D > 0:
			diff_debit = sum(
				flt(r.debit_in_account_currency) for r in je.accounts if r.account == diff_account
			)
			self.assertEqual(diff_debit, D)
		elif D < 0:
			diff_credit = sum(
				flt(r.credit_in_account_currency) for r in je.accounts if r.account == diff_account
			)
			self.assertEqual(diff_credit, abs(D))

		total_debit = sum(flt(r.debit_in_account_currency) for r in je.accounts)
		total_credit = sum(flt(r.credit_in_account_currency) for r in je.accounts)
		self.assertEqual(total_debit, total_credit)

	def test_duplicate_settlement_blocked(self):
		_receipt, ret = self._return_after_receipt("CS-SET-DUP", qty=3, rate=1000)
		create_consignment_return_settlement(ret.name)
		with self.assertRaises(frappe.ValidationError):
			create_consignment_return_settlement(ret.name)
