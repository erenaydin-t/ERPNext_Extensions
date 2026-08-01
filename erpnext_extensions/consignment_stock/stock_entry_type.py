# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN


def validate(doc, method=None):
	is_receipt = cint(doc.get(F_IS_RECEIPT))
	is_return = cint(doc.get(F_IS_RETURN))

	if is_receipt and is_return:
		frappe.throw(_("Consignment Receipt and Consignment Return cannot both be set."))

	if is_receipt and doc.purpose != "Material Receipt":
		frappe.throw(_("Consignment Receipt is only valid when Purpose is Material Receipt."))

	if is_return and doc.purpose != "Material Issue":
		frappe.throw(_("Consignment Return is only valid when Purpose is Material Issue."))

	if doc.purpose != "Material Receipt" and is_receipt:
		doc.set(F_IS_RECEIPT, 0)
	if doc.purpose != "Material Issue" and is_return:
		doc.set(F_IS_RETURN, 0)

	# Mutual exclusion with Material Loan flags (if present)
	from erpnext_extensions.consignment_stock.material_loan.constants import (
		F_IS_LOAN_ISSUE,
		F_IS_LOAN_RETURN,
	)

	if (is_receipt or is_return) and (
		cint(doc.get(F_IS_LOAN_ISSUE)) or cint(doc.get(F_IS_LOAN_RETURN))
	):
		frappe.throw(
			_("Consignment Receipt/Return flags cannot be combined with Material Loan flags.")
		)
