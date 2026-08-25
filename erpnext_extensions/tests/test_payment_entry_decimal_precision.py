# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for Payment Entry DECIMAL(30,9) allowlist and decision matrix."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from erpnext_extensions import payment_entry_decimal_precision as mod


class TestPaymentEntryDecimalPrecision(unittest.TestCase):
	def test_allowlists_exact(self):
		self.assertEqual(
			mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry"],
			(
				"paid_amount",
				"paid_amount_after_tax",
				"base_paid_amount",
				"base_paid_amount_after_tax",
				"received_amount",
				"received_amount_after_tax",
				"base_received_amount",
				"base_received_amount_after_tax",
				"total_allocated_amount",
				"base_total_allocated_amount",
				"unallocated_amount",
				"difference_amount",
				"total_taxes_and_charges",
				"base_total_taxes_and_charges",
			),
		)
		self.assertEqual(
			mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry Reference"],
			(
				"total_amount",
				"outstanding_amount",
				"allocated_amount",
				"exchange_gain_loss",
				"payment_term_outstanding",
			),
		)
		self.assertEqual(mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry Deduction"], ("amount",))
		self.assertEqual(
			mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Advance Taxes and Charges"],
			("tax_amount", "total", "base_tax_amount", "base_total", "net_amount", "base_net_amount"),
		)
		self.assertEqual(
			mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Tax Withholding Entry"],
			("taxable_amount", "withholding_amount"),
		)
		self.assertEqual(len(mod.payment_entry_field_targets()), 28)

	def test_excludes_exchange_and_tax_rates(self):
		pe = mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry"]
		self.assertNotIn("source_exchange_rate", pe)
		self.assertNotIn("target_exchange_rate", pe)
		ref = mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Payment Entry Reference"]
		self.assertNotIn("exchange_rate", ref)
		taxes = mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Advance Taxes and Charges"]
		self.assertNotIn("rate", taxes)
		tw = mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE["Tax Withholding Entry"]
		self.assertNotIn("tax_rate", tw)
		self.assertNotIn("conversion_rate", tw)

	def test_no_runtime_field_scanning(self):
		source = Path(inspect.getsourcefile(mod)).read_text(encoding="utf-8")
		for snippet in (
			"keyword",
			"for df in meta.fields",
			'fieldtype == "Currency"',
			"endswith(\"amount\")",
		):
			self.assertNotIn(snippet, source)

	def test_no_unrelated_doctypes_included(self):
		for doctype in ("GL Entry", "Journal Entry", "Sales Invoice", "PM Holder", "Stock Reconciliation"):
			self.assertNotIn(doctype, mod.PAYMENT_ENTRY_FIELDS_BY_DOCTYPE)

	def test_decide_decimal_action_matrix(self):
		self.assertEqual(mod.decide_decimal_action(None), mod.SKIP_MISSING_COLUMN)
		self.assertEqual(
			mod.decide_decimal_action({"DATA_TYPE": "decimal", "NUMERIC_PRECISION": 30, "NUMERIC_SCALE": 9}),
			mod.SKIP_ALREADY_CORRECT,
		)
		self.assertEqual(
			mod.decide_decimal_action({"DATA_TYPE": "decimal", "NUMERIC_PRECISION": 38, "NUMERIC_SCALE": 9}),
			mod.SKIP_ALREADY_WIDER,
		)
		self.assertEqual(
			mod.decide_decimal_action({"DATA_TYPE": "decimal", "NUMERIC_PRECISION": 21, "NUMERIC_SCALE": 9}),
			mod.ALTER_TO_DECIMAL_30_9,
		)
		self.assertEqual(
			mod.decide_decimal_action({"DATA_TYPE": "decimal", "NUMERIC_PRECISION": 21, "NUMERIC_SCALE": 2}),
			mod.SKIP_UNEXPECTED_SCALE,
		)

	@patch("erpnext_extensions.payment_entry_decimal_precision.frappe.clear_cache")
	@patch("erpnext_extensions.payment_entry_decimal_precision.make_property_setter")
	@patch("erpnext_extensions.payment_entry_decimal_precision.frappe.db.set_value")
	@patch("erpnext_extensions.payment_entry_decimal_precision.frappe.db.get_value")
	def test_property_setter_idempotent(self, mock_get_value, mock_set_value, mock_make_ps, mock_clear_cache):
		logger = MagicMock()
		mock_get_value.side_effect = [None]
		action, value = mod.ensure_length_property_setter("Payment Entry", "paid_amount", 30, logger)
		self.assertEqual((action, value), ("CREATE_METADATA_LENGTH", 30))

		mock_get_value.side_effect = ["Payment Entry-paid_amount-length", "21"]
		action, value = mod.ensure_length_property_setter("Payment Entry", "paid_amount", 30, logger)
		self.assertEqual((action, value), ("UPDATE_METADATA_LENGTH", 30))

		mock_set_value.reset_mock()
		mock_get_value.side_effect = ["Payment Entry-paid_amount-length", "38"]
		action, value = mod.ensure_length_property_setter("Payment Entry", "paid_amount", 30, logger)
		self.assertEqual((action, value), ("SKIP_METADATA_ALREADY_SET", 38))
		mock_set_value.assert_not_called()

	def test_missing_field_continues(self):
		logger = MagicMock()
		targets = (
			mod.PaymentEntryFieldTarget("Payment Entry", "missing_field"),
			mod.PaymentEntryFieldTarget("Payment Entry", "paid_amount"),
		)
		with (
			patch.object(mod, "payment_entry_field_targets", return_value=targets),
			patch("erpnext_extensions.payment_entry_decimal_precision.frappe.db.exists", return_value=True),
			patch("erpnext_extensions.payment_entry_decimal_precision.frappe.get_meta") as mock_meta,
			patch.object(mod, "table_exists", return_value=True),
			patch.object(mod, "read_column_schema") as mock_read,
			patch.object(mod, "alter_decimal_column") as mock_alter,
		):

			def _get_field(name):
				if name == "missing_field":
					return None
				return type("DF", (), {"fieldtype": "Currency"})()

			mock_meta.return_value.get_field.side_effect = _get_field
			mock_read.side_effect = [
				{
					"DATA_TYPE": "decimal",
					"COLUMN_TYPE": "decimal(21,9)",
					"NUMERIC_PRECISION": 21,
					"NUMERIC_SCALE": 9,
					"IS_NULLABLE": "YES",
					"COLUMN_DEFAULT": None,
				},
				{
					"DATA_TYPE": "decimal",
					"COLUMN_TYPE": "decimal(30,9)",
					"NUMERIC_PRECISION": 30,
					"NUMERIC_SCALE": 9,
					"IS_NULLABLE": "YES",
					"COLUMN_DEFAULT": None,
				},
			]
			rows = mod.apply_decimal_schema_targets(logger)
		self.assertEqual(rows[0]["action"], mod.SKIP_MISSING_FIELD)
		self.assertEqual(rows[1]["action"], mod.ALTER_TO_DECIMAL_30_9)
		mock_alter.assert_called_once()
