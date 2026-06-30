# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.model.document import unlock_document

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestStockReconciliationCancel(unittest.TestCase):
	def setUp(self):
		import erpnext_extensions.iran_accounting  # noqa: F401
		from erpnext_extensions.iran_accounting.monkey_patches import apply_monkey_patches

		apply_monkey_patches()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)

	def test_opening_cancel_reversal_sle_keeps_negative_value_difference(self):
		item = ensure_test_item(self.company, prefix="IA-SR-CAN-UT")
		sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=1234)
		frappe.db.commit()
		unlock_document("Stock Reconciliation", sr.name)
		sr = frappe.get_doc("Stock Reconciliation", sr.name)
		sr.flags.ignore_permissions = True
		sr._cancel()
		frappe.db.commit()
		self.assertEqual(sr.docstatus, 2)
		sle = frappe.db.sql(
			"""
			select stock_value_difference, actual_qty, is_cancelled
			from `tabStock Ledger Entry`
			where voucher_type='Stock Reconciliation' and voucher_no=%s
			order by creation desc limit 1
			""",
			sr.name,
			as_dict=True,
		)[0]
		self.assertEqual(sle.is_cancelled, 1)
		self.assertLess(float(sle.stock_value_difference), 0)
		self.assertLess(float(sle.actual_qty), 0)
