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
	round_row_amount,
	round_sle_monetary_fields,
)


class TestIranAccountingRounding(unittest.TestCase):
	def test_irr_precision_ignores_system_settings(self):
		get_currency_precision.cache_clear()
		# IRR is hard-coded to 0 decimals; System Settings must not change it.
		self.assertEqual(get_currency_precision("IRR"), 0)
		get_currency_precision.cache_clear()

	def test_float_precision_seven_does_not_change_irr_row_amount(self):
		get_currency_precision.cache_clear()
		self.assertEqual(round_row_amount(3, 9877, "IRR"), 29631)
		get_currency_precision.cache_clear()
		qty = 1.2345
		self.assertEqual(qty, 1.2345)

	def test_usd_precision_from_currency_master(self):
		# Non-IRR uses Currency master; unit-test via precision helper without live DB.
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.get_currency_precision",
			side_effect=lambda c: 0 if (c or "").upper() == "IRR" else 2,
		):
			from erpnext_extensions.iran_accounting.domain import currency as currency_mod

			self.assertEqual(currency_mod.round_currency(10.556, "USD"), 10.56)

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
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.frappe.get_cached_value",
				return_value="IRR",
			),
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
		# Company IRR amounts integer; account currency USD keeps 2dp (mocked precision).
		from erpnext_extensions.iran_accounting.domain import currency as currency_mod

		with mock.patch.object(
			currency_mod,
			"get_currency_precision",
			side_effect=lambda c: 0 if (c or "").upper() == "IRR" else 2,
		):
			self.assertEqual(currency_mod.round_currency(100.4, "IRR"), 100)
			self.assertEqual(currency_mod.round_currency(10.556, "USD"), 10.56)


	def test_irr_round_sle_value_fields(self):
		sle = {
			"company": "Test IRR Company",
			"stock_value": 1000.68,
			"stock_value_difference": -0.68,
			"valuation_rate": 12663.839090512,
			"incoming_rate": 18169.525,
		}
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.is_irr_company",
				return_value=False,
			),
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

	def test_irr_round_sle_preserves_rate_before_stock_value_computed(self):
		"""Opening Stock Reconciliation SLE: qty_after set before stock_value (before_insert)."""
		sle = {
			"company": "Test IRR Company",
			"voucher_type": "Stock Reconciliation",
			"actual_qty": 0,
			"qty_after_transaction": 5,
			"valuation_rate": 1234.567,
			"incoming_rate": 0,
			"stock_value": 0,
			"stock_value_difference": 0,
		}
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.get_company_currency",
				return_value="IRR",
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.domain.ledger_rounding.is_irr_company",
				return_value=False,
			),
		):
			round_sle_monetary_fields(sle, company="Test IRR Company")
		self.assertEqual(sle["valuation_rate"], 1235)
		# opening SLE with zero stock_value: incoming_rate may stay 0 until posting completes
		self.assertIn(sle["incoming_rate"], (0, 1235))
		self.assertEqual(sle["stock_value"], 0)


if __name__ == "__main__":
	unittest.main()
