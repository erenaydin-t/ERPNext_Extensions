# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any

import frappe
from frappe import _

DEFAULT_RECEIPT_REMARKS = "{facility_number} دریافت تسهیلات از {bank}"
DEFAULT_RECEIPT_BANK_ROW = "{facility_number} واریز تسهیلات"
DEFAULT_RECEIPT_DEFERRED_ROW = "{facility_number} ثبت فرع / بهره سنوات آتی تسهیلات"
DEFAULT_RECEIPT_LOAN_ROW = "{facility_number} ثبت تعهد اصل و فرع تسهیلات"

DEFAULT_REPAYMENT_REMARKS = "{facility_number} پرداخت قسط تسهیلات"
DEFAULT_REPAYMENT_BANK_ROW = "{facility_number} پرداخت قسط تسهیلات از بانک"
DEFAULT_REPAYMENT_PRINCIPAL_ROW = "{facility_number} پرداخت اصل قسط تسهیلات"
DEFAULT_REPAYMENT_PROFIT_ROW = "{facility_number} پرداخت فرع / بهره سنوات آتی قسط تسهیلات"
DEFAULT_REPAYMENT_PENALTY_ROW = "{facility_number} پرداخت هزینه دیرکرد / کارمزد تسهیلات"

FACILITY_SETTINGS_TEMPLATE_DEFAULTS: dict[str, str] = {
	"default_receipt_remarks_template": DEFAULT_RECEIPT_REMARKS,
	"default_receipt_bank_row_description_template": DEFAULT_RECEIPT_BANK_ROW,
	"default_receipt_deferred_interest_row_description_template": DEFAULT_RECEIPT_DEFERRED_ROW,
	"default_receipt_loan_payable_row_description_template": DEFAULT_RECEIPT_LOAN_ROW,
	"default_repayment_remarks_template": DEFAULT_REPAYMENT_REMARKS,
	"default_repayment_bank_row_description_template": DEFAULT_REPAYMENT_BANK_ROW,
	"default_repayment_principal_row_description_template": DEFAULT_REPAYMENT_PRINCIPAL_ROW,
	"default_repayment_profit_row_description_template": DEFAULT_REPAYMENT_PROFIT_ROW,
	"default_repayment_penalty_row_description_template": DEFAULT_REPAYMENT_PENALTY_ROW,
}


def populate_facility_settings_template_defaults(doc) -> None:
	"""Fill empty JE description templates (PDC Settings–style); never overwrite custom values."""
	for fieldname, default in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.items():
		val = doc.get(fieldname)
		if val is None or not str(val).strip():
			doc.set(fieldname, default)


ACCOUNT_FIELDS = (
	"bank_account",
	"loan_payable_account",
	"deferred_loan_interest_account",
	"interest_expense_account",
	"penalty_expense_account",
)

DIMENSION_FIELDS = (
	"cost_center",
	"department",
	"bank_dimension",
	"bank_account_dimension",
)

_SETTINGS_ACCOUNT_MAP = {
	"bank_account": "default_bank_account",
	"loan_payable_account": "default_loan_payable_account",
	"deferred_loan_interest_account": "default_deferred_loan_interest_account",
	"interest_expense_account": "default_interest_expense_account",
	"penalty_expense_account": "default_penalty_expense_account",
}

_SETTINGS_DIMENSION_MAP = {
	"cost_center": "default_cost_center",
	"department": "default_department",
	"bank_dimension": "default_bank_dimension",
	"bank_account_dimension": "default_bank_account_dimension",
}


def get_facility_settings_doc(company: str):
	if not company:
		return None
	name = frappe.db.get_value("Facility Settings", {"company": company}, "name")
	if not name:
		return None
	return frappe.get_doc("Facility Settings", name)


def _value_from_settings(settings, fieldname: str, *, account: bool) -> Any:
	if not settings:
		return None
	key = (_SETTINGS_ACCOUNT_MAP if account else _SETTINGS_DIMENSION_MAP).get(fieldname, fieldname)
	return settings.get(key)


