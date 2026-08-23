# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Script reports for Asset Request (requested vs fulfilled)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint

from erpnext_extensions.asset_usage_depreciation.constants import (
	STATUS_APPROVED,
	STATUS_PARTIALLY_FULFILLED,
	STATUS_PENDING_CEO,
	STATUS_PENDING_MANAGER,
	STATUS_PENDING_PLANNING,
)
from erpnext_extensions.asset_usage_depreciation.services.dimension_service import (
	report_dimension_columns,
	report_dimension_filter_sql,
	report_dimension_select_sql,
)


def _filters(filters) -> dict:
	filters = frappe._dict(filters or {})
	return filters


def requested_vs_fulfilled(filters=None):
	filters = _filters(filters)
	columns = [
		{"label": _("Asset Request"), "fieldname": "asset_request", "fieldtype": "Link", "options": "Asset Request", "width": 140},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Requested Item"), "fieldname": "requested_item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Requested Name"), "fieldname": "requested_item_name", "fieldtype": "Data", "width": 160},
		{"label": _("Fulfilled Item"), "fieldname": "fulfilled_item_code", "fieldtype": "Link", "options": "Item", "width": 140},
		{"label": _("Allocated Asset"), "fieldname": "allocated_asset", "fieldtype": "Link", "options": "Asset", "width": 140},
		{"label": _("Method"), "fieldname": "method", "fieldtype": "Data", "width": 110},
		{"label": _("Status"), "fieldname": "fulfillment_status", "fieldtype": "Data", "width": 110},
		{"label": _("Substituted"), "fieldname": "substituted", "fieldtype": "Check", "width": 90},
		{"label": _("Substitution Reason"), "fieldname": "substitution_reason", "fieldtype": "Small Text", "width": 200},
	]
	columns.extend(report_dimension_columns())
	dim_select = report_dimension_select_sql(header_alias="ar", item_alias="ari")
	dim_sql = (", " + ", ".join(dim_select)) if dim_select else ""
	conds, values = _common_conds(filters, item_alias="ari")
	rows = frappe.db.sql(
		f"""
		SELECT
			ar.name AS asset_request,
			ar.employee,
			al.requested_item_code,
			ari.requested_item_name,
			al.fulfilled_item_code,
			al.allocated_asset,
			al.method,
			al.fulfillment_status,
			CASE WHEN al.requested_item_code != al.fulfilled_item_code THEN 1 ELSE 0 END AS substituted,
			al.substitution_reason
			{dim_sql}
		FROM `tabAsset Request Allocation` al
		INNER JOIN `tabAsset Request` ar ON ar.name = al.parent
		LEFT JOIN `tabAsset Request Item` ari ON ari.name = al.asset_request_item
		WHERE ar.docstatus < 2 {conds}
		ORDER BY ar.creation DESC, al.idx
		""",
		values,
		as_dict=True,
	)
	return columns, rows


def substituted_assets(filters=None):
	filters = _filters(filters)
	columns, rows = requested_vs_fulfilled(filters)
	rows = [r for r in rows if cint(r.get("substituted"))]
	return columns, rows


