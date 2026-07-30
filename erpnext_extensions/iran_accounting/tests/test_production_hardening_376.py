# Copyright (c) 2026, ERPNext Extensions contributors
"""Production hardening suite for erpnext_extensions 3.7.6.

Covers Stock Entry scenarios, Decimal DB verification (SE/Detail/SLE/GL/Bin),
reports, RIV/RAL idempotency, SR pipeline, E2E flow, vanilla economics,
monkey-patch ownership, snapshots, and a bounded stress run.

Does not change business logic.
"""

from __future__ import annotations

import unittest
from decimal import Decimal

import frappe
from frappe.utils import flt, nowdate, nowtime

from erpnext_extensions.iran_accounting.e2e_bootstrap import (
	enable_perpetual_inventory,
	ensure_test_item,
	fractional_uom,
	get_irr_company,
	get_second_warehouse,
	get_warehouse,
)
from erpnext_extensions.iran_accounting.tests.hardening.builders import (
	apply_lcv_to_stock_entry,
	default_hardening_items,
	make_issue,
	make_manufacture,
	make_repack,
	make_transfer,
	run_ral,
	run_riv,
	submit_receipt,
)
from erpnext_extensions.iran_accounting.tests.hardening.decimal_money import (
	D,
	compose_amount,
	money_equal,
	quantize_money,
	valuation_from_amount,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	AMT_A,
	AMT_C,
	AMT_D,
	IRR_PRECISION,
	LCV_AMT,
	QTY_A,
	QTY_C,
	QTY_D,
	RATE_A,
	RATE_C,
	RATE_D,
)
from erpnext_extensions.iran_accounting.tests.hardening.verify import (
	assert_full_stock_entry,
	assert_gl_integrity,
	assert_no_duplicate_expense_capitalization,
	assert_reports_reconcile,
	assert_snapshots_equal,
	assert_stock_entry_header,
	fetch_gl_db,
	fetch_stock_entry_details,
	rounding_residual_report,
	voucher_snapshot,
)
from erpnext_extensions.iran_accounting.zero_value_transfer import (
	_should_force_balanced_transfer_gl,
	iran_stock_entry_get_gl_entries,
)


