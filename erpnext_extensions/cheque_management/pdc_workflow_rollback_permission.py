"""Policy-based permission for PDC workflow rollback (PDC Settings)."""

from __future__ import annotations

import frappe

_DEFAULT_ROLES = frozenset({"System Manager"})


def get_workflow_rollback_allowed_roles(company: str | None) -> frozenset[str]:
	"""Roles allowed to rollback workflow for a company (from PDC Settings)."""
	if not company:
		return _DEFAULT_ROLES
	settings_name = frappe.db.get_value("PDC Settings", {"company": company}, "name")
	if not settings_name:
		return _DEFAULT_ROLES
	raw = frappe.db.get_value("PDC Settings", settings_name, "workflow_rollback_allowed_roles") or ""
	roles = {line.strip() for line in (raw or "").splitlines() if line.strip()}
	return frozenset(roles) if roles else _DEFAULT_ROLES


def user_has_workflow_rollback_role(company: str | None, user: str | None = None) -> bool:
	user = user or frappe.session.user
	if user == "Administrator":
		return True
	allowed = get_workflow_rollback_allowed_roles(company)
	user_roles = set(frappe.get_roles(user))
	return bool(allowed & user_roles)


def user_may_rollback_pdc(pdc_name: str | None = None, *, company: str | None = None) -> bool:
	if pdc_name and not company:
		company = frappe.db.get_value("Post Dated Cheque", pdc_name, "company")
	return user_has_workflow_rollback_role(company)
