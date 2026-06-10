# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Safe placeholder rendering for Facility Management JE remarks and row descriptions."""

from __future__ import annotations

import re
from typing import Any

import frappe
from frappe.utils import cint, flt

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def render_facility_template(template: str | None, context: dict[str, Any]) -> str:
	if not template:
		return ""
	text = str(template)

	def _replace(match: re.Match) -> str:
		key = match.group(1)
		if key not in context:
			return ""
		val = context[key]
		if val is None:
			return ""
		return str(val)

	return _PLACEHOLDER_RE.sub(_replace, text)


def build_template_context(
	facility,
	repayment=None,
	*,
	installment_no: int | None = None,
) -> dict[str, Any]:
	bank_name = facility.bank
	if facility.bank and frappe.db.exists("Bank", facility.bank):
		bank_name = frappe.db.get_value("Bank", facility.bank, "bank_name") or facility.bank
	branch = ""
	if facility.bank and frappe.get_meta("Bank").has_field("branch"):
		branch = frappe.db.get_value("Bank", facility.bank, "branch") or ""

	principal = flt(facility.principal_amount)
	profit = flt(facility.profit_amount)
	penalty = 0.0
	total_payment = 0.0
	if repayment:
		principal = flt(repayment.principal_amount)
		profit = flt(repayment.profit_amount)
		penalty = flt(repayment.penalty_amount)
		total_payment = flt(repayment.total_payment_amount) or principal + profit + penalty

	return {
		"facility": facility.name,
		"facility_name": facility.facility_name or facility.name,
		"facility_number": facility.name,
		"company": facility.company,
		"bank": bank_name,
		"branch": branch,
		"posting_date": (repayment.posting_date if repayment else None)
		or facility.receive_date
		or facility.contract_date,
		"contract_date": facility.contract_date,
		"receive_date": facility.receive_date,
		"maturity_date": getattr(facility, "maturity_date", None),
		"settlement_date": getattr(facility, "settlement_date", None),
		"principal_amount": principal,
		"profit_amount": profit,
		"penalty_amount": penalty,
		"total_liability_amount": flt(facility.total_liability_amount)
		or flt(facility.principal_amount) + flt(facility.profit_amount),
		"total_payment_amount": total_payment,
		"installment_count": cint(getattr(facility, "installment_count", 0)),
		"installment_no": installment_no,
	}