def pending_asset_requests(filters=None):
	filters = _filters(filters)
	columns = [
		{"label": _("Asset Request"), "fieldname": "name", "fieldtype": "Link", "options": "Asset Request", "width": 140},
		{"label": _("Status"), "fieldname": "status", "fieldtype": "Data", "width": 160},
		{"label": _("Workflow State"), "fieldname": "workflow_state", "fieldtype": "Data", "width": 160},
		{"label": _("Employee"), "fieldname": "employee", "fieldtype": "Link", "options": "Employee", "width": 120},
		{"label": _("Department"), "fieldname": "department", "fieldtype": "Link", "options": "Department", "width": 140},
		{"label": _("Required Date"), "fieldname": "required_date", "fieldtype": "Date", "width": 110},
		{"label": _("Company"), "fieldname": "company", "fieldtype": "Link", "options": "Company", "width": 140},
		{"label": _("Manager"), "fieldname": "manager_approver", "fieldtype": "Link", "options": "User", "width": 140},
	]
	columns.extend(report_dimension_columns())
	pending = [
		STATUS_PENDING_MANAGER,
		STATUS_PENDING_PLANNING,
		STATUS_PENDING_CEO,
		STATUS_APPROVED,
		STATUS_PARTIALLY_FULFILLED,
	]
	conds, values = _common_conds(filters, item_alias=None)
	values["pending"] = pending
	dim_select = report_dimension_select_sql(header_alias="ar", item_alias=None)
	dim_sql = (", " + ", ".join(dim_select)) if dim_select else ""
	rows = frappe.db.sql(
		f"""
		SELECT ar.name, ar.status, ar.workflow_state, ar.employee, ar.department,
			ar.required_date, ar.company, ar.manager_approver
			{dim_sql}
		FROM `tabAsset Request` ar
		WHERE ar.docstatus < 2 AND ar.status IN %(pending)s {conds}
		ORDER BY ar.required_date, ar.creation
		""",
		values,
		as_dict=True,
	)
	return columns, rows


def fulfillment_accuracy(filters=None):
	filters = _filters(filters)
	columns = [
		{"label": _("Requested Item"), "fieldname": "requested_item_code", "fieldtype": "Link", "options": "Item", "width": 160},
		{"label": _("Requested Name"), "fieldname": "requested_item_name", "fieldtype": "Data", "width": 180},
		{"label": _("Units"), "fieldname": "units", "fieldtype": "Int", "width": 80},
		{"label": _("Exact Match"), "fieldname": "exact_match", "fieldtype": "Int", "width": 110},
		{"label": _("Substituted"), "fieldname": "substituted", "fieldtype": "Int", "width": 110},
		{"label": _("Exact Match %"), "fieldname": "exact_match_pct", "fieldtype": "Percent", "width": 120},
	]
	conds, values = _common_conds(filters, item_alias="ari")
	rows = frappe.db.sql(
		f"""
		SELECT
			al.requested_item_code,
			MAX(ari.requested_item_name) AS requested_item_name,
			COUNT(*) AS units,
			SUM(CASE WHEN al.requested_item_code = al.fulfilled_item_code THEN 1 ELSE 0 END) AS exact_match,
			SUM(CASE WHEN al.requested_item_code != al.fulfilled_item_code THEN 1 ELSE 0 END) AS substituted
		FROM `tabAsset Request Allocation` al
		INNER JOIN `tabAsset Request` ar ON ar.name = al.parent
		LEFT JOIN `tabAsset Request Item` ari ON ari.name = al.asset_request_item
		WHERE ar.docstatus = 1 AND al.fulfillment_status != 'Cancelled' {conds}
		GROUP BY al.requested_item_code
		ORDER BY units DESC
		""",
		values,
		as_dict=True,
	)
	for row in rows:
		units = cint(row.units) or 1
		row.exact_match_pct = (cint(row.exact_match) / units) * 100
	return columns, rows


def _common_conds(filters, *, item_alias: str | None = "ari") -> tuple[str, dict]:
	conds = []
	values: dict = {}
	if filters.get("company"):
		conds.append("AND ar.company = %(company)s")
		values["company"] = filters.company
	if filters.get("employee"):
		conds.append("AND ar.employee = %(employee)s")
		values["employee"] = filters.employee
	if filters.get("from_date"):
		conds.append("AND ar.transaction_date >= %(from_date)s")
		values["from_date"] = filters.from_date
	if filters.get("to_date"):
		conds.append("AND ar.transaction_date <= %(to_date)s")
		values["to_date"] = filters.to_date
	dim_sql, dim_values = report_dimension_filter_sql(
		filters, header_alias="ar", item_alias=item_alias
	)
	if dim_sql:
		conds.append(dim_sql)
		values.update(dim_values)
	return " ".join(conds), values
