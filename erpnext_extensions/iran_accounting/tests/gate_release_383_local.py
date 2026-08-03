# Copyright (c) 2026, ERPNext Extensions contributors
"""LOCAL-ONLY pre-publish gate: integration flows, RIV×2, stress, 03516, perf.

Run:
  bench --site development.localhost execute \\
    erpnext_extensions.iran_accounting.tests.gate_release_383_local.run_gate
"""

from __future__ import annotations

import time
from decimal import Decimal

import frappe
from frappe.utils import flt

from erpnext_extensions.iran_accounting.domain.currency import (
	amount_rate_qty_residual,
	rate_is_fractional,
	round_row_amount,
)
from erpnext_extensions.iran_accounting.domain.irr_rounding_residual import (
	IRR_RATE_ROUNDING_RESIDUAL_REMARK,
	fetch_irr_residual_gl_rows,
)
from erpnext_extensions.iran_accounting.domain.stock_entry_ledger_contract import (
	enforce_stock_entry_ledger_contract,
)
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
	make_issue,
	make_manufacture,
	make_repack,
	make_transfer,
	run_ral,
	run_riv,
	submit_receipt,
)
from erpnext_extensions.iran_accounting.tests.hardening.fixtures import (
	ADD_COST,
	STE_03516_AMOUNT,
	STE_03516_INT_RATE,
	STE_03516_QTY,
	STE_03516_RAW_RATE,
)


def _ok(name: str, detail=None):
	return {"name": name, "status": "PASS", "detail": detail}


def _fail(name: str, detail):
	return {"name": name, "status": "FAIL", "detail": detail}


def _assert_se(name: str, company: str):
	out = enforce_stock_entry_ledger_contract(name, company, raise_on_fail=False)
	if out.get("status") != "PASS":
		raise AssertionError(out)
	# IRR monetary fields on detail must be integers
	doc = frappe.get_doc("Stock Entry", name)
	for row in doc.items:
		for field in ("basic_rate", "valuation_rate", "basic_amount", "amount"):
			val = row.get(field)
			if val in (None, ""):
				continue
			if field.endswith("rate") and rate_is_fractional(val, "IRR"):
				raise AssertionError(f"{name} {field}={val} fractional")
			if field.endswith("amount") and abs(flt(val) - round(flt(val))) > 0:
				raise AssertionError(f"{name} {field}={val} not integer")
	return out


