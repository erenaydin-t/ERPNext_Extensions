# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
	F_ISSUE_SE,
	F_JE_ROLE,
	F_RECOGNITION_JE,
	F_SETTLEMENT_JE,
	JE_ROLE_RECOGNITION,
	JE_ROLE_SETTLEMENT,
)
from erpnext_extensions.consignment_stock.material_loan import status as ml_status
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import has_submitted_loan_returns


def on_submit(doc, method=None):
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		issue = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if issue:
			ml_status.refresh_issue_statuses(issue)
	elif role == JE_ROLE_SETTLEMENT:
		ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
		if ret:
			_refresh_issues_from_return(ret)


def before_cancel(doc, method=None):
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		issue = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if issue and has_submitted_loan_returns(issue):
			frappe.throw(
				_(
					"Cannot cancel Material Loan Recognition {0} while submitted Material Loan Returns exist "
					"for Issue {1}."
				).format(doc.name, issue)
			)


def on_cancel(doc, method=None):
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		issue = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if issue:
			ml_status.clear_recognition_link(issue)
	elif role == JE_ROLE_SETTLEMENT:
		ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
		if ret:
			ml_status.clear_settlement_link(ret)


def on_trash(doc, method=None):
	if doc.docstatus != 0:
		return
	role = doc.get(F_JE_ROLE) if doc.meta.has_field(F_JE_ROLE) else None
	if role == JE_ROLE_RECOGNITION:
		issue = frappe.db.get_value("Stock Entry", {F_RECOGNITION_JE: doc.name}, "name")
		if issue:
			ml_status.clear_recognition_link(issue)
	elif role == JE_ROLE_SETTLEMENT:
		ret = frappe.db.get_value("Stock Entry", {F_SETTLEMENT_JE: doc.name}, "name")
		if ret:
			ml_status.clear_settlement_link(ret)


def _refresh_issues_from_return(return_name: str) -> None:
	issues = frappe.get_all(
		"Stock Entry Detail",
		filters={"parent": return_name},
		pluck=F_ISSUE_SE,
	)
	for issue in {i for i in issues if i}:
		ml_status.refresh_issue_statuses(issue)
