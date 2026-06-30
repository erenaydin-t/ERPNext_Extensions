# Copyright (c) 2026, ERPNext Extensions contributors
"""Release gate: SR header, IRR integers, System Settings isolation."""

from __future__ import annotations

import unittest
from contextlib import contextmanager
from unittest import mock

import frappe
from frappe.utils import flt, nowtime, today

from erpnext_extensions.iran_accounting.domain.qty_rate_amount import (
	compute_row_amount,
	override_difference_amount,
	sum_stock_reconciliation_amount_difference,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import ensure_test_item, get_irr_company, get_warehouse
from erpnext_extensions.iran_accounting.qty_rate_consistency import check_qty_rate_amount_consistency
from erpnext_extensions.iran_accounting.rounding import (
	amount_is_fractional,
	get_company_currency,
	get_currency_precision,
	round_row_amount,
)
from erpnext_extensions.iran_accounting.stock_reconciliation_debug import _create_opening_sr


@contextmanager
def hostile_system_settings():
	"""Float precision 7, null currency precision, number format flag on — must not affect financial math."""
	get_currency_precision.cache_clear()

	def _single(doctype, field):
		if doctype != "System Settings":
			return None
		if field == "float_precision":
			return 7
		if field == "currency_precision":
			return None
		if field == "use_number_format_from_currency":
			return 1
		return None

	with mock.patch(
		"erpnext_extensions.iran_accounting.domain.currency.frappe.db.get_single_value",
		side_effect=_single,
	):
		yield
	get_currency_precision.cache_clear()


class TestStockReconciliationReleaseSuite(unittest.TestCase):
	def setUp(self):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		self.company = get_irr_company(None)
		self.warehouse = get_warehouse(self.company)
		self.currency = get_company_currency(self.company)

	def test_irr_precision_ignores_system_settings(self):
		with hostile_system_settings():
			self.assertEqual(get_currency_precision("IRR"), 0)
			self.assertEqual(get_currency_precision("USD"), 2)
			self.assertEqual(round_row_amount(3, 9877, "IRR"), 29631)

	def test_row_amount_irr_integer_only(self):
		with hostile_system_settings():
			self.assertEqual(round_row_amount(3, 9877, "IRR"), 29631)
			self.assertFalse(amount_is_fractional(round_row_amount(2, 333.33, "IRR"), "IRR"))

	def test_header_is_sum_of_net_amount_difference_scenario_a(self):
		with hostile_system_settings():
			item = ensure_test_item(self.company, prefix="IA-REL-A")
			sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
			frappe.db.commit()
			sr.reload()
			self.assertEqual(flt(sr.difference_amount), 29631)
			self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr, self.currency))

	def test_current_amount_does_not_affect_header(self):
		with hostile_system_settings():
			item = ensure_test_item(self.company, prefix="IA-REL-CUR")
			sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=1000)
			frappe.db.commit()
			sr.reload()
			row = sr.items[0]
			self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr, self.currency))
			if flt(row.current_amount) > 0:
				self.assertNotEqual(
					flt(sr.difference_amount),
					sum_stock_reconciliation_amount_difference(sr),
				)

	def test_fx_precision_usd_eur_only(self):
		get_currency_precision.cache_clear()
		with mock.patch(
			"erpnext_extensions.iran_accounting.domain.currency.frappe.db.get_value",
			side_effect=lambda dt, name, field=None, *a, **k: (
				0.01 if dt == "Currency" and field == "smallest_currency_fraction_value" else None
			),
		):
			get_currency_precision.cache_clear()
			self.assertEqual(get_currency_precision("USD"), 2)
			self.assertEqual(round_row_amount(1.333, 10.556, "USD"), 14.07)

	def test_system_settings_null_currency_precision_stable(self):
		with hostile_system_settings():
			before = round_row_amount(3, 9877, "IRR")
			after = round_row_amount(3, 9877, "IRR")
			self.assertEqual(before, after)
			self.assertEqual(before, 29631)

	def test_override_difference_amount_after_erpnext_style_header(self):
		doc = frappe.new_doc("Stock Reconciliation")
		doc.company = self.company
		doc.purpose = "Opening Stock"
		doc.difference_amount = 999  # simulate ERPNext net header
		doc.append("items", {"qty": 3, "valuation_rate": 9877, "current_qty": 0, "current_valuation_rate": 0})
		with hostile_system_settings():
			override_difference_amount(doc)
		self.assertEqual(flt(doc.difference_amount), 29631)
		self.assertEqual(flt(doc.items[0].amount), 29631)

	def test_large_opening_sr_header_sum_net_scenario_b(self):
		template = "MAT-RECO-2026-00174"
		if not frappe.db.exists("Stock Reconciliation", template):
			self.skipTest(template)
		src = frappe.get_doc("Stock Reconciliation", template)
		sr = frappe.new_doc("Stock Reconciliation")
		sr.purpose = "Opening Stock"
		sr.company = src.company
		sr.posting_date = today()
		sr.posting_time = nowtime()
		sr.set_posting_time = 1
		sr.expense_account = src.expense_account
		sr.cost_center = src.cost_center
		sr.difference_account = src.expense_account
		for r in (src.items or [])[:105]:
			sr.append(
				"items",
				{
					"item_code": r.item_code,
					"warehouse": r.warehouse,
					"qty": flt(r.qty) + 1,
					"valuation_rate": flt(r.valuation_rate) + 1,
					"allow_zero_valuation_rate": r.allow_zero_valuation_rate or 0,
				},
			)
		with hostile_system_settings():
			override_difference_amount(sr)
		self.assertGreaterEqual(len(sr.items), 100)
		self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr, self.currency))

	def test_submit_cancel_resubmit_identical_header(self):
		with hostile_system_settings():
			item = ensure_test_item(self.company, prefix="IA-REL-CYC")
			sr = _create_opening_sr(self.company, self.warehouse, item, 3, valuation_rate=9877)
			frappe.db.commit()
			expected = flt(sr.difference_amount)
			sr.cancel()
			frappe.db.commit()
			item2 = ensure_test_item(self.company, prefix="IA-REL-CYC2")
			sr2 = _create_opening_sr(self.company, self.warehouse, item2, 3, valuation_rate=9877)
			frappe.db.commit()
			self.assertEqual(flt(sr2.difference_amount), expected)

	def test_no_float_in_gl_sle_for_submitted_sr(self):
		with hostile_system_settings():
			item = ensure_test_item(self.company, prefix="IA-REL-GL")
			sr = _create_opening_sr(self.company, self.warehouse, item, 2, valuation_rate=1234.567)
			frappe.db.commit()
			chk = check_qty_rate_amount_consistency("Stock Reconciliation", sr.name, self.company)
			self.assertEqual(chk["totals"]["header_vs_rows_residual"], 0)
			self.assertEqual(chk["totals"]["difference_vs_sle_residual"], 0)
			for row in chk["item_rows"]:
				if row.get("field") == "amount" and row.get("currency") == "IRR":
					self.assertEqual(row.get("status"), "PASS", row)
			sles = frappe.get_all(
				"Stock Ledger Entry",
				filters={"voucher_type": "Stock Reconciliation", "voucher_no": sr.name, "is_cancelled": 0},
				fields=["stock_value_difference", "valuation_rate"],
			)
			for sle in sles:
				for field in ("stock_value_difference", "valuation_rate"):
					val = sle.get(field)
					if val not in (None, ""):
						self.assertFalse(amount_is_fractional(val, "IRR"), f"{field}={val}")

	def test_batch_row_header_sum(self):
		item = ensure_test_item(self.company, prefix="IA-REL-BAT")
		frappe.db.set_value("Item", item, "has_batch_no", 1, update_modified=False)
		try:
			batch = frappe.get_doc(
				{"doctype": "Batch", "item": item, "batch_id": f"IA-REL-{frappe.generate_hash(length=6)}"}
			)
			batch.insert(ignore_permissions=True)
		except frappe.ValidationError:
			self.skipTest("batch items not supported on this site")
		with hostile_system_settings():
			sr = _create_opening_sr(
				self.company, self.warehouse, item, 4, valuation_rate=1250.75, batch_no=batch.name
			)
			frappe.db.commit()
			sr.reload()
			self.assertEqual(flt(sr.difference_amount), sum_stock_reconciliation_amount_difference(sr, self.currency))
			self.assertEqual(
				flt(sr.items[0].amount),
				flt(compute_row_amount(sr.items[0], self.currency, rate_field="valuation_rate")),
			)