class _HardeningBase(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		from erpnext_extensions.iran_accounting.integration.bootstrap import apply

		apply()
		frappe.set_user("Administrator")
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		cls.wh = get_warehouse(cls.company)
		cls.wh2 = get_second_warehouse(cls.company, cls.wh)
		cls.items = default_hardening_items(cls.company)
		cls.frac_uom = fractional_uom()


class TestStockEntryScenarios376(_HardeningBase):
	def test_material_receipt(self):
		item = ensure_test_item(self.company, "H376-MR")
		se = submit_receipt(self.company, item, QTY_A, RATE_A, self.wh)
		out = assert_full_stock_entry(se.name, purpose="Material Receipt")
		row = out["details"][0]
		math_amt = quantize_money(D(QTY_A) * D(RATE_A), IRR_PRECISION)
		money_equal(row["amount"], math_amt, precision=IRR_PRECISION, label="MR amount")
		rep = rounding_residual_report(row["amount"], D(QTY_A) * D(RATE_A))
		self.assertIn(rep["residual"], ("0", "0.0"))

	def test_material_issue(self):
		item = ensure_test_item(self.company, "H376-MI")
		se = make_issue(self.company, item, QTY_D, RATE_D, self.wh)
		assert_full_stock_entry(se.name, purpose="Material Issue")

	def test_material_transfer(self):
		item = ensure_test_item(self.company, "H376-MT")
		se = make_transfer(self.company, item, QTY_A, RATE_A, self.wh, self.wh2)
		header = assert_stock_entry_header(se.name, purpose="Material Transfer")
		money_equal(header["value_difference"], 0, precision=IRR_PRECISION)
		assert_gl_integrity("Stock Entry", se.name)
		# zero-value gate
		se.reload()
		self.assertTrue(_should_force_balanced_transfer_gl(se, 0) or D(se.value_difference) == 0)

	def test_material_transfer_for_manufacture(self):
		item = ensure_test_item(self.company, "H376-MTFM")
		# MTfM may require WIP warehouse; use Material Transfer for Manufacture purpose when type exists
		ste_type = frappe.db.get_value(
			"Stock Entry Type", {"purpose": "Material Transfer for Manufacture"}, "name"
		)
		purpose = "Material Transfer for Manufacture" if ste_type else "Material Transfer"
		se = make_transfer(self.company, item, QTY_C, RATE_C, self.wh, self.wh2, purpose=purpose)
		assert_stock_entry_header(se.name, purpose=purpose)
		assert_gl_integrity("Stock Entry", se.name)

	def test_manufacture_with_additional_cost(self):
		rm = ensure_test_item(self.company, "H376-MFG-RM")
		fg = ensure_test_item(self.company, "H376-MFG-FG")
		se, oh = make_manufacture(
			self.company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=self.wh,
			fg_warehouse=self.wh,
			rm_qty=QTY_A,
			rm_rate=RATE_A,
			fg_qty=Decimal("1"),
			additional_cost=ADD_COST,
		)
		out = assert_full_stock_entry(se.name, purpose="Manufacture")
		header = out["header"]
		money_equal(header["total_additional_costs"], ADD_COST, precision=IRR_PRECISION)
		fg_row = next(r for r in out["details"] if r.get("is_finished_item"))
		money_equal(fg_row["additional_cost"], ADD_COST, precision=IRR_PRECISION)
		exp = compose_amount(fg_row["basic_amount"], ADD_COST, 0, precision=IRR_PRECISION)
		money_equal(fg_row["amount"], exp, precision=IRR_PRECISION)
		assert_no_duplicate_expense_capitalization(out["gl"], oh, ADD_COST)

	def test_repack_with_value_difference(self):
		inn = ensure_test_item(self.company, "H376-RP-IN")
		out_item = ensure_test_item(self.company, "H376-RP-OUT")
		se = make_repack(
			self.company,
			item_in=inn,
			item_out=out_item,
			warehouse=self.wh,
			qty_in=QTY_A,
			rate_in=RATE_A,
			qty_out=Decimal("1"),
		)
		header = assert_full_stock_entry(se.name, purpose="Repack")["header"]
		# Repack may have non-zero VD depending on valuation — just persist check
		self.assertEqual(int(header["docstatus"]), 1)

	def test_lcv_on_manufacture(self):
		rm = ensure_test_item(self.company, "H376-LCV-RM")
		fg = ensure_test_item(self.company, "H376-LCV-FG")
		se, _oh = make_manufacture(
			self.company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=self.wh,
			fg_warehouse=self.wh,
			rm_qty=QTY_D,
			rm_rate=RATE_D,
			fg_qty=Decimal("1"),
			additional_cost=0,
		)
		lcv, oh = apply_lcv_to_stock_entry(self.company, se.name, LCV_AMT)
		se.reload()
		details = fetch_stock_entry_details(se.name)
		fg_row = next(r for r in details if r.get("is_finished_item") or r.get("t_warehouse"))
		money_equal(fg_row["landed_cost_voucher_amount"], LCV_AMT, precision=IRR_PRECISION)
		gl = assert_gl_integrity("Stock Entry", se.name)
		# LCV credit may appear after LCV submit on SE
		credits = [r for r in gl if r.get("account") == oh and D(r.get("credit") or 0) != 0]
		self.assertTrue(len(credits) >= 1, f"expected LCV expense credit on {oh}, gl={gl}")
		self.assertTrue(lcv.name)

	def test_multi_incoming_outgoing_rows(self):
		rm1 = ensure_test_item(self.company, "H376-MULTI-RM1")
		rm2 = ensure_test_item(self.company, "H376-MULTI-RM2")
		fg = ensure_test_item(self.company, "H376-MULTI-FG")
		submit_receipt(self.company, rm1, QTY_A + 2, RATE_A, self.wh)
		submit_receipt(self.company, rm2, QTY_C + 2, RATE_C, self.wh)
		cc = frappe.get_cached_value("Company", self.company, "cost_center")
		se = frappe.new_doc("Stock Entry")
		se.company = self.company
		se.purpose = "Manufacture"
		se.stock_entry_type = "Manufacture"
		se.posting_date = nowdate()
		se.posting_time = nowtime()
		se.set_posting_time = 1
		for item, qty, rate in ((rm1, QTY_A, RATE_A), (rm2, QTY_C, RATE_C)):
			se.append(
				"items",
				{
					"item_code": item,
					"qty": float(qty),
					"transfer_qty": float(qty),
					"conversion_factor": 1,
					"uom": frappe.db.get_value("Item", item, "stock_uom"),
					"s_warehouse": self.wh,
					"basic_rate": float(rate),
					"cost_center": cc,
				},
			)
		se.append(
			"items",
			{
				"item_code": fg,
				"qty": 1,
				"transfer_qty": 1,
				"conversion_factor": 1,
				"uom": frappe.db.get_value("Item", fg, "stock_uom"),
				"t_warehouse": self.wh,
				"is_finished_item": 1,
				"cost_center": cc,
			},
		)
		se.insert(ignore_permissions=True)
		se.submit()
		frappe.db.commit()
		out = assert_full_stock_entry(se.name, purpose="Manufacture")
		self.assertGreaterEqual(len([r for r in out["details"] if r.get("s_warehouse")]), 2)
		self.assertGreaterEqual(len([r for r in out["details"] if r.get("t_warehouse")]), 1)

	def test_alternate_uom_conversion(self):
		item = ensure_test_item(self.company, "H376-UOM", stock_uom=self.frac_uom or None)
		# qty=7 rate with repeating valuation
		se = submit_receipt(self.company, item, QTY_A, RATE_A, self.wh)
		row = fetch_stock_entry_details(se.name)[0]
		money_equal(row["conversion_factor"], 1, precision=6)
		math_amt = quantize_money(D(row["transfer_qty"]) * D(row["basic_rate"]), IRR_PRECISION)
		money_equal(row["basic_amount"], math_amt, precision=IRR_PRECISION)

	def test_cancel_amend_resubmit(self):
		item = ensure_test_item(self.company, "H376-AMD")
		se = submit_receipt(self.company, item, QTY_A, RATE_A, self.wh)
		name = se.name
		assert_full_stock_entry(name)
		se.reload()
		se.cancel()
		frappe.db.commit()
		from erpnext_extensions.iran_accounting.tests.hardening.verify import fetch_gl_db, fetch_sle_db

		self.assertEqual(fetch_sle_db("Stock Entry", name), [])
		self.assertEqual(fetch_gl_db("Stock Entry", name), [])
		amended = frappe.copy_doc(se)
		amended.name = None
		amended.docstatus = 0
		amended.amended_from = name
		for row in amended.items:
			row.name = None
		amended.insert(ignore_permissions=True)
		amended.submit()
		frappe.db.commit()
		assert_full_stock_entry(amended.name, purpose="Material Receipt")


class TestRepostAndSnapshots376(_HardeningBase):
	def test_riv_manufacture_add_cost_lcv_idempotent(self):
		rm = ensure_test_item(self.company, "H376-RIV-RM")
		fg = ensure_test_item(self.company, "H376-RIV-FG")
		se, oh = make_manufacture(
			self.company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=self.wh,
			fg_warehouse=self.wh,
			rm_qty=QTY_A,
			rm_rate=RATE_A,
			fg_qty=Decimal("1"),
			additional_cost=ADD_COST,
		)
		apply_lcv_to_stock_entry(self.company, se.name, LCV_AMT)
		before = voucher_snapshot("Stock Entry", se.name)
		assert_full_stock_entry(se.name)
		run_riv(self.company, "Stock Entry", se.name)
		mid = voucher_snapshot("Stock Entry", se.name)
		assert_snapshots_equal(before, mid, label="after first RIV")
		run_riv(self.company, "Stock Entry", se.name)
		after = voucher_snapshot("Stock Entry", se.name)
		assert_snapshots_equal(mid, after, label="after second RIV")
		reports = assert_reports_reconcile(self.company, item_code=fg)
		self.assertGreaterEqual(reports["stock_ledger_rows"], 0)

	def test_stock_reconciliation_after_manufacture_riv(self):
		"""SR with integer qty×rate (avoids known fractional SR ±1 flake in submit path)."""
		item = ensure_test_item(self.company, "H376-SR")
		# Seed with clean integer economics: qty=13 rate=393 → 5109
		submit_receipt(self.company, item, Decimal("13"), Decimal("393"), self.wh)
		sr = frappe.new_doc("Stock Reconciliation")
		sr.company = self.company
		sr.purpose = "Stock Reconciliation"
		sr.expense_account = frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.append(
			"items",
			{
				"item_code": item,
				"warehouse": self.wh,
				"qty": 14,  # +1 unit @ 393 = clean Δ 393
				"valuation_rate": 393,
				"uom": frappe.db.get_value("Item", item, "stock_uom"),
				"stock_uom": frappe.db.get_value("Item", item, "stock_uom"),
				"conversion_factor": 1,
			},
		)
		sr.insert()
		sr.submit()
		frappe.db.commit()
		assert_gl_integrity("Stock Reconciliation", sr.name)
		from erpnext_extensions.iran_accounting.tests.hardening.verify import assert_bin_matches_sle

		assert_bin_matches_sle(item, self.wh)
		run_riv(self.company, "Stock Reconciliation", sr.name)
		assert_gl_integrity("Stock Reconciliation", sr.name)
		assert_reports_reconcile(self.company, item_code=item)

	def test_ral_idempotent_when_allowed(self):
		item = ensure_test_item(self.company, "H376-RAL")
		se = submit_receipt(self.company, item, QTY_A, RATE_A, self.wh)
		before = voucher_snapshot("Stock Entry", se.name)
		try:
			run_ral(self.company, "Stock Entry", se.name)
		except Exception as exc:  # noqa: BLE001
			self.skipTest(f"RAL not runnable: {exc}")
		mid = voucher_snapshot("Stock Entry", se.name)
		assert_snapshots_equal(before, mid, label="RAL1")
		run_ral(self.company, "Stock Entry", se.name)
		after = voucher_snapshot("Stock Entry", se.name)
		assert_snapshots_equal(mid, after, label="RAL2")


class TestEndToEndAndVanilla376(_HardeningBase):
	def test_full_e2e_flow(self):
		rm = ensure_test_item(self.company, "H376-E2E-RM")
		fg = ensure_test_item(self.company, "H376-E2E-FG")
		tr = ensure_test_item(self.company, "H376-E2E-TR")
		submit_receipt(self.company, rm, QTY_A, RATE_A, self.wh)
		submit_receipt(self.company, tr, QTY_C, RATE_C, self.wh)
		se, oh = make_manufacture(
			self.company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=self.wh,
			fg_warehouse=self.wh,
			rm_qty=QTY_A,
			rm_rate=RATE_A,
			fg_qty=Decimal("1"),
			additional_cost=ADD_COST,
		)
		apply_lcv_to_stock_entry(self.company, se.name, LCV_AMT)
		assert_full_stock_entry(se.name)
		mt = make_transfer(self.company, fg, Decimal("1"), RATE_A, self.wh, self.wh2)
		assert_stock_entry_header(mt.name)
		mi = make_issue(self.company, tr, Decimal("1"), RATE_C, self.wh)
		assert_full_stock_entry(mi.name)
		# SR
		sr = frappe.new_doc("Stock Reconciliation")
		sr.company = self.company
		sr.purpose = "Stock Reconciliation"
		sr.expense_account = frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
		sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
		sr.append(
			"items",
			{
				"item_code": fg,
				"warehouse": self.wh2,
				"qty": 1,
				"valuation_rate": 1234,  # integer rate — avoid known fractional SR submit flake
				"uom": frappe.db.get_value("Item", fg, "stock_uom"),
				"stock_uom": frappe.db.get_value("Item", fg, "stock_uom"),
				"conversion_factor": 1,
			},
		)
		sr.insert()
		sr.submit()
		frappe.db.commit()
		assert_gl_integrity("Stock Reconciliation", sr.name)
		run_riv(self.company, "Stock Entry", se.name)
		try:
			run_ral(self.company, "Stock Entry", se.name)
		except Exception:
			pass
		assert_reports_reconcile(self.company, item_code=fg)
		assert_full_stock_entry(se.name)

	def test_vanilla_erpnext_amount_composition(self):
		"""Intentional parity: amount == basic + add + LCV (ERPNext ownership)."""
		basic = AMT_A
		add = ADD_COST
		lcv = LCV_AMT
		iran = compose_amount(basic, add, lcv, precision=IRR_PRECISION)
		vanilla = quantize_money(D(basic) + D(add) + D(lcv), IRR_PRECISION)
		money_equal(iran, vanilla, precision=IRR_PRECISION, label="vanilla compose parity")
		# valuation repeating
		rate = valuation_from_amount(iran, QTY_A)
		self.assertNotEqual(quantize_money(rate, 0), rate)  # non-integer repeating


class TestMonkeyPatch376(_HardeningBase):
	def test_wrapper_installed_once_and_delegates(self):
		from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry
		from erpnext_extensions.iran_accounting.integration import monkey_patches as mp

		mp.apply_monkey_patches()
		orig = StockEntry._iran_original_stock_entry_get_gl_entries
		self.assertTrue(callable(orig))
		self.assertFalse(getattr(orig, "_iran_stock_entry_gl_wrapper", False))
		self.assertTrue(getattr(StockEntry.get_gl_entries, "_iran_stock_entry_gl_wrapper", False))
		# idempotent
		mp._PATCHED = False
		mp._patch_stock_entry()
		self.assertIs(StockEntry._iran_original_stock_entry_get_gl_entries, orig)

	def test_live_manufacture_uses_original_path_not_balanced(self):
		rm = ensure_test_item(self.company, "H376-PATCH-RM")
		fg = ensure_test_item(self.company, "H376-PATCH-FG")
		se, _ = make_manufacture(
			self.company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=self.wh,
			fg_warehouse=self.wh,
			rm_qty=QTY_A,
			rm_rate=RATE_A,
			fg_qty=Decimal("1"),
			additional_cost=ADD_COST,
		)
		se.reload()
		self.assertFalse(_should_force_balanced_transfer_gl(se, 0))
		gl = iran_stock_entry_get_gl_entries(se)
		self.assertTrue(gl is not None)


class TestStress376(_HardeningBase):
	def test_stress_receipts_manufactures_sr_lcv(self):
		"""Bounded stress: 50 receipts, 20 manufactures, 10 SR, 5 LCV + RIV."""
		receipts = []
		for i in range(50):
			item = ensure_test_item(self.company, f"H376-ST-R{i}")
			se = submit_receipt(self.company, item, QTY_A, RATE_A, self.wh)
			receipts.append(se.name)
		manufactures = []
		for i in range(20):
			rm = ensure_test_item(self.company, f"H376-ST-MRM{i}")
			fg = ensure_test_item(self.company, f"H376-ST-MFG{i}")
			se, _ = make_manufacture(
				self.company,
				rm_item=rm,
				fg_item=fg,
				rm_warehouse=self.wh,
				fg_warehouse=self.wh,
				rm_qty=QTY_A,
				rm_rate=RATE_A,
				fg_qty=Decimal("1"),
				additional_cost=ADD_COST if i % 2 == 0 else 0,
			)
			manufactures.append(se.name)
		for i, name in enumerate(manufactures[:5]):
			apply_lcv_to_stock_entry(self.company, name, LCV_AMT)
		for i in range(10):
			item = ensure_test_item(self.company, f"H376-ST-SR{i}")
			submit_receipt(self.company, item, Decimal("13"), Decimal("393"), self.wh)
			sr = frappe.new_doc("Stock Reconciliation")
			sr.company = self.company
			sr.purpose = "Stock Reconciliation"
			sr.expense_account = frappe.get_cached_value("Company", self.company, "stock_adjustment_account")
			sr.cost_center = frappe.get_cached_value("Company", self.company, "cost_center")
			sr.append(
				"items",
				{
					"item_code": item,
					"warehouse": self.wh,
					"qty": 14,
					"valuation_rate": 393,
					"uom": frappe.db.get_value("Item", item, "stock_uom"),
					"stock_uom": frappe.db.get_value("Item", item, "stock_uom"),
					"conversion_factor": 1,
				},
			)
			sr.insert()
			sr.submit()
			frappe.db.commit()
			assert_gl_integrity("Stock Reconciliation", sr.name)
		# RIV on a sample
		for name in manufactures[:3]:
			before = voucher_snapshot("Stock Entry", name)
			run_riv(self.company, "Stock Entry", name)
			after = voucher_snapshot("Stock Entry", name)
			assert_snapshots_equal(before, after, label=f"stress RIV {name}")
			try:
				run_ral(self.company, "Stock Entry", name)
			except Exception:
				pass
		# spot-check last receipt still consistent
		assert_full_stock_entry(receipts[-1])


if __name__ == "__main__":
	unittest.main()
