# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import inspect
import unittest
from unittest.mock import patch

import frappe
from frappe.utils import flt, nowtime, random_string, today

from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_warehouse,
)
from erpnext_extensions.iran_accounting.integration.bootstrap import apply
from erpnext_extensions.iran_accounting.tests.test_stock_ledger_reconciliation_balance import (
	_ensure_batch,
	_ensure_batch_item,
	_inward_sr_bundle,
	_opening_sr_multi_line,
	_sr_expense_account,
)
from erpnext_extensions.iran_accounting.utils import repost_stock_reconciliation_valuation as bulk


class TestBulkRepostStockReconciliationDetection(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)

	def test_correct_sr_not_flagged_affected(self):
		item = _ensure_batch_item(self.company, "IA-BULK-REP-OK")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(100, 1000), (10, 1000)])
		frappe.db.commit()
		issues = bulk.sle_balance_issues_for_voucher(sr.name, self.company)
		self.assertEqual(issues, [])

	def test_corrupted_balance_detected_and_dry_run_scope(self):
		item = _ensure_batch_item(self.company, "IA-BULK-REP-BAD")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(100, 1000), (10, 1000)])
		frappe.db.commit()
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": sr.name, "is_cancelled": 0},
			fields=["name", "stock_value", "stock_value_difference"],
			order_by="creation asc",
		)
		self.assertEqual(len(sles), 2)
		frappe.db.set_value(
			"Stock Ledger Entry",
			sles[1].name,
			"stock_value",
			flt(sles[1].stock_value_difference),
			update_modified=False,
		)
		frappe.db.commit()

		out = bulk.bulk_repost_stock_reconciliation_valuation(
			from_date=today(),
			company=self.company,
			dry_run=True,
			voucher_nos=[sr.name],
		)
		self.assertIn(sr.name, out["affected_vouchers"])
		self.assertIn(item, out["affected_items"])
		self.assertIn(self.wh, out["affected_warehouses"])
		self.assertEqual(out["created_repost_jobs"], [])

	def test_repost_job_created_without_direct_sle_writes_in_utility(self):
		for fn in (bulk.create_repost_item_valuation_for_sr, bulk.bulk_repost_stock_reconciliation_valuation):
			src = inspect.getsource(fn)
			self.assertNotIn("db_set", src)
			self.assertNotIn("db_update", src)
			self.assertNotIn("frappe.db.sql", src)

		item = _ensure_batch_item(self.company, "IA-BULK-REP-JOB")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(50, 2000), (5, 2000)])
		frappe.db.commit()
		sles = frappe.get_all(
			"Stock Ledger Entry",
			filters={"voucher_no": sr.name, "is_cancelled": 0},
			order_by="creation asc",
			pluck="name",
		)
		frappe.db.set_value("Stock Ledger Entry", sles[1], "stock_value", 10000, update_modified=False)
		frappe.db.commit()

		if not frappe.db.exists("DocType", "Repost Item Valuation"):
			self.skipTest("Repost Item Valuation not installed")

		sle_updates: list[str] = []

		orig_update = frappe.model.document.Document.db_update

		def _track_db_update(self, *args, **kwargs):
			if self.doctype == "Stock Ledger Entry":
				sle_updates.append(self.name)
			return orig_update(self, *args, **kwargs)

		with patch.object(frappe.model.document.Document, "db_update", _track_db_update):
			out = bulk.bulk_repost_stock_reconciliation_valuation(
				from_date=today(),
				company=self.company,
				dry_run=False,
				voucher_nos=[sr.name],
				execute_repost=False,
			)

		self.assertEqual(len(out["created_repost_jobs"]), 1)
		job = out["created_repost_jobs"][0]
		self.assertTrue(job.get("repost_name"))
		self.assertEqual(job.get("status"), "Queued")
		self.assertFalse(sle_updates, "utility must not db_update Stock Ledger Entry rows")
		self.assertTrue(
			frappe.db.exists("Repost Item Valuation", job["repost_name"]),
			"RIV document must exist",
		)

	def test_multiple_vouchers_in_scan(self):
		names = []
		for tag in ("A", "B"):
			item = _ensure_batch_item(self.company, f"IA-BULK-MULTI-{tag}")
			sr = _opening_sr_multi_line(self.company, self.wh, item, [(20, 500), (2, 500)])
			frappe.db.commit()
			names.append(sr.name)
			sles = frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_no": sr.name, "is_cancelled": 0},
				order_by="creation asc",
				pluck="name",
			)
			frappe.db.set_value("Stock Ledger Entry", sles[1], "stock_value", 1000, update_modified=False)
		frappe.db.commit()

		out = bulk.find_affected_stock_reconciliations(self.company, today(), voucher_nos=names)
		self.assertEqual(set(out["affected_vouchers"]), set(names))


if __name__ == "__main__":
	unittest.main()