def resolve_account(
	fieldname: str,
	*,
	repayment=None,
	facility=None,
	settings=None,
	required: bool = False,
	required_label: str | None = None,
) -> str | None:
	for source in (repayment, facility):
		if not source:
			continue
		val = source.get(fieldname)
		if val:
			return val
	val = _value_from_settings(settings, fieldname, account=True)
	if val:
		return val
	if required:
		label = required_label or fieldname
		frappe.throw(_("Missing required account: {0}").format(_(label)))
	return None


def resolve_dimension(fieldname: str, *, repayment=None, facility=None, settings=None) -> Any:
	for source in (repayment, facility):
		if not source:
			continue
		val = source.get(fieldname)
		if val not in (None, ""):
			return val
	val = _value_from_settings(settings, fieldname, account=False)
	if val not in (None, ""):
		return val
	return None


def _mandatory_pl_dimension_defaults(company: str) -> dict[str, Any]:
	"""Fill mandatory P&L accounting dimensions from Company / first linked doc when not on Facility."""
	out: dict[str, Any] = {}
	if not company:
		return out
	for row in frappe.get_all(
		"Accounting Dimension",
		filters={"disabled": 0, "mandatory_for_pl": 1},
		fields=["fieldname", "document_type"],
	):
		fn = (row.fieldname or "").strip()
		if not fn or not _je_account_has_field(fn):
			continue
		val = None
		if frappe.db.has_column("Company", fn):
			val = frappe.db.get_value("Company", company, fn)
		dt = row.document_type
		if not val and dt:
			filters = {"company": company} if frappe.get_meta(dt).has_field("company") else {}
			val = frappe.db.get_value(dt, filters, "name", order_by="creation asc")
		if not val:
			val = frappe.db.get_value(dt, {}, "name", order_by="creation asc")
		if val:
			out[fn] = val
	return out


def dimensions_for_je_row(*, repayment=None, facility=None, settings=None) -> dict[str, Any]:
	out: dict[str, Any] = {}
	for fn in DIMENSION_FIELDS:
		val = resolve_dimension(fn, repayment=repayment, facility=facility, settings=settings)
		if val not in (None, "") and _je_account_has_field(fn):
			out[fn] = val
	if "cost_center" not in out and _je_account_has_field("cost_center"):
		company = None
		if facility:
			company = facility.company
		elif repayment:
			company = repayment.get("company") or frappe.db.get_value(
				"Facility", repayment.get("facility"), "company"
			)
		if company:
			cc = frappe.db.get_value("Company", company, "cost_center")
			if not cc:
				cc = frappe.db.get_value(
					"Cost Center", {"company": company, "is_group": 0}, "name", order_by="creation asc"
				)
			if cc:
				out["cost_center"] = cc
	if facility:
		je_meta = frappe.get_meta("Journal Entry Account")
		fac_meta = frappe.get_meta("Facility")
		for df in fac_meta.fields:
			fn = df.fieldname
			if fn in out or fn in DIMENSION_FIELDS or fn in ACCOUNT_FIELDS:
				continue
			if df.fieldtype not in ("Link", "Data", "Dynamic Link"):
				continue
			if not je_meta.has_field(fn):
				continue
			val = facility.get(fn)
			if val not in (None, ""):
				out[fn] = val
	company = None
	if facility:
		company = facility.company
	elif repayment:
		company = repayment.get("company") or frappe.db.get_value(
			"Facility", repayment.get("facility"), "company"
		)
	for fn, val in _mandatory_pl_dimension_defaults(company or "").items():
		if fn not in out and val not in (None, ""):
			out[fn] = val
	return out


def _je_account_has_field(fieldname: str) -> bool:
	return frappe.get_meta("Journal Entry Account").has_field(fieldname)


def template_chain(
	*,
	facility_key: str,
	settings_key: str,
	facility,
	settings,
	default: str,
) -> str:
	if facility and facility.get(facility_key):
		return facility.get(facility_key)
	if settings and settings.get(settings_key):
		return settings.get(settings_key)
	return default
