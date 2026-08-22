# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""DB fixtures for OpeningEntryPolicy production integration (GF-01 … GF-17)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import flt, getdate

from erpnext_extensions.iran_accounting.tests.opening_policy_golden_fixtures import (
	FROM_DATE,
	MARKER,
	TO_DATE,
	GOLDEN_FIXTURES_BY_ID,
)

INTEGRATION_MARKER = f"{MARKER}-PROD"


def _balancing_accounts(company: str, currency: str | None = None) -> tuple[str, str]:
	from erpnext_extensions.iran_accounting.tests.analytical_parity_fixtures import _non_party_leaf

	accounts = _non_party_leaf(company, 2, currency) or _non_party_leaf(company, 2)
	if len(accounts) < 2:
		frappe.throw("Need at least 2 non-party leaf accounts for opening policy integration")
	return accounts[0], accounts[1]


def _cancel_marker_jes(company: str) -> None:
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{INTEGRATION_MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()


def _post_single_row(
	company: str,
	target_account: str,
	offset_account: str,
	row: dict[str, Any],
	*,
	fixture_id: str,
	seq: int | str,
	cost_center: str | None = None,
) -> str:
	debit = flt(row.get("debit"))
	credit = flt(row.get("credit"))
	if debit and credit:
		_post_single_row(
			company,
			target_account,
			offset_account,
			{**row, "debit": debit, "credit": 0},
			fixture_id=fixture_id,
			seq=f"{seq}a",
			cost_center=cost_center,
		)
		return _post_single_row(
			company,
			target_account,
			offset_account,
			{**row, "debit": 0, "credit": credit},
			fixture_id=fixture_id,
			seq=f"{seq}b",
			cost_center=cost_center,
		)
	posting_date = getdate(row.get("posting_date"))
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = f"{INTEGRATION_MARKER}-{fixture_id}-{seq}"
	target_line = {
		"account": target_account,
		"debit_in_account_currency": debit,
		"credit_in_account_currency": credit,
		"debit": debit,
		"credit": credit,
	}
	offset_line = {
		"account": offset_account,
		"debit_in_account_currency": credit,
		"credit_in_account_currency": debit,
		"debit": credit,
		"credit": debit,
	}
	if cost_center:
		target_line["cost_center"] = cost_center
		offset_line["cost_center"] = cost_center
	je.append("accounts", target_line)
	je.append("accounts", offset_line)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()

	gl_name = frappe.db.get_value(
		"GL Entry",
		{"voucher_no": je.name, "account": target_account, "debit": debit, "credit": credit},
		"name",
	)
	if gl_name:
		patch = {
			"is_opening": row.get("is_opening", "No"),
			"is_cancelled": int(row.get("is_cancelled") or 0),
		}
		if row.get("voucher_type") and row.get("voucher_type") != "Journal Entry":
			patch["voucher_type"] = row.get("voucher_type")
		if row.get("finance_book"):
			patch["finance_book"] = row.get("finance_book")
		if row.get("party") is not None:
			patch["party"] = row.get("party")
		frappe.db.set_value("GL Entry", gl_name, patch, update_modified=False)
	return je.name


def ensure_gf_production_context(company: str, fixture_id: str) -> dict:
	fixture = GOLDEN_FIXTURES_BY_ID[fixture_id]
	_cancel_marker_jes(company)
	currency = frappe.db.get_value("Company", company, "default_currency")
	target, offset = _balancing_accounts(company, currency)
	for row in fixture.rows:
		if row.get("finance_book") and not frappe.db.exists("Finance Book", row["finance_book"]):
			fb = frappe.new_doc("Finance Book")
			fb.finance_book_name = row["finance_book"]
			fb.flags.ignore_permissions = True
			fb.insert()
	for seq, row in enumerate(fixture.rows, start=1):
		_post_single_row(company, target, offset, row, fixture_id=fixture_id, seq=seq)
	frappe.db.commit()
	return {
		"company": company,
		"target_account": target,
		"offset_account": offset,
		"from_date": str(FROM_DATE),
		"to_date": str(TO_DATE),
		"fixture_id": fixture_id,
	}


def cleanup_gf_production(company: str) -> None:
	_cancel_marker_jes(company)
