# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for PDC / Cheque / Ledger DECIMAL(30,9) allowlist and decision matrix."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from erpnext_extensions.cheque_management import pdc_decimal_precision_v2 as mod


class TestPdcChequeLedgerDecimalPrecisionV2(unittest.TestCase):
	def test_allowlists_exact(self):
		self.assertEqual(
			mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE["Post Dated Cheque"],
			("cheque_amount", "allocated_amount", "unallocated_amount"),
		)
		self.assertEqual(mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE["PDC Allocation"], ("amount",))
		self.assertEqual(mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE["PDC Journal Reference"], ("amount",))
		self.assertEqual(mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE["Guarantee Document"], ("amount",))
		self.assertEqual(
			mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE["Payment Ledger Entry"],
			("amount", "amount_in_account_currency"),
		)
		self.assertEqual(len(mod.pdc_cheque_ledger_field_targets()), 8)

	def test_no_unrelated_doctypes_included(self):
		forbidden = {
			"Facility",
			"Facility Repayment",
			"Journal Entry",
			"GL Entry",
			"Payment Entry",
			"Stock Reconciliation",
			"Account Closing Balance",
			"Sales Invoice",
			"Sales Order",
		}
		for doctype in forbidden:
			self.assertNotIn(doctype, mod.PDC_CHEQUE_LEDGER_FIELDS_BY_DOCTYPE)

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

	@patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.clear_cache")
	@patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.make_property_setter")
	@patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.db.set_value")
	@patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.db.get_value")
	def test_property_setter_create_update_skip(
		self, mock_get_value, mock_set_value, mock_make_ps, mock_clear_cache
	):
		logger = MagicMock()

		mock_get_value.side_effect = [None]
		action, value = mod.ensure_length_property_setter("Post Dated Cheque", "cheque_amount", 30, logger)
		self.assertEqual((action, value), ("CREATE_METADATA_LENGTH", 30))
		mock_make_ps.assert_called_once()

		mock_make_ps.reset_mock()
		mock_get_value.side_effect = ["Post Dated Cheque-cheque_amount-length", "21"]
		action, value = mod.ensure_length_property_setter("Post Dated Cheque", "cheque_amount", 30, logger)
		self.assertEqual((action, value), ("UPDATE_METADATA_LENGTH", 30))
		mock_set_value.assert_called_once()
		mock_clear_cache.assert_called()

		mock_set_value.reset_mock()
		mock_get_value.side_effect = ["Post Dated Cheque-cheque_amount-length", "38"]
		action, value = mod.ensure_length_property_setter("Post Dated Cheque", "cheque_amount", 30, logger)
		self.assertEqual((action, value), ("SKIP_METADATA_ALREADY_SET", 38))
		mock_set_value.assert_not_called()

	def test_verify_and_set_metadata_isolates_errors(self):
		logger = MagicMock()
		targets = (
			mod.PdcChequeLedgerFieldTarget("Post Dated Cheque", "cheque_amount"),
			mod.PdcChequeLedgerFieldTarget("PDC Allocation", "amount"),
		)

		with (
			patch.object(mod, "pdc_cheque_ledger_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.db.exists",
				return_value=True,
			),
			patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.get_meta") as mock_meta,
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
				"erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.get_traceback",
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
			mod.PdcChequeLedgerFieldTarget("Post Dated Cheque", "missing_field"),
			mod.PdcChequeLedgerFieldTarget("Guarantee Document", "amount"),
		)

		with (
			patch.object(mod, "pdc_cheque_ledger_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.db.exists",
				return_value=True,
			),
			patch("erpnext_extensions.cheque_management.pdc_decimal_precision_v2.frappe.get_meta") as mock_meta,
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
