# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for Accounting Core DECIMAL(30,9) allowlist and decision matrix."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from erpnext_extensions import accounting_core_decimal_precision as mod


class TestAccountingCoreDecimalPrecision(unittest.TestCase):
	def test_allowlists_exact(self):
		self.assertEqual(
			mod.ACCOUNTING_CORE_FIELDS_BY_DOCTYPE["Journal Entry"],
			("total_debit", "total_credit", "difference", "total_amount"),
		)
		self.assertEqual(
			mod.ACCOUNTING_CORE_FIELDS_BY_DOCTYPE["Journal Entry Account"],
			("debit", "credit", "debit_in_account_currency", "credit_in_account_currency"),
		)
		self.assertEqual(
			mod.ACCOUNTING_CORE_FIELDS_BY_DOCTYPE["GL Entry"],
			(
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"debit_in_transaction_currency",
				"credit_in_transaction_currency",
				"debit_in_reporting_currency",
				"credit_in_reporting_currency",
				"transaction_exchange_rate",
				"reporting_currency_exchange_rate",
			),
		)
		self.assertEqual(
			mod.ACCOUNTING_CORE_FIELDS_BY_DOCTYPE["Account Closing Balance"],
			(
				"debit",
				"credit",
				"debit_in_account_currency",
				"credit_in_account_currency",
				"debit_in_reporting_currency",
				"credit_in_reporting_currency",
				"reporting_currency_exchange_rate",
			),
		)
		self.assertNotIn("Payment Entry", mod.ACCOUNTING_CORE_FIELDS_BY_DOCTYPE)
		self.assertEqual(len(mod.accounting_core_field_targets()), 25)

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
		self.assertEqual(
			mod.decide_decimal_action({"DATA_TYPE": "double", "NUMERIC_PRECISION": None, "NUMERIC_SCALE": None}),
			mod.SKIP_UNEXPECTED_TYPE,
		)

	@patch("erpnext_extensions.accounting_core_decimal_precision.frappe.clear_cache")
	@patch("erpnext_extensions.accounting_core_decimal_precision.make_property_setter")
	@patch("erpnext_extensions.accounting_core_decimal_precision.frappe.db.set_value")
	@patch("erpnext_extensions.accounting_core_decimal_precision.frappe.db.get_value")
	def test_property_setter_create_update_skip(
		self, mock_get_value, mock_set_value, mock_make_ps, mock_clear_cache
	):
		logger = MagicMock()

		mock_get_value.side_effect = [None]
		action, value = mod.ensure_length_property_setter("Journal Entry", "total_debit", 30, logger)
		self.assertEqual((action, value), ("CREATE_METADATA_LENGTH", 30))
		mock_make_ps.assert_called_once()

		mock_make_ps.reset_mock()
		mock_get_value.side_effect = ["Journal Entry-total_debit-length", "21"]
		action, value = mod.ensure_length_property_setter("Journal Entry", "total_debit", 30, logger)
		self.assertEqual((action, value), ("UPDATE_METADATA_LENGTH", 30))
		mock_set_value.assert_called_once()
		mock_clear_cache.assert_called()

		mock_set_value.reset_mock()
		mock_get_value.side_effect = ["Journal Entry-total_debit-length", "38"]
		action, value = mod.ensure_length_property_setter("Journal Entry", "total_debit", 30, logger)
		self.assertEqual((action, value), ("SKIP_METADATA_ALREADY_SET", 38))
		mock_set_value.assert_not_called()

	def test_verify_and_set_metadata_isolates_errors(self):
		logger = MagicMock()
		targets = (
			mod.AccountingCoreFieldTarget("Journal Entry", "total_debit"),
			mod.AccountingCoreFieldTarget("Journal Entry", "total_credit"),
		)

		with (
			patch.object(mod, "accounting_core_field_targets", return_value=targets),
			patch("erpnext_extensions.accounting_core_decimal_precision.frappe.db.exists", return_value=True),
			patch("erpnext_extensions.accounting_core_decimal_precision.frappe.get_meta") as mock_meta,
			patch.object(
				mod,
				"read_column_schema",
				return_value={"DATA_TYPE": "decimal", "NUMERIC_PRECISION": 21, "NUMERIC_SCALE": 9},
			),
			patch.object(
				mod,
				"ensure_length_property_setter",
				side_effect=[Exception("boom"), ("CREATE_METADATA_LENGTH", 30)],
			),
			patch(
				"erpnext_extensions.accounting_core_decimal_precision.frappe.get_traceback",
				return_value="traceback",
			),
		):
			mock_meta.return_value.get_field.side_effect = [
				type("DF", (), {"fieldtype": "Currency"})(),
				type("DF", (), {"fieldtype": "Currency"})(),
			]
			rows = mod.verify_and_set_metadata(logger)

		self.assertEqual(len(rows), 2)
		self.assertEqual(rows[0]["status"], "error")
		self.assertEqual(rows[1]["metadata_action"], "CREATE_METADATA_LENGTH")

	def test_apply_decimal_schema_targets_missing_field_continues(self):
		logger = MagicMock()
		targets = (
			mod.AccountingCoreFieldTarget("Journal Entry", "missing_field"),
			mod.AccountingCoreFieldTarget("Account Closing Balance", "debit"),
		)

		with (
			patch.object(mod, "accounting_core_field_targets", return_value=targets),
			patch("erpnext_extensions.accounting_core_decimal_precision.frappe.db.exists", return_value=True),
			patch("erpnext_extensions.accounting_core_decimal_precision.frappe.get_meta") as mock_meta,
			patch.object(mod, "table_exists", return_value=True),
			patch.object(mod, "read_column_schema") as mock_read,
			patch.object(mod, "alter_decimal_column") as mock_alter,
		):
			def _get_field(name):
				if name == "missing_field":
					return None
				return type("DF", (), {"fieldtype": "Currency"})()

			mock_meta.return_value.get_field.side_effect = _get_field
			mock_read.return_value = {
				"DATA_TYPE": "decimal",
				"COLUMN_TYPE": "decimal(21,9)",
				"NUMERIC_PRECISION": 21,
				"NUMERIC_SCALE": 9,
				"IS_NULLABLE": "NO",
				"COLUMN_DEFAULT": "0",
			}
			# after ALTER read returns 30,9
			mock_read.side_effect = [
				{
					"DATA_TYPE": "decimal",
					"COLUMN_TYPE": "decimal(21,9)",
					"NUMERIC_PRECISION": 21,
					"NUMERIC_SCALE": 9,
					"IS_NULLABLE": "NO",
					"COLUMN_DEFAULT": "0",
				},
				{
					"DATA_TYPE": "decimal",
					"COLUMN_TYPE": "decimal(30,9)",
					"NUMERIC_PRECISION": 30,
					"NUMERIC_SCALE": 9,
					"IS_NULLABLE": "NO",
					"COLUMN_DEFAULT": "0",
				},
			]
			rows = mod.apply_decimal_schema_targets(logger)

		self.assertEqual(rows[0]["action"], mod.SKIP_MISSING_FIELD)
		self.assertEqual(rows[1]["action"], mod.ALTER_TO_DECIMAL_30_9)
		mock_alter.assert_called_once()
