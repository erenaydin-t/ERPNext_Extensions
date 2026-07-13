# Copyright (c) 2026, ERPNext Extensions contributors
"""Stock Reconciliation SLE warehouse cumulative balance (not per-row amount)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt, nowtime, random_string, today

from erpnext_extensions.iran_accounting.domain.stock_ledger_deterministic import (
	irr_avg_rate_from_balance,
	resolve_irr_balance_avg_rate,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	get_irr_company,
	get_warehouse,
)
from erpnext_extensions.iran_accounting.integration.bootstrap import apply
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


def _ensure_batch_item(company: str, prefix: str) -> str:
	item_code = ensure_test_item(company, prefix)
	frappe.db.set_value(
		"Item",
		item_code,
		{"has_batch_no": 1, "create_new_batch": 1},
		update_modified=False,
	)
	return item_code


def _ensure_batch(item_code: str, batch_id: str) -> str:
	if not frappe.db.exists("Batch", batch_id):
		frappe.get_doc({"doctype": "Batch", "batch_id": batch_id, "item": item_code}).insert(
			ignore_permissions=True
		)
	return batch_id


def _inward_sr_bundle(
	item_code: str, warehouse: str, company: str, qty: float, rate: float, batch_no: str
) -> str:
	from erpnext.stock.doctype.serial_and_batch_bundle.serial_and_batch_bundle import combine_datetime
	from erpnext.stock.serial_batch_bundle import SerialBatchCreation

	posting_datetime = combine_datetime(today(), nowtime())
	sb = SerialBatchCreation(
		{
			"item_code": item_code,
			"warehouse": warehouse,
			"voucher_type": "Stock Reconciliation",
			"posting_datetime": posting_datetime,
			"qty": qty,
			"avg_rate": rate,
			"batches": {batch_no: qty},
			"type_of_transaction": "Inward",
			"company": company,
			"do_not_submit": True,
		}
	)
	return sb.make_serial_and_batch_bundle().name


def _sr_expense_account(company: str) -> str:
	return frappe.get_cached_value("Company", company, "temporary_opening_account") or frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Temporary", "is_group": 0},
		"name",
	)


def _opening_sr_multi_line(company: str, warehouse: str, item_code: str, lines: list[tuple[float, float]]):
	"""lines: list of (qty, rate); distinct batch + bundle per row (same item + warehouse)."""
	sr = frappe.new_doc("Stock Reconciliation")
	sr.purpose = "Opening Stock"
	sr.company = company
	sr.posting_date = today()
	sr.posting_time = nowtime()
	sr.set_posting_time = 1
	sr.expense_account = _sr_expense_account(company)
	sr.cost_center = frappe.get_cached_value("Company", company, "cost_center")
	sr.difference_account = sr.expense_account
	item_doc = frappe.get_doc("Item", item_code)
	for idx, (qty, rate) in enumerate(lines):
		batch_no = _ensure_batch(item_code, f"{item_code}-bal-{idx}-{random_string(4)}")
		bundle = _inward_sr_bundle(item_code, warehouse, company, qty, rate, batch_no)
		sr.append(
			"items",
			{
				"item_code": item_code,
				"warehouse": warehouse,
				"qty": qty,
				"valuation_rate": rate,
				"current_qty": 0,
				"current_valuation_rate": 0,
				"batch_no": batch_no,
				"reconcile_all_serial_batch": 0,
				"serial_and_batch_bundle": bundle,
				"uom": item_doc.stock_uom,
				"stock_uom": item_doc.stock_uom,
			},
		)
	sr.insert(ignore_permissions=True)
	sr.submit()
	return sr


def _sles_for_voucher(voucher_no: str, item_code: str):
	return frappe.get_all(
		"Stock Ledger Entry",
		filters={
			"voucher_type": "Stock Reconciliation",
			"voucher_no": voucher_no,
			"item_code": item_code,
			"is_cancelled": 0,
		},
		fields=[
			"name",
			"actual_qty",
			"qty_after_transaction",
			"stock_value",
			"stock_value_difference",
			"valuation_rate",
			"serial_and_batch_bundle",
		],
		order_by="creation asc",
	)


class TestStockLedgerReconciliationBalance(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)

	def test_multi_line_opening_sr_cumulative_stock_value(self):
		item = _ensure_batch_item(self.company, "IA-SR-BAL-MULTI")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(100, 1000), (10, 1000)])
		frappe.db.commit()
		sles = _sles_for_voucher(sr.name, item)
		self.assertEqual(len(sles), 2)
		self.assertEqual(flt(sles[0].qty_after_transaction), 100)
		self.assertEqual(flt(sles[0].stock_value), 100_000)
		self.assertEqual(flt(sles[1].qty_after_transaction), 110)
		self.assertEqual(flt(sles[1].stock_value), 110_000)
		self.assertNotEqual(flt(sles[1].stock_value), 10_000)

	def test_multi_line_balance_chain_integrity(self):
		item = _ensure_batch_item(self.company, "IA-SR-BAL-CHAIN")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(50, 2000), (25, 2000), (5, 2000)])
		frappe.db.commit()
		sles = _sles_for_voucher(sr.name, item)
		running = 0.0
		for sle in sles:
			running += flt(sle.stock_value_difference)
			self.assertEqual(flt(sle.stock_value), running)
			self.assertEqual(flt(sle.qty_after_transaction), running / 2000)

	def test_batch_opening_sr_warehouse_cumulative_qty_and_value(self):
		item = _ensure_batch_item(self.company, "IA-SR-BAL-BATCH")
		b1 = _ensure_batch(item, f"{item}-b1-{random_string(4)}")
		b2 = _ensure_batch(item, f"{item}-b2-{random_string(4)}")
		sr = frappe.new_doc("Stock Reconciliation")
		sr.purpose = "Opening Stock"
		sr.company = self.company
		sr.posting_date = today()
		sr.posting_time = nowtime()
		sr.set_posting_time = 1
		sr.expense_account = _sr_expense_account(self.company)
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.difference_account = sr.expense_account
		item_doc = frappe.get_doc("Item", item)
		for qty, batch_no in ((100, b1), (10, b2)):
			bundle = _inward_sr_bundle(item, self.wh, self.company, qty, 1000, batch_no)
			sr.append(
				"items",
				{
					"item_code": item,
					"warehouse": self.wh,
					"qty": qty,
					"valuation_rate": 1000,
					"current_qty": 0,
					"current_valuation_rate": 0,
					"batch_no": batch_no,
					"reconcile_all_serial_batch": 0,
					"serial_and_batch_bundle": bundle,
					"uom": item_doc.stock_uom,
					"stock_uom": item_doc.stock_uom,
				},
			)
		sr.insert(ignore_permissions=True)
		sr.submit()
		frappe.db.commit()
		sles = _sles_for_voucher(sr.name, item)
		self.assertGreaterEqual(len(sles), 2)
		self.assertEqual(flt(sles[-1].qty_after_transaction), 110)
		self.assertEqual(flt(sles[-1].stock_value), 110_000)
		for sle in sles:
			self.assertEqual(flt(sle.stock_value_difference), flt(sle.actual_qty) * 1000)

	def test_irr_valuation_rate_matches_balance_over_qty(self):
		item = _ensure_batch_item(self.company, "IA-SR-BAL-VRATE")
		sr = _opening_sr_multi_line(self.company, self.wh, item, [(100, 1000), (10, 1000)])
		frappe.db.commit()
		ccy = frappe.db.get_value("Company", self.company, "default_currency")
		for sle in _sles_for_voucher(sr.name, item):
			qty = flt(sle.qty_after_transaction)
			val = flt(sle.stock_value)
			exp = resolve_irr_balance_avg_rate(
				{"stock_value": val, "qty_after_transaction": qty, "voucher_type": "Stock Reconciliation"},
				self.company,
			)
			self.assertEqual(flt(sle.valuation_rate), exp)
			self.assertEqual(exp, irr_avg_rate_from_balance(val, qty, ccy))


if __name__ == "__main__":
	unittest.main()
