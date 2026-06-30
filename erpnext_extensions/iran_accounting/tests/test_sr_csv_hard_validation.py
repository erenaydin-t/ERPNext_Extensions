# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import os
import unittest

import frappe

from erpnext_extensions.iran_accounting.sr_csv_hard_validation import (
	DEFAULT_VOUCHERS,
	compute_csv_expected,
	load_csv_rows,
	run_hard_validation,
	validate_erpnext_voucher,
)


def _fixture_csv_path() -> str:
	return os.path.join(
		os.path.dirname(__file__),
		"fixtures",
		"Items (6)(1).csv",
	)


class TestSrCsvHardValidation(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_csv_recompute_header_is_sum_amount_difference(self):
		path = _fixture_csv_path()
		if not os.path.isfile(path):
			self.skipTest(f"Place export at {path}")
		rows, currency = load_csv_rows(path)
		block = compute_csv_expected(rows, currency)
		self.assertFalse(block["row_failures"], block["row_failures"])
		total = sum(line["expected_amount_difference"] for line in block["lines"])
		self.assertEqual(block["csv_expected_header"], total)

	def test_erpnext_vouchers_match_db_sum_when_submitted(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		for name in DEFAULT_VOUCHERS:
			if not frappe.db.exists("Stock Reconciliation", name):
				continue
			if frappe.db.get_value("Stock Reconciliation", name, "docstatus") != 1:
				continue
			out = validate_erpnext_voucher(name)
			self.assertEqual(out["status"], "PASS", f"{name}: {out.get('failures')}")

	def test_full_run_with_csv_if_present(self):
		path = _fixture_csv_path()
		if not os.path.isfile(path):
			self.skipTest(f"Place export at {path}")
		result = run_hard_validation(csv_path=path)
		self.assertEqual(result["overall"], "PASS", result.get("failures"))
