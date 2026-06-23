# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

from frappe.utils import flt

from erpnext_extensions.iran_accounting.rounding import (
	amount_is_fractional,
	get_currency_precision,
	is_irr_currency,
	round_currency,
	round_gl_entry_amounts,
	round_if_irr,
	round_sle_monetary_fields,
)


class TestIranAccountingRounding(unittest.TestCase):
	def test_irr_precision_is_zero(self):
		self.assertEqual(get_currency_precision("IRR"), 0)
		self.assertTrue(is_irr_currency("IRR"))

	def test_irr_round_gl_entry_fields(self):
		entry = {
			"company": "Test IRR Company",
			"account_currency": "IRR",
			"transaction_currency": "IRR",
			"debit": 10596667255.68,
			"credit": 0,
			"debit_in_account_currency": 10596667255.68,
			"credit_in_account_currency": 0,
			"debit_in_transaction_currency": 10596667255.68,
			"credit_in_transaction_currency": 0,
			"debit_in_reporting_currency": 10596667255.68,
			"credit_in_reporting_currency": 0,
		}
		with mock.patch(
			"erpnext_extensions.iran_accounting.rounding.get_company_currency", return_value="IRR"
		), mock.patch(
			"erpnext_extensions.iran_accounting.rounding.frappe.get_cached_value", return_value="IRR"
		):
			round_gl_entry_amounts(entry)
		for field in (
			"debit",
			"credit",
			"debit_in_account_currency",
			"credit_in_account_currency",
			"debit_in_transaction_currency",
			"credit_in_transaction_currency",
			"debit_in_reporting_currency",
			"credit_in_reporting_currency",
		):
			if not entry[field]:
				continue
			self.assertEqual(entry[field], 10596667256, msg=field)
			self.assertFalse(amount_is_fractional(entry[field], "IRR"))

	def test_usd_eur_account_currency_keeps_decimals(self):
		entry = {
			"company": "Test IRR Company",
			"account_currency": "USD",
			"debit": 100,
			"credit": 0,
			"debit_in_account_currency": 10.555,
			"credit_in_account_currency": 0,
		}
		with mock.patch(
			"erpnext_extensions.iran_accounting.rounding.get_company_currency", return_value="IRR"
		):
			round_gl_entry_amounts(entry)
		self.assertEqual(entry["debit"], 100)
		self.assertEqual(flt(entry["debit_in_account_currency"], 2), 10.56)

	def test_irr_round_sle_value_fields(self):
		sle = {
			"company": "Test IRR Company",
			"stock_value": 1000.68,
			"stock_value_difference": -0.68,
			"valuation_rate": 12663.839090512,
			"incoming_rate": 18169.525,
		}
		with mock.patch(
			"erpnext_extensions.iran_accounting.rounding.get_company_currency", return_value="IRR"
		):
			round_sle_monetary_fields(sle, company="Test IRR Company")
		self.assertEqual(sle["stock_value"], 1001)
		self.assertEqual(sle["stock_value_difference"], -1)
		self.assertEqual(sle["valuation_rate"], 12664)
		self.assertEqual(sle["incoming_rate"], 18170)
		for field in ("stock_value", "stock_value_difference", "valuation_rate", "incoming_rate"):
			self.assertFalse(amount_is_fractional(sle[field], "IRR"), msg=field)

	def test_stock_entry_totals_round_for_irr(self):
		self.assertEqual(round_if_irr(10.6, "IRR"), 11)
		self.assertEqual(round_if_irr(10.4, "IRR"), 10)

	def test_qty_not_rounded_by_rounding_module(self):
		qty = 1.2345
		self.assertEqual(qty, 1.2345)


if __name__ == "__main__":
	unittest.main()
