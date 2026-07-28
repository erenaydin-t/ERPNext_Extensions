# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Unit tests for Petty Management DECIMAL(30,9) allowlist and decision matrix (v2)."""

from __future__ import annotations

import inspect
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from erpnext_extensions import petty_management_decimal_precision_v2 as mod


class TestPettyManagementDecimalPrecisionV2(unittest.TestCase):
	def test_allowlists_exact(self):
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Holder"],
			(
				"max_balance",
				"account_gl_balance",
				"current_balance",
				"pending_clearance_amount",
				"consumed_amount",
			),
		)
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Request"],
			(
				"max_balance_for_petty_cash",
				"previous_balance",
				"total_requested_amount",
				"total_paid_amount",
				"remaining_to_pay",
				"total_draft_pe_amount",
				"allocated_amount",
				"available_for_clearance",
			),
		)
		self.assertEqual(mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Request Detail"], ("advance_amount",))
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Clearance"],
			(
				"funded_available",
				"opening_available",
				"total_available",
				"pending_amount",
				"current_petty_balance",
				"total_funded_amount",
				"total_cleared_amount",
				"total_expense_without_tax",
				"total_tax_amount",
				"total_expense_amount",
				"total_petty_cash",
				"remaining_amount",
			),
		)
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Clearance Detail"],
			("outstanding_amount", "allocated_amount", "amount_plus_tax"),
		)
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Clearance Request Allocation"],
			(
				"request_amount",
				"paid_amount",
				"previously_allocated_amount",
				"available_amount",
				"allocated_amount",
			),
		)
		self.assertEqual(
			mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE["PM Opening Advance"],
			(
				"opening_advance_amount",
				"previously_settled_before_migration",
				"remaining_at_cutover",
				"allocated_in_pm",
				"available_opening_balance",
			),
		)
		self.assertEqual(len(mod.petty_management_field_targets()), 39)
		self.assertEqual(
			set(mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE),
			{
				"PM Holder",
				"PM Request",
				"PM Request Detail",
				"PM Clearance",
				"PM Clearance Detail",
				"PM Clearance Request Allocation",
				"PM Opening Advance",
			},
		)

	def test_parents_and_children_included(self):
		for doctype in ("PM Holder", "PM Request", "PM Clearance"):
			self.assertIn(doctype, mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE)
		for doctype in (
			"PM Request Detail",
			"PM Clearance Detail",
			"PM Clearance Request Allocation",
		):
			self.assertIn(doctype, mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE)

	def test_no_runtime_field_scanning(self):
		source = Path(inspect.getsourcefile(mod)).read_text(encoding="utf-8")
		forbidden_snippets = (
			"keyword",
			"for df in meta.fields",
			"fieldtype == \"Currency\"",
			"fieldtype == 'Currency'",
			"endswith(\"amount\")",
			"endswith('amount')",
		)
		for snippet in forbidden_snippets:
			self.assertNotIn(snippet, source, f"forbidden scanning pattern: {snippet}")
		self.assertIn("PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE", source)

	def test_no_unrelated_doctypes_included(self):
		forbidden = {
			"PM Settings",
			"Facility",
			"Post Dated Cheque",
			"Journal Entry",
			"GL Entry",
			"Payment Entry",
			"Stock Reconciliation",
			"Sales Invoice",
			"Purchase Invoice",
		}
		for doctype in forbidden:
			self.assertNotIn(doctype, mod.PETTY_MANAGEMENT_FIELDS_BY_DOCTYPE)

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

	@patch("erpnext_extensions.petty_management_decimal_precision_v2.frappe.clear_cache")
	@patch("erpnext_extensions.petty_management_decimal_precision_v2.make_property_setter")
	@patch("erpnext_extensions.petty_management_decimal_precision_v2.frappe.db.set_value")
	@patch("erpnext_extensions.petty_management_decimal_precision_v2.frappe.db.get_value")
	def test_property_setter_create_update_skip(
		self, mock_get_value, mock_set_value, mock_make_ps, mock_clear_cache
	):
		logger = MagicMock()

		mock_get_value.side_effect = [None]
		action, value = mod.ensure_length_property_setter("PM Holder", "max_balance", 30, logger)
		self.assertEqual((action, value), ("CREATE_METADATA_LENGTH", 30))
		mock_make_ps.assert_called_once()

		mock_make_ps.reset_mock()
		mock_get_value.side_effect = ["PM Holder-max_balance-length", "21"]
		action, value = mod.ensure_length_property_setter("PM Holder", "max_balance", 30, logger)
		self.assertEqual((action, value), ("UPDATE_METADATA_LENGTH", 30))
		mock_set_value.assert_called_once()
		mock_clear_cache.assert_called()

		mock_set_value.reset_mock()
		mock_get_value.side_effect = ["PM Holder-max_balance-length", "38"]
		action, value = mod.ensure_length_property_setter("PM Holder", "max_balance", 30, logger)
		self.assertEqual((action, value), ("SKIP_METADATA_ALREADY_SET", 38))
		mock_set_value.assert_not_called()

	def test_verify_and_set_metadata_isolates_errors(self):
		logger = MagicMock()
		targets = (
			mod.PettyManagementFieldTarget("PM Holder", "max_balance"),
			mod.PettyManagementFieldTarget("PM Request", "total_requested_amount"),
		)

		with (
			patch.object(mod, "petty_management_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.petty_management_decimal_precision_v2.frappe.db.exists",
				return_value=True,
			),
			patch("erpnext_extensions.petty_management_decimal_precision_v2.frappe.get_meta") as mock_meta,
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
				"erpnext_extensions.petty_management_decimal_precision_v2.frappe.get_traceback",
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
			mod.PettyManagementFieldTarget("PM Clearance", "missing_field"),
			mod.PettyManagementFieldTarget("PM Holder", "current_balance"),
		)

		with (
			patch.object(mod, "petty_management_field_targets", return_value=targets),
			patch(
				"erpnext_extensions.petty_management_decimal_precision_v2.frappe.db.exists",
				return_value=True,
			),
			patch("erpnext_extensions.petty_management_decimal_precision_v2.frappe.get_meta") as mock_meta,
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
