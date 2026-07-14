# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import csv
import io
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import frappe

from erpnext_extensions.iran_accounting.account_explorer import api, export
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	disable_export,
	enable_export,
	enable_wave2a_analysis,
	enable_wave2b_voucher,
	enable_wave2c_unified_party,
	require_site,
)


def _fake_spec(view_axis: str, *, dimension_type: str | None = None):
	return SimpleNamespace(
		view_axis=view_axis,
		dimension_scope=SimpleNamespace(dimension_type=dimension_type),
	)


class TestAccountExplorerExportStructure(unittest.TestCase):
	def test_csv_structure(self):
		spec = _fake_spec("account_level")
		columns = export.get_export_columns(spec)
		rows = [
			{
				"display_code": "1000",
				"display_title": "Cash",
				"opening_debit": 10,
				"opening_credit": 0,
				"period_debit": 100,
				"period_credit": 50,
				"debit_balance": 60,
				"credit_balance": 0,
			}
		]
		content = export.build_csv_content(rows, columns)
		reader = csv.reader(io.StringIO(content))
		parsed = list(reader)
		self.assertEqual(len(parsed), 2)
		self.assertIn("Account Code", parsed[0])
		self.assertIn("Closing Credit", parsed[0])
		self.assertEqual(parsed[1][0], "1000")

	def test_xlsx_generation(self):
		spec = _fake_spec("party")
		columns = export.get_export_columns(spec)
		rows = [
			{
				"party_type": "Customer",
				"display_code": "CUST-001",
				"display_title": "Acme",
				"period_debit": 100,
				"period_credit": 0,
				"debit_balance": 100,
				"credit_balance": 0,
			}
		]
		content = export.build_xlsx_content(rows, columns)
		self.assertTrue(content.startswith(b"PK"))

	def test_currency_export_columns_are_native(self):
		columns = export.get_export_columns(_fake_spec("currency"))
		labels = [column["label"] for column in columns]
		self.assertEqual(labels, ["Currency", "Native Debit", "Native Credit", "Native Net"])
		fieldnames = [column["fieldname"] for column in columns]
		self.assertNotIn("presentation_currency", fieldnames)


class TestAccountExplorerExport(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		enable_wave2b_voucher(include_wave2a=False)
		enable_wave2c_unified_party(include_wave2b=True)
		enable_export()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def tearDown(self):
		frappe.set_user("Administrator")
		enable_export(threshold=5000)

	def _reset_response(self):
		frappe.local.response = frappe._dict()

	def _export_sync(self, payload, file_format="csv"):
		self._reset_response()
		return export.export_account_explorer(payload, file_format, force_sync=True)

	def test_export_disabled_permission(self):
		disable_export()
		payload = build_payload(self.company, self.fiscal_year, self.from_date, self.to_date)
		with self.assertRaises(frappe.ValidationError):
			self._export_sync(payload)
		enable_export()

	def test_metadata_includes_export_settings(self):
		meta = api.get_metadata()
		self.assertIn("export_enabled", meta)
		self.assertIn("export_background_threshold", meta)
		self.assertEqual(meta.get("export_enabled"), 1)

	def test_account_axis_export(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={"hide_zero_rows": 0},
		)
		result = self._export_sync(payload, "csv")
		self.assertEqual(result.get("queued"), 0)
		self.assertEqual(frappe.local.response.type, "download")
		reader = csv.reader(io.StringIO(frappe.local.response.filecontent))
		headers = next(reader)
		self.assertIn("Account Code", headers)
		self.assertIn("Opening Debit", headers)
		self.assertIn("Closing Credit", headers)

	def test_party_axis_export(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "party"},
			document={"hide_zero_rows": 0},
		)
		self._export_sync(payload, "csv")
		reader = csv.reader(io.StringIO(frappe.local.response.filecontent))
		headers = next(reader)
		self.assertIn("Party Type", headers)
		self.assertIn("Party Name", headers)

	def test_dimension_axis_export(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center on GL Entry")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
			document={"hide_zero_rows": 0},
		)
		self._export_sync(payload, "csv")
		reader = csv.reader(io.StringIO(frappe.local.response.filecontent))
		headers = next(reader)
		self.assertIn("Dimension Type", headers)
		self.assertIn("Dimension Value", headers)

	def test_currency_export_without_conversion(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "currency"},
			document={"hide_zero_rows": 0},
		)
		self._export_sync(payload, "csv")
		reader = csv.reader(io.StringIO(frappe.local.response.filecontent))
		headers = next(reader)
		self.assertEqual(headers, ["Currency", "Native Debit", "Native Credit", "Native Net"])

	def test_voucher_axis_export(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "voucher"},
			document={"hide_zero_rows": 0},
		)
		self._export_sync(payload, "xlsx")
		self.assertEqual(frappe.local.response.type, "download")
		self.assertTrue(frappe.local.response.filecontent.startswith(b"PK"))
		self.assertTrue(frappe.local.response.filename.endswith(".xlsx"))

	def test_company_permission(self):
		payload = build_payload(self.company, self.fiscal_year, self.from_date, self.to_date)
		with patch(
			"erpnext_extensions.iran_accounting.account_explorer.query_spec.assert_company_allowed",
			side_effect=frappe.PermissionError("Not permitted for company"),
		):
			with self.assertRaises(frappe.PermissionError):
				self._export_sync(payload)

	def test_large_export_threshold(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={"hide_zero_rows": 0},
		)
		enable_export(threshold=0)
		with patch("frappe.enqueue") as enqueue_mock:
			with patch.object(export, "_probe_export_size", return_value=1):
				result = export.export_account_explorer(payload, "csv", force_sync=False)
		self.assertEqual(result.get("queued"), 1)
		enqueue_mock.assert_called_once()
		self.assertIn("background", (result.get("message") or "").lower())

	def test_unified_party_axis_export(self):
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={"view_axis": "unified_party"},
			document={"hide_zero_rows": 0},
		)
		self._export_sync(payload, "csv")
		reader = csv.reader(io.StringIO(frappe.local.response.filecontent))
		headers = next(reader)
		self.assertIn("Unified Party", headers)
		self.assertIn("Member Count", headers)

	def test_whitelisted_export_entry_point(self):
		from erpnext_extensions.iran_accounting.account_explorer import export_account_explorer

		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			document={"hide_zero_rows": 0},
		)
		self._reset_response()
		export_account_explorer(payload, "csv")
		self.assertEqual(frappe.local.response.type, "download")
