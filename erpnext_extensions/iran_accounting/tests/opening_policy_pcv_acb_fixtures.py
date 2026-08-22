# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Native ERPNext PCV + ACB fixtures for GF-13 … GF-17 production integration."""

from __future__ import annotations

from datetime import date
from typing import Any

import frappe
from erpnext.accounts.utils import get_fiscal_year
from frappe.utils import flt, getdate

from erpnext_extensions.iran_accounting.account_explorer.opening_entry_policy import (
	AccountAxisEngine,
	opening_flagged_baked_in_acb,
	select_account_axis_engine,
)
from erpnext_extensions.iran_accounting.account_explorer.query_spec import (
	AccountExplorerQuerySpec_from_client,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import (
	FROM_DATE,
	GAP_START,
	TO_DATE,
)
from erpnext_extensions.iran_accounting.tests.opening_policy_production_fixtures import (
	_balancing_accounts,
)

MARKER = "AE-OEP-PCV"
PCV_END = date(2025, 12, 31)


def _cancel_marker_pcv(company: str) -> None:
	for pcv_name in frappe.get_all(
		"Period Closing Voucher",
		filters={"company": company, "remarks": ("like", f"{MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Period Closing Voucher", pcv_name)
		if doc.docstatus != 1:
			continue
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()


def _cancel_marker_jes(company: str) -> None:
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		if doc.docstatus != 1:
			continue
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()


def _purge_marker_gl_orphans(company: str) -> None:
	"""Mark GL active rows cancelled when marker JE is already docstatus=2."""
	voucher_nos = frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{MARKER}%"), "docstatus": 2},
		pluck="name",
	)
	if not voucher_nos:
		return
	frappe.db.sql(
		"""
		update `tabGL Entry`
		set is_cancelled=1
		where company=%(company)s and voucher_no in %(vouchers)s and is_cancelled=0
		""",
		{"company": company, "vouchers": voucher_nos},
	)
	frappe.db.commit()


def _cost_center(company: str) -> str:
	cc = frappe.db.get_value(
		"Cost Center", {"company": company, "is_group": 0, "disabled": 0}, "name", order_by="lft"
	)
	if cc:
		return cc
	parent = frappe.db.get_value("Company", company, "cost_center")
	doc = frappe.new_doc("Cost Center")
	doc.cost_center_name = f"{MARKER}-CC"
	doc.company = company
	if parent:
		doc.parent_cost_center = parent
	doc.is_group = 0
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _closing_account(company: str) -> str:
	for candidate in (
		frappe.db.get_value("Company", company, "default_provisional_account"),
		frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Equity", "is_group": 0, "disabled": 0},
			"name",
		),
		"Retained Earnings - _TC",
	):
		if candidate and frappe.db.get_value("Account", candidate, "root_type") in ("Liability", "Equity"):
			return candidate
	raise frappe.ValidationError(f"No liability/equity closing account for {company}")


def _submit_je(
	company: str,
	posting_date,
	target: str,
	offset: str,
	*,
	debit: float,
	credit: float = 0.0,
	is_opening: str = "No",
	remark: str,
	cost_center: str | None = None,
	patch_opening_on_gl: bool = False,
) -> str:
	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = getdate(posting_date)
	je.user_remark = remark
	je.is_opening = "No" if patch_opening_on_gl else is_opening
	lines = [
		{
			"account": target,
			"debit_in_account_currency": debit,
			"credit_in_account_currency": credit,
			"debit": debit,
			"credit": credit,
		},
		{
			"account": offset,
			"debit_in_account_currency": credit,
			"credit_in_account_currency": debit,
			"debit": credit,
			"credit": debit,
		},
	]
	for line in lines:
		if cost_center:
			line["cost_center"] = cost_center
		je.append("accounts", line)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	if patch_opening_on_gl:
		for gle_name in frappe.get_all(
			"GL Entry",
			filters={"voucher_no": je.name, "account": target, "is_cancelled": 0},
			pluck="name",
		):
			frappe.db.set_value("GL Entry", gle_name, "is_opening", "Yes", update_modified=False)
	return je.name


def _submit_pcv(company: str, period_end_date, *, cost_center: str, closing_account: str) -> str:
	frappe.db.set_single_value("Accounts Settings", "use_legacy_controller_for_pcv", 1)
	fy_name, fy_start, fy_end = get_fiscal_year(period_end_date, company=company)
	pcv = frappe.get_doc(
		{
			"doctype": "Period Closing Voucher",
			"company": company,
			"fiscal_year": fy_name,
			"period_start_date": fy_start,
			"period_end_date": fy_end,
			"transaction_date": period_end_date,
			"closing_account_head": closing_account,
			"cost_center": cost_center,
			"remarks": f"{MARKER}-FY-CLOSE",
		}
	)
	pcv.flags.ignore_permissions = True
	pcv.insert()
	pcv.submit()
	frappe.db.commit()
	return pcv.name


def _dedicated_target_account(company: str, currency: str | None) -> str:
	account_name = f"{MARKER}-Target"
	existing = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
	if existing:
		return existing
	parent = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Asset"},
		"name",
		order_by="lft",
	)
	doc = frappe.new_doc("Account")
	doc.account_name = account_name
	doc.company = company
	doc.parent_account = parent
	doc.is_group = 0
	if currency:
		doc.account_currency = currency
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_pcv_acb_context(company: str) -> dict[str, Any]:
	"""Deterministic PCV dataset for GF-13 … GF-17 (native documents only)."""
	_cancel_marker_pcv(company)
	_cancel_marker_jes(company)
	_purge_marker_gl_orphans(company)
	frappe.db.set_single_value("Accounts Settings", "ignore_account_closing_balance", 0)

	currency = frappe.db.get_value("Company", company, "default_currency")
	target = _dedicated_target_account(company, currency)
	_, offset = _balancing_accounts(company, currency)
	cost_center = _cost_center(company)
	closing_account = _closing_account(company)

	# GF-13/17 core: normal + opening-flagged before PCV
	_submit_je(
		company,
		date(2025, 11, 1),
		target,
		offset,
		debit=800,
		remark=f"{MARKER}-NORMAL-PRE",
		cost_center=cost_center,
	)
	_submit_je(
		company,
		date(2025, 11, 2),
		target,
		offset,
		debit=200,
		is_opening="Yes",
		remark=f"{MARKER}-OPENING-PRE",
		cost_center=cost_center,
	)

	pcv_name = _submit_pcv(company, PCV_END, cost_center=cost_center, closing_account=closing_account)

	# GF-15: gap opening after PCV (normal JE + GL flag patch — ERPNext blocks is_opening JE after PCV)
	_submit_je(
		company,
		GAP_START,
		target,
		offset,
		debit=150,
		remark=f"{MARKER}-GAP-OPENING",
		cost_center=cost_center,
		patch_opening_on_gl=True,
	)

	# GF-16: in-period opening after PCV
	_submit_je(
		company,
		date(2026, 4, 10),
		target,
		offset,
		debit=300,
		remark=f"{MARKER}-IN-PERIOD-OPENING",
		cost_center=cost_center,
		patch_opening_on_gl=True,
	)

	# In-period normal for turnover sanity
	_submit_je(
		company,
		date(2026, 4, 12),
		target,
		offset,
		debit=50,
		remark=f"{MARKER}-IN-PERIOD-NORMAL",
		cost_center=cost_center,
	)

	frappe.db.commit()

	payload_off = _payload(company, include_opening_entries=False)
	spec_off = AccountExplorerQuerySpec_from_client(payload_off, require_dates=True)
	engine_off = select_account_axis_engine(spec_off)

	return {
		"company": company,
		"target_account": target,
		"offset_account": offset,
		"cost_center": cost_center,
		"pcv_name": pcv_name,
		"pcv_end": str(PCV_END),
		"from_date": str(FROM_DATE),
		"to_date": str(TO_DATE),
		"engine_off_unfiltered": engine_off.value,
		"acb_opening_baked": opening_flagged_baked_in_acb(spec_off),
	}


def cleanup_pcv_acb(company: str) -> None:
	_cancel_marker_pcv(company)
	_cancel_marker_jes(company)
	_purge_marker_gl_orphans(company)


def _payload(company: str, *, include_opening_entries: bool, account: str | None = None) -> str:
	import json

	document = {
		"company": company,
		"fiscal_year": "2026",
		"from_date": str(FROM_DATE),
		"to_date": str(TO_DATE),
		"hide_zero_rows": 0,
		"status": {
			"include_opening_entries": 1 if include_opening_entries else 0,
			"include_cancelled_entries": 0,
			"include_period_closing_vouchers": 0,
			"include_default_finance_book_entries": 1,
		},
	}
	if account:
		document["accounting"] = {"account": account}
	return json.dumps(
		{
			"document_scope": document,
			"analysis_context": {"view_axis": "account_level", "page_size": 50, "page": 1},
		}
	)
