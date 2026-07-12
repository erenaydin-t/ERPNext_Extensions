# Copyright (c) 2026, ERPNext Extensions contributors
# For license information, please see license.txt

"""Bank-related Accounting Dimensions on PDC JE rows — explicit PDC fields only, shared eligibility."""

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

_BANK_RELATED_DOCUMENT_TYPES = frozenset({"Bank", "Bank Account"})


def get_pdc_bank_related_accounting_dimensions() -> list[dict[str, str]]:
	"""Active Accounting Dimensions tied to Bank or Bank Account masters (for PDC JE copy rules)."""
	rows = frappe.get_all(
		"Accounting Dimension",
		filters={"document_type": ["in", list(_BANK_RELATED_DOCUMENT_TYPES)], "disabled": 0},
		fields=["fieldname", "name", "label", "document_type"],
		order_by="creation asc",
	)
	out: list[dict[str, str]] = []
	seen: set[str] = set()
	for r in rows:
		fn = (r.get("fieldname") or "").strip()
		if not fn or fn in seen:
			continue
		seen.add(fn)
		out.append(
			{
				"fieldname": fn,
				"name": (r.get("name") or "").strip(),
				"label": (r.get("label") or "").strip(),
				"document_type": (r.get("document_type") or "").strip(),
			}
		)
	return out


def _pick_dimension_fieldname(document_type: str, *, prefer_fieldname: str | None = None) -> str | None:
	candidates = [
		d for d in get_pdc_bank_related_accounting_dimensions() if d["document_type"] == document_type
	]
	if not candidates:
		return None
	if prefer_fieldname:
		for c in candidates:
			if c["fieldname"] == prefer_fieldname:
				return prefer_fieldname
	if len(candidates) == 1:
		return candidates[0]["fieldname"]
	for c in candidates:
		label = (c.get("label") or c.get("name") or "").lower()
		fn = (c.get("fieldname") or "").lower()
		if document_type == "Bank" and ("bank dimension" in label or fn == "bank_dimension"):
			return c["fieldname"]
		if document_type == "Bank Account" and (
			"bank account dimension" in label or fn == "bank_account_dimension"
		):
			return c["fieldname"]
	return candidates[0]["fieldname"]


def get_bank_accounting_dimension_fieldname() -> str | None:
	"""ERPNext fieldname for the active Bank-type Accounting Dimension."""
	return _pick_dimension_fieldname("Bank", prefer_fieldname="bank_dimension")


def get_bank_account_dimension_fieldname() -> str | None:
	"""ERPNext fieldname for the active Bank Account-type Accounting Dimension."""
	return _pick_dimension_fieldname("Bank Account", prefer_fieldname="bank_account_dimension")


def get_pdc_bank_related_dimension_fieldnames() -> frozenset[str]:
	return frozenset(d["fieldname"] for d in get_pdc_bank_related_accounting_dimensions())


def resolve_pdc_accounting_dimension_value(doc, fieldname: str | None) -> str | None:
	"""Read one dimension value from the PDC document field only (never from bank_account)."""
	if not fieldname:
		return None
	return _strip_link_name_or_none(getattr(doc, fieldname, None))


def resolve_pdc_bank_dimension_value(doc) -> str | None:
	fieldname = get_bank_accounting_dimension_fieldname()
	return resolve_pdc_accounting_dimension_value(doc, fieldname)


def resolve_pdc_bank_account_dimension_value(doc) -> str | None:
	fieldname = get_bank_account_dimension_fieldname()
	return resolve_pdc_accounting_dimension_value(doc, fieldname)


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


def apply_pdc_bank_related_dimensions_to_je_row(doc, entry: dict[str, Any]) -> dict[str, Any]:
	"""Set or clear all bank-related dimensions on ``entry`` (bank GL + clearing rows only)."""
	dimensions = get_pdc_bank_related_accounting_dimensions()
	if not dimensions:
		return entry
	eligible = _row_account_needs_bank_dimension(doc, entry.get("account"))
	for dim in dimensions:
		fieldname = dim["fieldname"]
		if not eligible:
			entry.pop(fieldname, None)
			continue
		value = resolve_pdc_accounting_dimension_value(doc, fieldname)
		if value:
			entry[fieldname] = value
		else:
			entry.pop(fieldname, None)
	return entry


def apply_pdc_bank_dimension_to_je_row(doc, entry: dict[str, Any]) -> dict[str, Any]:
	"""Backward-compatible alias — applies every bank-related dimension with shared rules."""
	return apply_pdc_bank_related_dimensions_to_je_row(doc, entry)


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
	bank_related = get_pdc_bank_related_dimension_fieldnames()
	for key, val in (row or {}).items():
		if key in reserved or val in (None, ""):
			continue
		if key in bank_related:
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
	apply_pdc_bank_related_dimensions_to_je_row(doc, entry)
	return entry