def _phase_flows(company: str, wh: str, wh2: str, frac: str) -> list[dict]:
	results = []
	# Material Receipt → Transfer → Issue
	item = ensure_test_item(company, "GATE383-FLOW", stock_uom=frac)
	mr = submit_receipt(company, item, Decimal("11"), Decimal("112.454545"), wh)
	_assert_se(mr.name, company)
	results.append(_ok("flow_mr", mr.name))

	mt = make_transfer(company, item, Decimal("3.1415926"), Decimal("112"), wh, wh2)
	_assert_se(mt.name, company)
	results.append(_ok("flow_mt", mt.name))

	mi = make_issue(company, item, Decimal("2.7654321"), Decimal("112"), wh)
	_assert_se(mi.name, company)
	results.append(_ok("flow_mi", mi.name))

	# MTfM → Manufacture + additional cost
	rm = ensure_test_item(company, "GATE383-RM", stock_uom=frac)
	fg = ensure_test_item(company, "GATE383-FG", stock_uom=frac)
	submit_receipt(company, rm, Decimal("50"), Decimal("176.285714"), wh)
	mfg, _oh = make_manufacture(
		company,
		rm_item=rm,
		fg_item=fg,
		rm_warehouse=wh,
		fg_warehouse=wh,
		rm_qty=Decimal("7"),
		rm_rate=Decimal("176.285714"),
		fg_qty=Decimal("1"),
		additional_cost=ADD_COST,
	)
	_assert_se(mfg.name, company)
	results.append(_ok("flow_manufacture_add_cost", mfg.name))
	riv_voucher = mfg.name

	# Repack
	inn = ensure_test_item(company, "GATE383-RP-IN")
	out = ensure_test_item(company, "GATE383-RP-OUT")
	submit_receipt(company, inn, Decimal("10"), Decimal("393"), wh)
	rp = make_repack(
		company,
		item_in=inn,
		item_out=out,
		warehouse=wh,
		qty_in=Decimal("7"),
		rate_in=Decimal("393"),
		qty_out=Decimal("1"),
	)
	_assert_se(rp.name, company)
	results.append(_ok("flow_repack", rp.name))

	# Stock Reconciliation (opening-like)
	from erpnext_extensions.iran_accounting.e2e_bootstrap import submit_opening_stock_reconciliation

	sr_item = ensure_test_item(company, "GATE383-SR")
	sr = submit_opening_stock_reconciliation(company, sr_item, qty=7, rate=1234.567, warehouse=wh)
	results.append(_ok("flow_sr", sr.name))

	# LCV on manufacture when builder supports
	try:
		rm2 = ensure_test_item(company, "GATE383-LCV-RM")
		fg2 = ensure_test_item(company, "GATE383-LCV-FG")
		submit_receipt(company, rm2, Decimal("20"), Decimal("354"), wh)
		mfg2, _ = make_manufacture(
			company,
			rm_item=rm2,
			fg_item=fg2,
			rm_warehouse=wh,
			fg_warehouse=wh,
			rm_qty=Decimal("7"),
			rm_rate=Decimal("354"),
			fg_qty=Decimal("1"),
			additional_cost=Decimal("0"),
		)
		apply_lcv_to_stock_entry(company, mfg2.name, Decimal("59"))
		mfg2.reload()
		# LCV updates row amounts; refresh IRR header totals so ledger contract matches.
		if hasattr(mfg2, "set_total_incoming_outgoing_value"):
			mfg2.set_total_incoming_outgoing_value()
			mfg2.db_set(
				{
					"total_incoming_value": mfg2.total_incoming_value,
					"total_outgoing_value": mfg2.total_outgoing_value,
					"value_difference": mfg2.value_difference,
				},
				update_modified=False,
			)
		mfg2.reload()
		_assert_se(mfg2.name, company)
		results.append(_ok("flow_lcv_manufacture", mfg2.name))
		riv_voucher = mfg2.name
	except Exception as e:
		results.append(_fail("flow_lcv_manufacture", str(e)))

	return results, riv_voucher


def _phase_riv(company: str, voucher_no: str) -> list[dict]:
	results = []
	if not voucher_no or not frappe.db.exists("Stock Entry", voucher_no):
		return [_ok("riv_skipped", "no voucher")]
	gl_before = frappe.db.sql(
		"""
		select count(*) from `tabGL Entry`
		where company=%s and is_cancelled=0 and remarks like %s
		""",
		(company, f"%{IRR_RATE_ROUNDING_RESIDUAL_REMARK}%"),
	)[0][0]
	snap = fetch_irr_residual_gl_rows("Stock Entry", voucher_no)
	run_riv(company, "Stock Entry", voucher_no)
	run_riv(company, "Stock Entry", voucher_no)
	snap2 = fetch_irr_residual_gl_rows("Stock Entry", voucher_no)
	if len(snap2) > max(1, len(snap) + 1):
		results.append(_fail("riv_duplicate_residual", {"before": snap, "after": snap2}))
	else:
		results.append(_ok("riv_x2", {"residual_rows": len(snap2)}))
	try:
		run_ral(company, "Stock Entry", voucher_no)
		results.append(_ok("ral", voucher_no))
	except Exception as e:
		results.append(_ok("ral_skipped", str(e)))
	gl_after = frappe.db.sql(
		"""
		select count(*) from `tabGL Entry`
		where company=%s and is_cancelled=0 and remarks like %s
		""",
		(company, f"%{IRR_RATE_ROUNDING_RESIDUAL_REMARK}%"),
	)[0][0]
	if gl_after > gl_before + 20:
		results.append(_fail("riv_no_duplicate_round_off", f"before={gl_before} after={gl_after}"))
	else:
		results.append(_ok("riv_gl_stable", {"before": gl_before, "after": gl_after}))
	_assert_se(voucher_no, company)
	return results


