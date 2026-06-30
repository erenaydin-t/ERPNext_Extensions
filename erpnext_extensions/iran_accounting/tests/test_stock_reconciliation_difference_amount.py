# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.rounding import get_company_currency, round_currency
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


class TestStockReconciliationDifferenceAmount(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def _sum_net_header(self, doc) -> float:
		from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
			sum_stock_reconciliation_amount_difference,
		)

		return flt(sum_stock_reconciliation_amount_difference(doc))

	def test_difference_amount_equals_sum_amount_difference(self):
		item = ensure_test_item(self.company, prefix="IA-SR-DIFF-UT")
		sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=1500.5)
		frappe.db.commit()
		sr.reload()
		self.assertEqual(flt(sr.difference_amount), self._sum_net_header(sr))
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr.name, self.company)
		self.assertEqual(chk["status"], "PASS", chk.get("totals"))

	def test_submit_cancel_and_second_submit_stable(self):
		item = ensure_test_item(self.company, prefix="IA-SR-CYCLE-UT")
		sr = _create_opening_sr(self.company, self.warehouse, item, 1, valuation_rate=2500)
		frappe.db.commit()
		self.assertEqual(flt(sr.difference_amount), self._sum_net_header(sr))
		sr.cancel()
		frappe.db.commit()
		self.assertEqual(sr.docstatus, 2)

		item2 = ensure_test_item(self.company, prefix="IA-SR-CYCLE-UT2")
		sr2 = _create_opening_sr(self.company, self.warehouse, item2, 2, valuation_rate=1800)
		frappe.db.commit()
		sr2.reload()
		self.assertEqual(flt(sr2.difference_amount), self._sum_opening_header_base(sr2))
		chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr2.name, self.company)
		self.assertEqual(chk["status"], "PASS", chk.get("totals"))
