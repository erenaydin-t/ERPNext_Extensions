# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.constants import (
	NOT_SPECIFIED_LABEL,
	NOT_SPECIFIED_LABEL_FA,
)


NATIVE_DIMENSIONS = (
	{
		"fieldname": "cost_center",
		"label": "Cost Center",
		"label_fa": "مرکز هزینه",
		"document_type": "Cost Center",
		"is_native": 1,
	},
	{
		"fieldname": "project",
		"label": "Project",
		"label_fa": "پروژه",
		"document_type": "Project",
		"is_native": 1,
	},
)


def filter_usable_gl_dimensions(
	dimensions: list[dict] | None,
	*,
	warn: bool = True,
) -> list[dict]:
	"""Keep only dimensions whose fieldname exists on GL Entry.

	Callers that build SELECT/WHERE/GROUP BY for GL Entry must use this (or
	``get_discovered_dimensions``) so stale Accounting Dimension records or
	mocked fixtures cannot invent SQL columns.
	"""
	gl_meta = frappe.get_meta("GL Entry")
	usable: list[dict] = []
	seen: set[str] = set()
	skipped: list[str] = []
	for row in dimensions or []:
		fieldname = (row or {}).get("fieldname")
		if not fieldname or fieldname in seen:
			continue
		if not gl_meta.has_field(fieldname):
			skipped.append(fieldname)
			continue
		usable.append(row)
		seen.add(fieldname)
	if warn and skipped:
		frappe.logger("erpnext_extensions.account_explorer").warning(
			"Skipping accounting dimensions missing on GL Entry: {0}".format(", ".join(skipped))
		)
		# Desk-visible once per request is enough; avoid toast spam in API loops.
		if getattr(frappe.flags, "ae_missing_dimension_warned", None) != tuple(skipped):
			frappe.flags.ae_missing_dimension_warned = tuple(skipped)
			frappe.msgprint(
				_("Accounting dimensions skipped (no GL Entry field): {0}").format(", ".join(skipped)),
				indicator="orange",
				alert=True,
			)
	return usable


def get_discovered_dimensions() -> list[dict]:
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		get_accounting_dimensions,
	)

	gl_meta = frappe.get_meta("GL Entry")
	dimensions: list[dict] = []
	seen = set()
	stale_custom: list[str] = []

	for native in NATIVE_DIMENSIONS:
		if not gl_meta.has_field(native["fieldname"]):
			continue
		dimensions.append(dict(native))
		seen.add(native["fieldname"])

	for row in get_accounting_dimensions(as_list=False) or []:
		fieldname = row.fieldname
		if not fieldname or fieldname in seen:
			continue
		if not gl_meta.has_field(fieldname):
			stale_custom.append(fieldname)
			continue
		dimensions.append(
			{
				"fieldname": fieldname,
				"label": row.label or fieldname,
				"label_fa": getattr(row, "label", None) or fieldname,
				"document_type": row.document_type,
				"is_native": 0,
			}
		)
		seen.add(fieldname)

	if stale_custom:
		frappe.logger("erpnext_extensions.account_explorer").warning(
			"Accounting Dimension records without GL Entry fields: {0}".format(", ".join(stale_custom))
		)

	return dimensions


def get_allowed_dimension_fieldnames() -> frozenset[str]:
	return frozenset(row["fieldname"] for row in get_discovered_dimensions())


def get_default_dimension_field() -> str | None:
	return get_default_dimension_type()


def get_default_dimension_type() -> str | None:
	dimensions = get_discovered_dimensions()
	for preferred in ("cost_center",):
		for row in dimensions:
			if row["fieldname"] == preferred:
				return preferred
	return dimensions[0]["fieldname"] if dimensions else None


def validate_dimension_field(fieldname: str) -> None:
	if fieldname not in get_allowed_dimension_fieldnames():
		frappe.throw(_("Accounting dimension {0} is not allowed.").format(fieldname))


def get_dimension_display_title(dimension_field: str, value: str) -> str:
	if not value:
		return NOT_SPECIFIED_LABEL
	if dimension_field == "cost_center":
		return frappe.db.get_value("Cost Center", value, "cost_center_name") or value
	if dimension_field == "project":
		return frappe.db.get_value("Project", value, "project_name") or value
	meta = frappe.get_meta("GL Entry").get_field(dimension_field)
	if meta and meta.options:
		return frappe.db.get_value(meta.options, value, "name") or value
	return value


def not_specified_label() -> str:
	locale = frappe.local.lang or "en"
	if locale.startswith("fa"):
		return NOT_SPECIFIED_LABEL_FA
	return NOT_SPECIFIED_LABEL