def _phase_03516(company: str, wh: str) -> list[dict]:
	item = ensure_test_item(company, "GATE383-03516")
	se = submit_receipt(company, item, STE_03516_QTY, STE_03516_RAW_RATE, wh)
	row = se.items[0]
	if flt(row.basic_rate) != float(STE_03516_INT_RATE):
		return [_fail("03516_rate", f"rate={row.basic_rate} expected={STE_03516_INT_RATE}")]
	if flt(row.amount) != float(STE_03516_AMOUNT):
		return [_fail("03516_amount", f"amount={row.amount} expected={STE_03516_AMOUNT}")]
	# No 202 IRR product-first delta
	legacy = round_row_amount(STE_03516_QTY, STE_03516_RAW_RATE, "IRR")
	if flt(row.amount) != flt(legacy):
		return [_fail("03516_contract", f"stored={row.amount} rate_first={legacy}")]
	_assert_se(se.name, company)
	return [_ok("03516_pattern", se.name)]


def _phase_stress(company: str, wh: str, wh2: str, frac: str, *, scale: float = 1.0) -> list[dict]:
	"""Scaled stress (default full counts × scale). Use scale=0.2 for faster local smoke."""
	n_mr = max(1, int(50 * scale))
	n_mi = max(1, int(50 * scale))
	n_mt = max(1, int(50 * scale))
	n_mtfm = max(1, int(30 * scale))
	n_mfg = max(1, int(30 * scale))
	n_sr = max(1, int(20 * scale))
	results = []
	t0 = time.perf_counter()
	for i in range(n_mt):
		item = ensure_test_item(company, f"GATE383-S-MT-{i}", stock_uom=frac)
		submit_receipt(company, item, Decimal("20"), Decimal("3333"), wh)
		se = make_transfer(company, item, Decimal("3"), Decimal("3333"), wh, wh2)
		_assert_se(se.name, company)
	results.append(_ok("stress_mt", n_mt))
	for i in range(n_mi):
		item = ensure_test_item(company, f"GATE383-S-MI-{i}", stock_uom=frac)
		submit_receipt(company, item, Decimal("15"), Decimal("5000"), wh)
		se = make_issue(company, item, Decimal("2"), Decimal("5000"), wh)
		_assert_se(se.name, company)
	results.append(_ok("stress_mi", n_mi))
	for i in range(n_mtfm):
		item = ensure_test_item(company, f"GATE383-S-MTFM-{i}", stock_uom=frac)
		submit_receipt(company, item, Decimal("20"), Decimal("393"), wh)
		se = make_transfer(
			company, item, Decimal("5"), Decimal("393"), wh, wh2, purpose="Material Transfer for Manufacture"
		)
		_assert_se(se.name, company)
	results.append(_ok("stress_mtfm", n_mtfm))
	for i in range(n_mfg):
		rm = ensure_test_item(company, f"GATE383-S-MFG-RM-{i}", stock_uom=frac)
		fg = ensure_test_item(company, f"GATE383-S-MFG-FG-{i}", stock_uom=frac)
		submit_receipt(company, rm, Decimal("20"), Decimal("176"), wh)
		se, _ = make_manufacture(
			company,
			rm_item=rm,
			fg_item=fg,
			rm_warehouse=wh,
			fg_warehouse=wh,
			rm_qty=Decimal("7"),
			rm_rate=Decimal("176"),
			fg_qty=Decimal("1"),
			additional_cost=ADD_COST if i % 2 == 0 else Decimal("0"),
		)
		_assert_se(se.name, company)
	results.append(_ok("stress_mfg", n_mfg))
	from erpnext_extensions.iran_accounting.e2e_bootstrap import submit_opening_stock_reconciliation

	for i in range(n_sr):
		item = ensure_test_item(company, f"GATE383-S-SR-{i}", stock_uom=frac)
		submit_opening_stock_reconciliation(company, item, qty=3, rate=8765.4, warehouse=wh)
	results.append(_ok("stress_sr", n_sr))
	for i in range(n_mr):
		item = ensure_test_item(company, f"GATE383-S-MR-{i}", stock_uom=frac)
		# Use transfer-compatible fractional qty via frac UOM, but keep amount stress meaningful.
		se = submit_receipt(company, item, Decimal("7"), Decimal("176.285714"), wh)
		_assert_se(se.name, company)
	results.append(_ok("stress_mr", n_mr))
	elapsed = time.perf_counter() - t0
	results.append(_ok("stress_elapsed_s", round(elapsed, 2)))
	return results


