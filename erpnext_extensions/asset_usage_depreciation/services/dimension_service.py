# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Generic Accounting Dimension helpers for Asset Request.

Uses ERPNext's native Accounting Dimension metadata. Dimension names are never
hard-coded (no Branch / Business Unit / Division / Territory special cases).
Cost Center and Project stay native DocFields and are included in inheritance.
"""

from __future__ import annotations

import json
import re

import frappe
from frappe import _

AR_DIMENSION_DOCTYPES = ("Asset Request", "Asset Request Item")
_SAFE_FIELD = re.compile(r"^[a-zA-Z][a-zA-Z0-9_]*$")
_NATIVE_FIELDS = ("cost_center", "project")


def _has_field(doctype: str, fieldname: str) -> bool:
	try:
		return bool(frappe.get_meta(doctype).has_field(fieldname))
	except Exception:
		return False


def get_dynamic_dimension_fieldnames() -> list[str]:
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)
	except Exception:
		return []
	return [fn for fn in (get_accounting_dimensions() or []) if fn and _SAFE_FIELD.match(fn)]


def get_dimension_fieldnames() -> list[str]:
	"""Cost Center, Project, then active dynamic accounting dimensions."""
	fields: list[str] = []
	for fn in (*_NATIVE_FIELDS, *get_dynamic_dimension_fieldnames()):
		if fn not in fields:
			fields.append(fn)
	return fields


def get_dimension_details(*, with_cost_center_and_project: bool = True) -> list[dict]:
	"""Runtime metadata: fieldname, label, document_type."""
	details: list[dict] = []
	seen: set[str] = set()
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import get_dimensions

		dims, _defaults = get_dimensions(with_cost_center_and_project=with_cost_center_and_project)
	except Exception:
		dims = []
	for dim in dims or []:
		fn = dim.get("fieldname")
		if not fn or fn in seen or not _SAFE_FIELD.match(fn):
			continue
		seen.add(fn)
		label = dim.get("label") or fn.replace("_", " ").title()
		details.append(
			{
				"fieldname": fn,
				"label": label,
				"document_type": dim.get("document_type") or "",
			}
		)
	if with_cost_center_and_project:
		for fn, label, dt in (
			("cost_center", _("Cost Center"), "Cost Center"),
			("project", _("Project"), "Project"),
		):
			if fn not in seen:
				details.insert(0 if fn == "cost_center" else 1, {"fieldname": fn, "label": label, "document_type": dt})
				seen.add(fn)
	return details


def inheritable_item_fields() -> list[str]:
	return [
		fn
		for fn in get_dimension_fieldnames()
		if _has_field("Asset Request", fn) and _has_field("Asset Request Item", fn)
	]


def apply_header_defaults_to_items(doc, *, only_empty: bool = True) -> None:
	"""Copy header dimension values into empty item cells. Never overwrite non-empty values."""
	fields = inheritable_item_fields()
	if not fields:
		return
	for item in doc.get("items") or []:
		for fn in fields:
			header_val = doc.get(fn)
			if not header_val:
				continue
			if only_empty and item.get(fn):
				continue
			item.set(fn, header_val)


def resolve_item_dimensions(doc, item) -> dict[str, str]:
	"""Item value wins; empty item cells fall back to header."""
	out: dict[str, str] = {}
	for fn in get_dimension_fieldnames():
		item_val = item.get(fn) if item else None
		header_val = doc.get(fn) if doc else None
		out[fn] = item_val or header_val or ""
	return out


def dimension_fingerprint(values: dict) -> str:
	fields = get_dimension_fieldnames()
	payload = {fn: values.get(fn) or "" for fn in fields}
	return json.dumps(payload, sort_keys=True, default=str)


def apply_dimensions_to_target(target, values: dict) -> None:
	"""Set resolved dimension values on a target row if the field exists."""
	if not target or not values:
		return
	meta = getattr(target, "meta", None) or frappe.get_meta(target.doctype)
	for fn, val in values.items():
		if not fn or not meta.has_field(fn):
			continue
		target.set(fn, val)


def validate_dimension_companies(doc) -> None:
	"""Company-compatibility for Cost Center, Project, and dynamic dimensions.

	Mirrors ERPNext AccountsController.validate_company_in_accounting_dimension.
	Does not enforce mandatory_for_pl / mandatory_for_bs (Material Request does not
	at this stage either).
	"""
	company = doc.get("company")
	if not company:
		return

	pairs: list[tuple[str, str]] = [("cost_center", "Cost Center"), ("project", "Project")]
	for dim in get_dimension_details(with_cost_center_and_project=False):
		fn, dt = dim.get("fieldname"), dim.get("document_type")
		if fn and dt and (fn, dt) not in pairs:
			pairs.append((fn, dt))

	rows = [doc, *(doc.get("items") or [])]
	for row in rows:
		for fieldname, dt in pairs:
			value = row.get(fieldname)
			if not value or not frappe.db.exists("DocType", dt):
				continue
			meta = frappe.get_meta(dt)
			if not meta.has_field("company"):
				continue
			value_company = frappe.db.get_value(dt, value, "company")
			if value_company and value_company != company:
				frappe.throw(
					_("{0}: {1} does not belong to the Company: {2}").format(
						dt, frappe.bold(value), company
					)
				)


def provision_asset_request_accounting_dimensions() -> None:
	"""Idempotent: create missing Accounting Dimension Custom Fields on AR doctypes."""
	if not frappe.db.exists("DocType", "Accounting Dimension"):
		return
	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	doclist = [dt for dt in AR_DIMENSION_DOCTYPES if frappe.db.exists("DocType", dt)]
	if not doclist:
		return

	for name in frappe.get_all("Accounting Dimension", pluck="name"):
		dim = frappe.get_doc("Accounting Dimension", name)
		try:
			make_dimension_in_accounting_doctypes(dim, doclist=doclist)
		except Exception:
			frappe.log_error(
				title="Asset Request accounting dimension provisioning skipped",
				message=frappe.get_traceback(),
			)

	# Native backfill helper, skipping fieldnames that already exist as DocFields
	# (e.g. Department as both HR field and Accounting Dimension).
	for dt in doclist:
		_create_accounting_dimensions_for_doctype_safe(dt)
		frappe.clear_cache(doctype=dt)

	backfill_item_cost_center_and_project()


def _create_accounting_dimensions_for_doctype_safe(doctype: str) -> None:
	"""ERPNext create_accounting_dimensions_for_doctype plus DocField existence guard."""
	from frappe.custom.doctype.custom_field.custom_field import create_custom_field

	try:
		meta = frappe.get_meta(doctype, cached=False)
	except Exception:
		return
	existing = {df.fieldname for df in meta.get("fields", [])}
	accounting_dimensions = frappe.db.get_all(
		"Accounting Dimension",
		fields=["fieldname", "label", "document_type", "disabled"],
	)
	if not accounting_dimensions:
		return
	for d in accounting_dimensions:
		fn = (d.fieldname or "").strip()
		if not fn or fn in existing:
			continue
		if frappe.db.get_value("Custom Field", {"dt": doctype, "fieldname": fn}):
			continue
		df = {
			"fieldname": fn,
			"label": d.label,
			"fieldtype": "Link",
			"options": d.document_type,
			"insert_after": "accounting_dimensions_section",
		}
		create_custom_field(doctype, df, ignore_validate=True)
		existing.add(fn)
	frappe.clear_cache(doctype=doctype)


def backfill_item_cost_center_and_project() -> None:
	"""Copy header cost_center / project onto empty item cells. Never overwrite."""
	if not frappe.db.table_exists("Asset Request Item") or not frappe.db.table_exists("Asset Request"):
		return
	for fieldname in ("cost_center", "project"):
		if not frappe.db.has_column("Asset Request Item", fieldname):
			continue
		if not frappe.db.has_column("Asset Request", fieldname):
			continue
		frappe.db.sql(
			f"""
			UPDATE `tabAsset Request Item` ari
			INNER JOIN `tabAsset Request` ar
				ON ar.name = ari.parent AND ari.parenttype = 'Asset Request'
			SET ari.`{fieldname}` = ar.`{fieldname}`
			WHERE IFNULL(ari.`{fieldname}`, '') = ''
				AND IFNULL(ar.`{fieldname}`, '') != ''
			"""
		)


def report_dimension_select_sql(*, header_alias: str = "ar", item_alias: str | None = "ari") -> list[str]:
	parts: list[str] = []
	for dim in get_dimension_details():
		fn = dim["fieldname"]
		if not _SAFE_FIELD.match(fn):
			continue
		header_has = frappe.db.has_column("Asset Request", fn)
		item_has = bool(item_alias) and frappe.db.has_column("Asset Request Item", fn)
		if item_has and header_has:
			parts.append(
				f"COALESCE(NULLIF({item_alias}.`{fn}`, ''), {header_alias}.`{fn}`) AS `{fn}`"
			)
		elif header_has:
			parts.append(f"{header_alias}.`{fn}` AS `{fn}`")
		elif item_has:
			parts.append(f"{item_alias}.`{fn}` AS `{fn}`")
	return parts


def report_dimension_columns() -> list[dict]:
	cols = []
	for dim in get_dimension_details():
		fn = dim["fieldname"]
		cols.append(
			{
				"label": _(dim["label"]),
				"fieldname": fn,
				"fieldtype": "Link" if dim.get("document_type") else "Data",
				"options": dim.get("document_type") or "",
				"width": 130,
			}
		)
	return cols


def report_dimension_filter_sql(
	filters,
	*,
	header_alias: str = "ar",
	item_alias: str | None = "ari",
) -> tuple[str, dict]:
	conds: list[str] = []
	values: dict = {}
	if not filters:
		return "", values
	for dim in get_dimension_details():
		fn = dim["fieldname"]
		val = filters.get(fn)
		if not val:
			continue
		if isinstance(val, str) and "," in val and not frappe.db.exists(dim.get("document_type") or "", val):
			val = [v.strip() for v in val.split(",") if v.strip()]
		header_has = frappe.db.has_column("Asset Request", fn)
		item_has = bool(item_alias) and frappe.db.has_column("Asset Request Item", fn)
		if item_has and header_has:
			expr = f"COALESCE(NULLIF({item_alias}.`{fn}`, ''), {header_alias}.`{fn}`)"
		elif header_has:
			expr = f"{header_alias}.`{fn}`"
		elif item_has:
			expr = f"{item_alias}.`{fn}`"
		else:
			continue
		if isinstance(val, (list, tuple)):
			if not val:
				continue
			values[fn] = list(val)
			conds.append(f"AND {expr} IN %({fn})s")
		else:
			values[fn] = val
			conds.append(f"AND {expr} = %({fn})s")
	return " ".join(conds), values
