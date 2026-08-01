# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
)


def validate(doc, method=None):
	is_issue = cint(doc.get(F_IS_LOAN_ISSUE))
	is_return = cint(doc.get(F_IS_LOAN_RETURN))

	if is_issue and is_return:
		frappe.throw(_("Material Loan Issue and Material Loan Return cannot both be set."))

	if is_issue and doc.purpose != "Material Issue":
		frappe.throw(_("Material Loan Issue is only valid when Purpose is Material Issue."))

	if is_return and doc.purpose != "Material Receipt":
		frappe.throw(_("Material Loan Return is only valid when Purpose is Material Receipt."))

	if doc.purpose != "Material Issue" and is_issue:
		doc.set(F_IS_LOAN_ISSUE, 0)
	if doc.purpose != "Material Receipt" and is_return:
		doc.set(F_IS_LOAN_RETURN, 0)

	# Mutual exclusion with inbound consignment flags
	if (is_issue or is_return) and (cint(doc.get(F_IS_RECEIPT)) or cint(doc.get(F_IS_RETURN))):
		frappe.throw(
			_("Material Loan flags cannot be combined with Consignment Receipt/Return flags.")
		)
