# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for Stock Reconciliation DECIMAL(30,9) allowlist and decision matrix (v4)."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from erpnext_extensions import stock_reconciliation_decimal_precision_v4 as mod


class TestStockReconciliationDecimalPrecisionV4(unittest.TestCase):
	def test_allowlists_exact(self):
		self.assertEqual(
			mod.STOCK_RECONCILIATION_FIELDS_BY_DOCTYPE["Stock Reconciliation"],
			("difference_amount",),
		)
		self.assertEqual(
			mod.STOCK_RECONCILIATION_FIELDS_BY_DOCTYPE["Stock Reconciliation Item"],
			(
				"qty",
				"valuation_rate",
				"amount",
				"current_qty",
				"current_valuation_rate",
				"current_amount",
				"amount_difference",
			),
		)
		self.assertEqual(len(mod.stock_reconciliation_field_targets()), 8)
		self.assertEqual(set(mod.STOCK_RECONCILIATION_FIELDS_BY_DOCTYPE), {
			"Stock Reconciliation",
			"Stock Reconciliation Item",
		})

	def test_no_dynamic_keyword_discovery(self):
		source = Path(inspect.getsourcefile(mod)).read_text(encoding="utf-8")
		forbidden_snippets = (
			"keyword",
			"discover",
			"for df in meta.fields",
			"fieldtype == \"Currency\"",
			"fieldtype == 'Currency'",
			"endswith(\"amount\")",
			"endswith('amount')",
		)
		for snippet in forbidden_snippets:
			self.assertNotIn(snippet, source, f"forbidden discovery pattern: {snippet}")
		self.assertIn("STOCK_RECONCILIATION_FIELDS_BY_DOCTYPE", source)

	def test_no_unrelated_doctypes_included(self):
		forbidden = {
			"Stock Entry",
			"Stock Ledger Entry",
			"GL Entry",
			"Facility",
			"Facility Repayment",
			"Post Dated Cheque",
			"Payment Ledger Entry",
			"Journal Entry",
			"Payment Entry",
			"Sales Invoice",
		}
		for doctype in forbidden:
			self.assertNotIn(doctype, mod.STOCK_RECONCILIATION_FIELDS_BY_DOCTYPE)

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

	@patch("erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.clear_cache")
	@patch("erpnext_extensions.stock_reconciliation_decimal_precision_v4.make_property_setter")
	@patch("erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.db.set_value")
	@patch("erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.db.get_value")
	def test_property_setter_create_update_skip(
		self, mock_get_value, mock_set_value, mock_make_ps, mock_clear_cache
	):
		logger = MagicMock()

		mock_get_value.side_effect = [None]
		action, value = mod.ensure_length_property_setter(
			"Stock Reconciliation", "difference_amount", 30, logger
		)
		self.assertEqual((action, value), ("CREATE_METADATA_LENGTH", 30))
		mock_make_ps.assert_called_once()

		mock_make_ps.reset_mock()
		mock_get_value.side_effect = ["Stock Reconciliation-difference_amount-length", "21"]
		action, value = mod.ensure_length_property_setter(
			"Stock Reconciliation", "difference_amount", 30, logger
		)
		self.assertEqual((action, value), ("UPDATE_METADATA_LENGTH", 30))
		mock_set_value.assert_called_once()
		mock_clear_cache.assert_called()

		mock_set_value.reset_mock()
		mock_get_value.side_effect = ["Stock Reconciliation-difference_amount-length", "38"]
		action, value = mod.ensure_length_property_setter(
			"Stock Reconciliation", "difference_amount", 30, logger
		)
		self.assertEqual((action, value), ("SKIP_METADATA_ALREADY_SET", 38))
		mock_set_value.assert_not_called()

	def test_verify_and_set_metadata_isolates_errors(self):
		logger = MagicMock()
		targets = (
			mod.StockReconciliationFieldTarget("Stock Reconciliation", "difference_amount"),
			mod.StockReconciliationFieldTarget("Stock Reconciliation Item", "amount"),
		)

		with (
			patch.object(mod, "stock_reconciliation_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.db.exists",
				return_value=True,
			),
			patch(
				"erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.get_meta"
			) as mock_meta,
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
				"erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.get_traceback",
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
			mod.StockReconciliationFieldTarget("Stock Reconciliation", "missing_field"),
			mod.StockReconciliationFieldTarget("Stock Reconciliation Item", "qty"),
		)

		with (
			patch.object(mod, "stock_reconciliation_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.db.exists",
				return_value=True,
			),
			patch(
				"erpnext_extensions.stock_reconciliation_decimal_precision_v4.frappe.get_meta"
			) as mock_meta,
			patch.object(mod, "table_exists", return_value=True),
			patch.object(mod, "read_column_schema") as mock_read,
			patch.object(mod, "alter_decimal_column") as mock_alter,
		):

			def _get_field(name):
				if name == "missing_field":
					return None
				return type("DF", (), {"fieldtype": "Float"})()

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

	def test_summarize_results_groups_changed_skipped_errors(self):
		summary = mod.summarize_results(
			[
				{"doctype": "A", "field": "x", "action": mod.ALTER_TO_DECIMAL_30_9, "status": "ok"},
				{"doctype": "B", "field": "y", "action": mod.SKIP_ALREADY_CORRECT, "status": "ok"},
				{"doctype": "C", "field": "z", "action": "SQL_EXCEPTION", "status": "error"},
			]
		)
		self.assertEqual(summary["changed"], ["A.x"])
		self.assertEqual(summary["skipped"], ["B.y"])
		self.assertEqual(summary["errors"], ["C.z"])
		self.assertEqual(summary["total"], 3)
