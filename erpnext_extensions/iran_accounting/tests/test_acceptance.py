# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

import frappe

from erpnext_extensions.iran_accounting.acceptance import (
	_check_irr_settings,
	_overall_status,
	_row,
)


class TestAcceptanceRunner(unittest.TestCase):
	def test_overall_status_pass_and_fail(self):
		rows = [
			_row("settings", "Co", "PASS"),
			_row("GL Entry", "x", "FAIL"),
		]
		self.assertEqual(_overall_status(rows), "FAIL")
		rows[1]["status"] = "PASS"
		self.assertEqual(_overall_status(rows), "PASS")

	def test_overall_status_ignores_manual_required(self):
		rows = [_row("Print", "", "MANUAL_REQUIRED", manual_required=True)]
		self.assertEqual(_overall_status(rows), "PASS")

	def test_check_irr_settings_mock(self):
		with (
			mock.patch(
				"erpnext_extensions.iran_accounting.acceptance.get_company_currency", return_value="IRR"
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.acceptance.get_currency_precision", return_value=0
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.acceptance.frappe.db.get_single_value", return_value=None
			),
			mock.patch(
				"erpnext_extensions.iran_accounting.acceptance.frappe.db.get_value", return_value="#,###"
			),
		):
			rows, info = _check_irr_settings("ESPAD")
		self.assertEqual(rows[0]["status"], "PASS")
		self.assertEqual(info["resolved_irr_precision"], 0)


@unittest.skipUnless(getattr(frappe, "db", None), "needs site")
class TestAcceptanceRunnerSite(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")

	def test_run_structure_without_synthetic(self):
		from erpnext_extensions.iran_accounting.acceptance import run as acceptance_run

		out = acceptance_run(company=None, stock_entry_vouchers=[], include_synthetic=False)
		self.assertIn("status", out)
		self.assertIn("rows", out)
		self.assertTrue(out["rows"])


if __name__ == "__main__":
	unittest.main()
