# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_ISSUE_DETAIL,
	F_ISSUE_RATE,
	F_SETTLEMENT_AMOUNT,
)


def lock_issue_outgoing_rates(doc) -> None:
	"""Material Loan Issue must use system outgoing valuation — no manual basic_rate."""
	for row in doc.get("items") or []:
		row.set_basic_rate_manually = 0


def prepare_return_rates(doc) -> None:
	"""Force return basic_rate from frozen issue rate."""
	for row in doc.get("items") or []:
		detail = row.get(F_ISSUE_DETAIL)
		if not detail:
			continue
		rate = flt(frappe.db.get_value("Stock Entry Detail", detail, F_ISSUE_RATE))
		if rate <= 0:
			frappe.throw(
				_("Row {0}: Frozen Material Loan Issue rate is missing for {1}.").format(
					row.idx, detail
				)
			)
		# Reject client override beyond precision
		if row.get("basic_rate") not in (None, "") and abs(flt(row.basic_rate) - rate) > 1e-6:
			if not cint_allow_reassert():
				pass
		row.basic_rate = rate
		row.set_basic_rate_manually = 1
		qty = flt(row.transfer_qty if row.transfer_qty not in (None, "") else row.qty)
		row.basic_amount = flt(qty * rate)
		row.set(F_ISSUE_RATE, rate)
		row.set(F_SETTLEMENT_AMOUNT, flt(qty * rate))


def cint_allow_reassert() -> bool:
	return True
