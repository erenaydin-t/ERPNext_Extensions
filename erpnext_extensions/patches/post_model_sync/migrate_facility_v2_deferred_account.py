# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe


def execute() -> None:
	if not frappe.db.has_column("Facility", "deferred_loan_interest_account"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabFacility`
		SET deferred_loan_interest_account = interest_expense_account
		WHERE IFNULL(deferred_loan_interest_account, '') = ''
		  AND IFNULL(interest_expense_account, '') != ''
		"""
	)
	frappe.db.commit()
