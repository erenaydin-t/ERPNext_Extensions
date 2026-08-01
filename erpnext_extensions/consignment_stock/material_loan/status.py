# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe.utils import cint, getdate, today

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_EXPECTED_RETURN_DATE,
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
	F_ISSUE_SE,
	F_PHYSICAL_STATUS,
	F_RECOGNITION_JE,
	F_RECOGNITION_STATUS,
	F_SETTLEMENT_JE,
	F_SETTLEMENT_STATUS,
	REC_CANCELLED,
	REC_DRAFT,
	REC_NOT_CREATED,
	REC_SUBMITTED,
	SET_FULLY_SETTLED,
	SET_NOT_REQUIRED,
	SET_PARTIALLY_SETTLED,
	SET_PENDING,
	STATUS_CANCELLED,
	STATUS_DRAFT,
	STATUS_FULLY_RETURNED,
	STATUS_ISSUED,
	STATUS_OVERDUE,
	STATUS_PARTIALLY_RETURNED,
)
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import issue_return_progress


def is_loan_issue(doc) -> bool:
	return bool(cint(doc.get(F_IS_LOAN_ISSUE)))


def is_loan_return(doc) -> bool:
	return bool(cint(doc.get(F_IS_LOAN_RETURN)))


def db_set_statuses(name: str, values: dict) -> None:
	frappe.db.set_value("Stock Entry", name, values, update_modified=False)


def compute_recognition_status(issue_name: str) -> str:
	je = frappe.db.get_value("Stock Entry", issue_name, F_RECOGNITION_JE)
	if not je or not frappe.db.exists("Journal Entry", je):
		return REC_NOT_CREATED
	ds = frappe.db.get_value("Journal Entry", je, "docstatus")
	if ds == 0:
		return REC_DRAFT
	if ds == 1:
		return REC_SUBMITTED
	return REC_CANCELLED


def compute_settlement_status(issue_name: str) -> str:
	"""Issue-level aggregate settlement status across submitted returns."""
	progress = issue_return_progress(issue_name)
	if progress["returned"] <= 0:
		# No returns yet
		rec = compute_recognition_status(issue_name)
		return SET_NOT_REQUIRED if rec != REC_SUBMITTED else SET_PENDING

	returns = frappe.db.sql(
		f"""
		select distinct se.name, se.{F_SETTLEMENT_JE} as settlement_je, se.docstatus
		from `tabStock Entry` se
		inner join `tabStock Entry Detail` sed on sed.parent = se.name
		where se.{F_IS_LOAN_RETURN} = 1
		  and se.docstatus = 1
		  and sed.{F_ISSUE_SE} = %s
		""",
		issue_name,
		as_dict=True,
	)
	if not returns:
		return SET_PENDING

	settled = 0
	for ret in returns:
		je = ret.settlement_je
		if je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1:
			settled += 1

	if settled == 0:
		return SET_PENDING
	if settled < len(returns) or progress["remaining"] > 1e-9:
		# Partially settled if some returns unsettled OR physical remaining
		if settled < len(returns):
			return SET_PARTIALLY_SETTLED
		# All submitted returns settled but qty still outstanding
		return SET_PARTIALLY_SETTLED
	return SET_FULLY_SETTLED


def compute_physical_status(doc) -> str:
	if doc.docstatus == 2:
		return STATUS_CANCELLED
	if doc.docstatus == 0:
		return STATUS_DRAFT

	progress = issue_return_progress(doc.name)
	remaining = progress["remaining"]
	original = progress["original"]

	if remaining <= 1e-9:
		base = STATUS_FULLY_RETURNED
	elif remaining < original - 1e-9:
		base = STATUS_PARTIALLY_RETURNED
	else:
		base = STATUS_ISSUED

	expected = doc.get(F_EXPECTED_RETURN_DATE)
	if expected and remaining > 1e-9 and getdate(today()) > getdate(expected):
		return STATUS_OVERDUE
	return base


def refresh_issue_statuses(issue_name: str) -> None:
	doc = frappe.get_doc("Stock Entry", issue_name)
	if not is_loan_issue(doc):
		return
	values = {
		F_PHYSICAL_STATUS: compute_physical_status(doc),
		F_RECOGNITION_STATUS: compute_recognition_status(issue_name),
		F_SETTLEMENT_STATUS: compute_settlement_status(issue_name),
	}
	db_set_statuses(issue_name, values)
	for key, val in values.items():
		doc.set(key, val)


def sync_draft_status(doc) -> None:
	if is_loan_issue(doc) or is_loan_return(doc):
		if doc.docstatus == 0:
			doc.set(F_PHYSICAL_STATUS, STATUS_DRAFT)
		if is_loan_issue(doc) and doc.docstatus == 0:
			doc.set(F_RECOGNITION_STATUS, REC_NOT_CREATED)
			doc.set(F_SETTLEMENT_STATUS, SET_NOT_REQUIRED)


def on_issue_submit(doc) -> None:
	doc.set(F_PHYSICAL_STATUS, STATUS_ISSUED)
	doc.set(F_RECOGNITION_STATUS, REC_NOT_CREATED)
	doc.set(F_SETTLEMENT_STATUS, SET_NOT_REQUIRED)
	db_set_statuses(
		doc.name,
		{
			F_PHYSICAL_STATUS: STATUS_ISSUED,
			F_RECOGNITION_STATUS: REC_NOT_CREATED,
			F_SETTLEMENT_STATUS: SET_NOT_REQUIRED,
		},
	)


def on_return_submit(doc) -> None:
	seen = set()
	for row in doc.get("items") or []:
		issue = row.get(F_ISSUE_SE)
		if issue and issue not in seen:
			seen.add(issue)
			refresh_issue_statuses(issue)


def on_return_cancel(doc) -> None:
	on_return_submit(doc)


def on_issue_cancel(doc) -> None:
	db_set_statuses(
		doc.name,
		{
			F_PHYSICAL_STATUS: STATUS_CANCELLED,
			F_RECOGNITION_STATUS: REC_CANCELLED
			if doc.get(F_RECOGNITION_JE)
			else REC_NOT_CREATED,
		},
	)


def clear_recognition_link(issue_name: str) -> None:
	frappe.db.set_value("Stock Entry", issue_name, F_RECOGNITION_JE, None, update_modified=False)
	refresh_issue_statuses(issue_name)


def clear_settlement_link(return_name: str) -> None:
	frappe.db.set_value("Stock Entry", return_name, F_SETTLEMENT_JE, None, update_modified=False)
	issues = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": return_name},
		pluck=F_ISSUE_SE,
	)
	for issue in {i for i in issues if i}:
		refresh_issue_statuses(issue)
