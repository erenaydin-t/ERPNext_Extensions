# Copyright (c) 2026, ERPNext Extensions contributors
# For license information, please see license.txt

"""Bank Dimension on PDC Journal Entry account rows — value from PDC only, account-based eligibility."""

from __future__ import annotations

from typing import Any

import frappe

from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_accounting_dimensions

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_get_pdc_settings_for_company,
	_pdc_bank_gl_account,
	_strip_link_name_or_none,
	resolve_pdc_accounts_for_journal,
)

_BANK_DIMENSION_DOCTYPE = "Bank"


def get_bank_accounting_dimension_fieldname() -> str | None:
	"""Return ERPNext fieldname for the active Accounting Dimension with document_type Bank."""
	rows = frappe.get_all(
		"Accounting Dimension",
		filters={"document_type": _BANK_DIMENSION_DOCTYPE, "disabled": 0},
		fields=["fieldname", "name", "label"],
		order_by="creation asc",
	)
	if not rows:
		return None
	if len(rows) == 1:
		return (rows[0].fieldname or "").strip() or None
	# Prefer label/name hinting "bank"; else first Bank-type dimension.
	for r in rows:
		label = (r.get("label") or r.get("name") or "").lower()
		if "bank" in label or "بانک" in label:
			return (r.fieldname or "").strip() or None
	return (rows[0].fieldname or "").strip() or None


def resolve_pdc_bank_dimension_value(doc) -> str | None:
	"""Bank Dimension value from the PDC document field only (not from ``bank_account``)."""
	fieldname = get_bank_accounting_dimension_fieldname()
	if not fieldname:
		return None
	return _strip_link_name_or_none(getattr(doc, fieldname, None))


def _resolved_cheques_in_clearing_gl(doc) -> str | None:
	company = getattr(doc, "company", None)
	settings = _get_pdc_settings_for_company(company) if company else None
	acc = resolve_pdc_accounts_for_journal(doc, settings)
	return _strip_link_name_or_none(acc.get("cheques_in_clearing"))


def _row_account_needs_bank_dimension(doc, account: str | None) -> bool:
	acc = _strip_link_name_or_none(account)
	if not acc:
		return False
	bank_gl = _pdc_bank_gl_account(doc)
	clearing_gl = _resolved_cheques_in_clearing_gl(doc)
	targets = {a for a in (bank_gl, clearing_gl) if a}
	return acc in targets


def apply_pdc_bank_dimension_to_je_row(doc, entry: dict[str, Any]) -> dict[str, Any]:
	"""Set or clear Bank Dimension on ``entry`` when account is bank GL or cheques-in-clearing GL."""
	fieldname = get_bank_accounting_dimension_fieldname()
	if not fieldname:
		return entry
	if not _row_account_needs_bank_dimension(doc, entry.get("account")):
		entry.pop(fieldname, None)
		return entry
	bank_value = resolve_pdc_bank_dimension_value(doc)
	if not bank_value:
		entry.pop(fieldname, None)
		return entry
	entry[fieldname] = bank_value
	return entry


def copy_pdc_payload_row_extras_into_je_entry(row: dict[str, Any], entry: dict[str, Any]) -> dict[str, Any]:
	"""Preserve accounting dimension (and cost_center/project) keys from payload rows."""
	reserved = {
		"account",
		"debit_in_account_currency",
		"credit_in_account_currency",
		"party_type",
		"party",
		"reference_type",
		"reference_name",
	}
	dim_fields = set(get_accounting_dimensions() or [])
	bank_dim_field = get_bank_accounting_dimension_fieldname()
	for key, val in (row or {}).items():
		if key in reserved or val in (None, ""):
			continue
		if bank_dim_field and key == bank_dim_field:
			continue
		if key in dim_fields or key in ("cost_center", "project"):
			entry[key] = val
	return entry


def build_je_account_row_from_pdc_payload(
	doc,
	row: dict[str, Any],
	*,
	bank_gl_party_strip: str | None = None,
) -> dict[str, Any]:
	"""Map one PDC JE payload account dict to a Journal Entry Account row dict."""
	entry: dict[str, Any] = {"account": row["account"]}
	if row.get("debit_in_account_currency"):
		entry["debit_in_account_currency"] = row["debit_in_account_currency"]
	if row.get("credit_in_account_currency"):
		entry["credit_in_account_currency"] = row["credit_in_account_currency"]

	acc = _strip_link_name_or_none(row.get("account"))
	is_bank_line = bool(bank_gl_party_strip and acc == bank_gl_party_strip)
	if not is_bank_line:
		if row.get("party_type"):
			entry["party_type"] = row["party_type"]
		if row.get("party"):
			entry["party"] = row["party"]
	if row.get("reference_type"):
		entry["reference_type"] = row["reference_type"]
	if row.get("reference_name"):
		entry["reference_name"] = row["reference_name"]

	copy_pdc_payload_row_extras_into_je_entry(row, entry)
	apply_pdc_bank_dimension_to_je_row(doc, entry)
	return entry