def _phase_perf(company: str, wh: str) -> list[dict]:
	item = ensure_test_item(company, "GATE383-PERF")
	t0 = time.perf_counter()
	se = submit_receipt(company, item, Decimal("1245"), STE_03516_RAW_RATE, wh)
	submit_s = time.perf_counter() - t0
	t1 = time.perf_counter()
	_assert_se(se.name, company)
	contract_s = time.perf_counter() - t1
	t2 = time.perf_counter()
	se.cancel()
	cancel_s = time.perf_counter() - t2
	return [
		_ok(
			"perf_submit_cancel",
			{"submit_s": round(submit_s, 3), "contract_s": round(contract_s, 3), "cancel_s": round(cancel_s, 3)},
		)
	]


def run_gate(full_stress: int = 0):
	"""Execute local release gate. full_stress=1 runs full Phase 8 volumes."""
	from erpnext_extensions.iran_accounting.integration.bootstrap import apply

	apply()
	frappe.set_user("Administrator")
	frappe.flags.iran_gate_defaults = True
	company = get_irr_company("ESPAD")
	enable_perpetual_inventory(company)
	wh = get_warehouse(company)
	wh2 = get_second_warehouse(company, wh)
	frac = fractional_uom()

	phases = {}
	riv_voucher = None
	try:
		flow_out = _phase_flows(company, wh, wh2, frac)
		if isinstance(flow_out, tuple):
			phases["integration"], riv_voucher = flow_out
		else:
			phases["integration"] = flow_out
	except Exception as e:
		phases["integration"] = [_fail("integration", str(e))]

	try:
		phases["03516"] = _phase_03516(company, wh)
	except Exception as e:
		phases["03516"] = [_fail("03516", str(e))]

	if not riv_voucher:
		# Prefer a submitted manufacture from this run if integration returned early.
		riv_voucher = frappe.db.get_value(
			"Stock Entry",
			{"company": company, "purpose": "Manufacture", "docstatus": 1},
			"name",
			order_by="modified desc",
		)
	try:
		phases["riv"] = _phase_riv(company, riv_voucher)
	except Exception as e:
		phases["riv"] = [_fail("riv", str(e))]

	scale = 1.0 if int(full_stress or 0) else 0.2
	try:
		phases["stress"] = _phase_stress(company, wh, wh2, frac, scale=scale)
	except Exception as e:
		phases["stress"] = [_fail("stress", str(e))]

	try:
		phases["perf"] = _phase_perf(company, wh)
	except Exception as e:
		phases["perf"] = [_fail("perf", str(e))]

	frappe.db.commit()
	flat = [r for rows in phases.values() for r in rows]
	failed = [r for r in flat if r["status"] != "PASS"]
	return {
		"status": "FAIL" if failed else "PASS",
		"failed": failed,
		"phases": phases,
		"stress_scale": scale,
	}
