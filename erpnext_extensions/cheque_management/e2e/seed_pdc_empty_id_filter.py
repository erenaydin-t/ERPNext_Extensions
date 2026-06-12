"""Seed dirty PDC list user setting: ID Equals \"\" for browser E2E.

bench --site development.localhost execute erpnext_extensions.cheque_management.e2e.seed_pdc_empty_id_filter.seed
"""

from __future__ import annotations

import json

import frappe
from frappe.model.utils.user_settings import get_user_settings, sync_user_settings, update_user_settings


def seed(user: str | None = None):
	target = user or "Administrator"
	frappe.set_user(target)
	raw = get_user_settings("Post Dated Cheque")
	settings = json.loads(raw or "{}")
	settings.setdefault("List", {})
	settings["List"]["filters"] = [["Post Dated Cheque", "name", "=", ""]]
	settings["last_view"] = "List"
	update_user_settings("Post Dated Cheque", settings)
	sync_user_settings()
	frappe.db.commit()
	return {"filters": settings["List"]["filters"]}


def restore_empty():
	frappe.set_user("Administrator")
	raw = get_user_settings("Post Dated Cheque")
	settings = json.loads(raw or "{}")
	settings.setdefault("List", {})
	settings["List"]["filters"] = []
	update_user_settings("Post Dated Cheque", settings)
	sync_user_settings()
	frappe.db.commit()
	return {"filters": []}


def dump():
	"""Dump __UserSettings rows for PDC (all users)."""
	frappe.connect()
	rows = frappe.db.sql(
		"""
		SELECT user, data FROM `__UserSettings` WHERE doctype = %s ORDER BY user
		""",
		("Post Dated Cheque",),
		as_dict=True,
	)
	out = []
	for row in rows:
		data = json.loads(row.data or "{}")
		out.append({"user": row.user, "List": data.get("List", {})})
	return out
