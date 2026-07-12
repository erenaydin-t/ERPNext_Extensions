# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _

from erpnext_extensions.iran_accounting.account_explorer.permissions import (
	assert_accounts_role,
	assert_company_allowed,
	assert_feature_enabled,
	assert_saved_views_enabled,
)

FORBIDDEN_CONFIG_KEYS = frozenset(
	{
		"rows",
		"totals",
		"pagination",
		"warnings",
		"columns",
		"scoped_account_count",
		"voucher_header",
		"member_breakdown",
	}
)


def _parse_json_block(value: Any, label: str) -> dict:
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		if not value.strip():
			raise frappe.ValidationError(_("{0} is required.").format(label))
		parsed = json.loads(value)
		if not isinstance(parsed, dict):
			raise frappe.ValidationError(_("{0} must be a JSON object.").format(label))
		return parsed
	raise frappe.ValidationError(_("{0} must be a JSON object.").format(label))


def _json_field_value(value: Any) -> dict:
	if isinstance(value, dict):
		return value
	if isinstance(value, str):
		return json.loads(value) if value.strip() else {}
	return {}


def validate_saved_view_configuration(
	document_scope: Any,
	analysis_context: Any,
	presentation: Any,
) -> None:
	document_scope = _parse_json_block(document_scope, "Document Scope")
	analysis_context = _parse_json_block(analysis_context, "Analysis Context")
	presentation = _parse_json_block(presentation, "Presentation")

	for label, block in (
		("Document Scope", document_scope),
		("Analysis Context", analysis_context),
		("Presentation", presentation),
	):
		forbidden = FORBIDDEN_CONFIG_KEYS.intersection(block.keys())
		if forbidden:
			raise frappe.ValidationError(
				_("{0} must not contain calculated data: {1}").format(label, ", ".join(sorted(forbidden)))
			)

	if not document_scope.get("company"):
		raise frappe.ValidationError(_("Document Scope company is required."))


def _assert_saved_view_owner(doc) -> None:
	if frappe.session.user == "Administrator":
		return
	if doc.owner != frappe.session.user:
		raise frappe.PermissionError(_("You can only access your own saved views."))


def list_saved_views(company: str | None = None) -> list[dict]:
	assert_accounts_role()
	assert_feature_enabled()
	assert_saved_views_enabled()

	filters: dict[str, Any] = {"owner": frappe.session.user}
	if company:
		filters["company"] = company

	rows = frappe.get_all(
		"Account Explorer Saved View",
		filters=filters,
		fields=["name", "view_name", "company", "modified", "owner"],
		order_by="modified desc",
	)
	return rows


def get_saved_view(name: str) -> dict:
	assert_accounts_role()
	assert_feature_enabled()
	assert_saved_views_enabled()

	doc = frappe.get_doc("Account Explorer Saved View", name)
	if not frappe.has_permission("Account Explorer Saved View", "read", doc):
		frappe.throw(_("Not permitted to read saved view {0}.").format(name), frappe.PermissionError)
	_assert_saved_view_owner(doc)

	return {
		"name": doc.name,
		"view_name": doc.view_name,
		"company": doc.company,
		"document_scope": _json_field_value(doc.document_scope),
		"analysis_context": _json_field_value(doc.analysis_context),
		"presentation": _json_field_value(doc.presentation),
		"modified": str(doc.modified),
	}


def save_saved_view(payload: Any) -> dict:
	assert_accounts_role()
	assert_feature_enabled()
	assert_saved_views_enabled()

	data = frappe.parse_json(payload) if isinstance(payload, str) else (payload or {})
	view_name = (data.get("view_name") or "").strip()
	if not view_name:
		raise frappe.ValidationError(_("View name is required."))

	company = data.get("company")
	if not company:
		raise frappe.ValidationError(_("Company is required."))
	assert_company_allowed(company)

	document_scope = data.get("document_scope")
	analysis_context = data.get("analysis_context")
	presentation = data.get("presentation")
	validate_saved_view_configuration(document_scope, analysis_context, presentation)

	if document_scope.get("company") != company:
		raise frappe.ValidationError(_("Document Scope company must match the saved view company."))

	existing = frappe.db.get_value(
		"Account Explorer Saved View",
		{"owner": frappe.session.user, "view_name": view_name, "company": company},
		"name",
	)
	if existing:
		doc = frappe.get_doc("Account Explorer Saved View", existing)
		_assert_saved_view_owner(doc)
		if not frappe.has_permission("Account Explorer Saved View", "write", doc):
			frappe.throw(_("Not permitted to update saved view {0}.").format(view_name), frappe.PermissionError)
	else:
		if not frappe.has_permission("Account Explorer Saved View", "create"):
			frappe.throw(_("Not permitted to create saved views."), frappe.PermissionError)
		doc = frappe.new_doc("Account Explorer Saved View")

	doc.view_name = view_name
	doc.company = company
	doc.document_scope = document_scope
	doc.analysis_context = analysis_context
	doc.presentation = presentation
	doc.flags.ignore_permissions = False
	doc.save()

	return get_saved_view(doc.name)


def delete_saved_view(name: str) -> dict:
	assert_accounts_role()
	assert_feature_enabled()
	assert_saved_views_enabled()

	doc = frappe.get_doc("Account Explorer Saved View", name)
	_assert_saved_view_owner(doc)
	if not frappe.has_permission("Account Explorer Saved View", "delete", doc):
		frappe.throw(_("Not permitted to delete saved view {0}.").format(name), frappe.PermissionError)
	frappe.delete_doc("Account Explorer Saved View", name)
	return {"ok": True, "name": name}
