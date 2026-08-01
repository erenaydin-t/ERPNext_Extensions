# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_IS_LOAN_ISSUE,
	F_IS_LOAN_RETURN,
)
from erpnext_extensions.consignment_stock.material_loan.frozen_valuation import (
	refresh_issue_frozen_valuation,
)
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import has_submitted_loan_returns


def validate_repost_item_valuation(doc, method=None):
	"""Block explicit transaction repost of Material Loan Issue/Return after returns exist.

	Item-and-Warehouse RIV is not blocked here: Material Loan Return (Material Receipt)
	creates such RIVs on submit, and same-day posting would deadlock. Transaction-based
	guards plus frozen return rates protect settled valuation.
	"""
	if getattr(doc, "voucher_type", None) == "Stock Entry" and doc.get("voucher_no"):
		_validate_stock_entry_voucher(doc.voucher_no)


def on_repost_completed(doc, method=None):
	if cint(doc.docstatus) != 1:
		return
	if (doc.get("status") or "") != "Completed":
		return
	if doc.get("voucher_type") == "Stock Entry" and doc.get("voucher_no"):
		if frappe.db.get_value("Stock Entry", doc.voucher_no, F_IS_LOAN_ISSUE):
			if not has_submitted_loan_returns(doc.voucher_no):
				refresh_issue_frozen_valuation(doc.voucher_no)
				from erpnext_extensions.consignment_stock.material_loan import status as ml_status

				ml_status.refresh_issue_statuses(doc.voucher_no)


def _validate_stock_entry_voucher(voucher_no: str) -> None:
	flags = frappe.db.get_value(
		"Stock Entry",
		voucher_no,
		[F_IS_LOAN_ISSUE, F_IS_LOAN_RETURN],
		as_dict=True,
	)
	if not flags:
		return
	if cint(flags.get(F_IS_LOAN_ISSUE)) and has_submitted_loan_returns(voucher_no):
		frappe.throw(
			_(
				"Cannot repost Material Loan Issue {0} while submitted Material Loan Returns exist. "
				"Cancel related Settlement JEs and Returns first."
			).format(voucher_no)
		)
	if cint(flags.get(F_IS_LOAN_RETURN)):
		frappe.throw(
			_(
				"Cannot repost Material Loan Return {0}. Cancel the Settlement JE and Return, "
				"then recreate if needed."
			).format(voucher_no)
		)
