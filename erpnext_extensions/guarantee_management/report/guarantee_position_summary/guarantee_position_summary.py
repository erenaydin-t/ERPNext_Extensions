# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT. See LICENSE file for details.

"""Guarantee Position Summary — custody KPIs by currency (no accounting)."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate

from erpnext_extensions.guarantee_management.services.party_display import (
	batch_resolve_party_displays,
	format_party_display,
)
from erpnext_extensions.guarantee_management.services.possession import (
	get_expiry_bucket,
	get_held_by_label,
	is_active_but_expired,
	is_expiring_soon,
	is_held_by_others,
	is_held_by_us,
)


def execute(filters=None):
	filters = frappe._dict(filters or {})
	as_on = getdate(filters.as_on_date) if filters.get("as_on_date") else getdate()
	filters.as_on_date = as_on

	columns = _get_columns()
	rows = _get_rows(filters)
	_apply_party_displays(rows)

	report_summary = _build_report_summary(rows, as_on)
	message = _build_message(report_summary)

	# Apply derived filters after possession/expiry computation.
	data = _apply_derived_filters(rows, filters, as_on)

	return columns, data, message, None, report_summary


def _get_columns() -> list[dict]:
	return [
		{
			"label": _("Document No."),
			"fieldname": "document_no",
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"label": _("Name"),
			"fieldname": "name",
			"fieldtype": "Link",
			"options": "Guarantee Document",
			"width": 140,
		},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 100},
		{"label": _("Held By"), "fieldname": "held_by", "fieldtype": "Data", "width": 120},
		{"label": _("Direction"), "fieldname": "guarantee_direction", "fieldtype": "Data", "width": 90},
		{"label": _("Party Type"), "fieldname": "party_type", "fieldtype": "Data", "width": 100},
		{"label": _("Party"), "fieldname": "party_display", "fieldtype": "Data", "width": 220},
		{"label": _("Party ID"), "fieldname": "party", "fieldtype": "Data", "width": 120},
		{
			"label": _("Guarantee Type"),
			"fieldname": "guarantee_type",
			"fieldtype": "Data",
			"width": 130,
		},
		{
			"label": _("Issuing Bank"),
			"fieldname": "issuing_bank",
			"fieldtype": "Link",
			"options": "Bank",
			"width": 140,
		},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "width": 130},
		{
			"label": _("Currency"),
			"fieldname": "currency",
			"fieldtype": "Link",
			"options": "Currency",
			"width": 90,
		},
		{"label": _("Expiry Date"), "fieldname": "expiry_date", "fieldtype": "Date", "width": 110},
		{"label": _("Expiry Bucket"), "fieldname": "expiry_bucket", "fieldtype": "Data", "width": 140},
		{
			"label": _("Company"),
			"fieldname": "company",
			"fieldtype": "Link",
			"options": "Company",
			"width": 160,
		},
	]


def _get_rows(filters: frappe._dict) -> list[dict]:
	where: list[str] = []
	params: dict[str, Any] = {}

	if filters.get("company"):
		where.append("company = %(company)s")
		params["company"] = filters.company
	if filters.get("status"):
		where.append("status = %(status)s")
		params["status"] = filters.status
	if filters.get("guarantee_direction"):
		where.append("guarantee_direction = %(guarantee_direction)s")
		params["guarantee_direction"] = filters.guarantee_direction
	if filters.get("party_type"):
		where.append("party_type = %(party_type)s")
		params["party_type"] = filters.party_type
	if filters.get("party"):
		where.append("party = %(party)s")
		params["party"] = filters.party
	if filters.get("guarantee_type"):
		where.append("guarantee_type = %(guarantee_type)s")
		params["guarantee_type"] = filters.guarantee_type
	if filters.get("issuing_bank"):
		where.append("issuing_bank = %(issuing_bank)s")
		params["issuing_bank"] = filters.issuing_bank
	if filters.get("currency"):
		where.append("currency = %(currency)s")
		params["currency"] = filters.currency
	if filters.get("from_expiry_date"):
		where.append("expiry_date >= %(from_expiry_date)s")
		params["from_expiry_date"] = filters.from_expiry_date
	if filters.get("to_expiry_date"):
		where.append("expiry_date <= %(to_expiry_date)s")
		params["to_expiry_date"] = filters.to_expiry_date

	conditions = (" where " + " and ".join(where)) if where else ""

	rows = frappe.db.sql(
		f"""
		select
			name,
			document_no,
			status,
			guarantee_direction,
			party_type,
			party,
			other_party_name,
			guarantee_type,
			issuing_bank,
			amount,
			currency,
			expiry_date,
			company
		from `tabGuarantee Document`
		{conditions}
		order by expiry_date asc, modified desc
		""",
		params,
		as_dict=True,
	)
	return rows


def _apply_party_displays(rows: list[dict]) -> None:
	refs = [
		{
			"party_type": r.party_type,
			"party": r.party,
			"other_party_name": r.other_party_name,
		}
		for r in rows
	]
	resolved = batch_resolve_party_displays(refs)
	for r in rows:
		if (r.party_type or "").strip() == "Other":
			key = f"Other::{(r.other_party_name or '').strip()}"
			r.party_display = resolved.get(key) or format_party_display(
				"Other", None, other_party_name=r.other_party_name
			)
		else:
			key = f"{(r.party_type or '').strip()}::{(r.party or '').strip()}"
			r.party_display = resolved.get(key) or (r.party or "")


def _apply_derived_filters(rows: list[dict], filters: frappe._dict, as_on) -> list[dict]:
	out = []
	held_by_filter = (filters.get("held_by") or "").strip()
	bucket_filter = (filters.get("expiry_bucket") or "").strip()

	for r in rows:
		held_by = get_held_by_label(r.status, r.guarantee_direction)
		r.held_by = held_by
		# Expiry bucket for Active rows uses the shared helper; for non-Active still show bucket of date.
		r.expiry_bucket = get_expiry_bucket(r.expiry_date, as_on)

		if held_by_filter and held_by != held_by_filter:
			continue
		if bucket_filter and r.expiry_bucket != bucket_filter:
			continue
		out.append(r)
	return out


def _build_report_summary(rows: list[dict], as_on) -> list[dict]:
	"""KPI cards — one entry per currency per KPI (never combine currencies)."""
	held_us: dict[str, float] = defaultdict(float)
	held_others: dict[str, float] = defaultdict(float)
	active_expired: dict[str, float] = defaultdict(float)
	expiring_soon: dict[str, float] = defaultdict(float)

	for r in rows:
		currency = (r.currency or "").strip() or _("No Currency")
		amount = flt(r.amount)
		if is_held_by_us(r.status, r.guarantee_direction):
			held_us[currency] += amount
		if is_held_by_others(r.status, r.guarantee_direction):
			held_others[currency] += amount
		if is_active_but_expired(r.status, r.expiry_date, as_on):
			active_expired[currency] += amount
		if is_expiring_soon(r.status, r.expiry_date, as_on, days=30):
			expiring_soon[currency] += amount

	summary: list[dict] = []
	_append_kpi_summary(summary, _("Held by Us"), held_us)
	_append_kpi_summary(summary, _("Held by Others"), held_others)
	_append_kpi_summary(summary, _("Active but Expired"), active_expired)
	_append_kpi_summary(summary, _("Expiring Soon"), expiring_soon)
	return summary


def _append_kpi_summary(summary: list[dict], label: str, by_currency: dict[str, float]) -> None:
	if not by_currency:
		summary.append({"value": 0, "label": label, "datatype": "Currency"})
		return
	for currency in sorted(by_currency.keys()):
		summary.append(
			{
				"value": by_currency[currency],
				"label": f"{label} ({currency})",
				"datatype": "Currency",
				"currency": currency if currency != _("No Currency") else None,
			}
		)


def _build_message(report_summary: list[dict]) -> str:
	if not report_summary:
		return ""
	parts = []
	for item in report_summary:
		parts.append(f"{item.get('label')}: {frappe.format_value(item.get('value'), {'fieldtype': 'Currency'})}")
	return "<br>".join(parts)


# Exposed for tests / external callers
def compute_kpis(rows: list[dict], as_on_date) -> dict[str, dict[str, float]]:
	as_on = getdate(as_on_date)
	result = {
		"held_by_us": defaultdict(float),
		"held_by_others": defaultdict(float),
		"active_but_expired": defaultdict(float),
		"expiring_soon": defaultdict(float),
	}
	for r in rows:
		currency = (r.get("currency") or "").strip() or "NONE"
		amount = flt(r.get("amount"))
		status = r.get("status")
		direction = r.get("guarantee_direction")
		expiry = r.get("expiry_date")
		if is_held_by_us(status, direction):
			result["held_by_us"][currency] += amount
		if is_held_by_others(status, direction):
			result["held_by_others"][currency] += amount
		if is_active_but_expired(status, expiry, as_on):
			result["active_but_expired"][currency] += amount
		if is_expiring_soon(status, expiry, as_on, days=30):
			result["expiring_soon"][currency] += amount
	return {k: dict(v) for k, v in result.items()}


def expiring_soon_end(as_on_date, days: int = 30):
	return add_days(getdate(as_on_date), days)
