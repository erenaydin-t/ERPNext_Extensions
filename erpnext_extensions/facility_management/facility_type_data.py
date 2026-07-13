# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe

DEFAULT_FACILITY_TYPES: tuple[str, ...] = (
	"وام قرض الحسنه",
	"مشارکت مدنی",
	"فروش اقساطی",
	"مرابحه",
	"سرمایه در گردش",
	"تسهیلات کوتاه‌مدت",
	"تسهیلات بلندمدت",
	"سایر",
)


def ensure_facility_type(name: str) -> str:
	"""Create Facility Type if missing; return document name (same as facility_type_name)."""
	name = (name or "").strip()
	if not name:
		return ""
	if frappe.db.exists("Facility Type", name):
		return name
	doc = frappe.new_doc("Facility Type")
	doc.facility_type_name = name
	doc.insert(ignore_permissions=True)
	return doc.name


def ensure_default_facility_types() -> list[str]:
	created = []
	for label in DEFAULT_FACILITY_TYPES:
		if not frappe.db.exists("Facility Type", label):
			ensure_facility_type(label)
			created.append(label)
	return created


def migrate_facility_type_links() -> None:
	"""Map legacy Select/Data facility_type values on Facility to Facility Type links."""
	if not frappe.db.has_column("Facility", "facility_type"):
		return
	rows = frappe.db.sql(
		"""
		SELECT DISTINCT facility_type FROM `tabFacility`
		WHERE IFNULL(facility_type, '') != ''
		""",
	)
	for (raw,) in rows:
		val = (raw or "").strip()
		if not val:
			continue
		if frappe.db.exists("Facility Type", val):
			continue
		if frappe.db.exists("Facility Type", {"facility_type_name": val}):
			continue
		ensure_facility_type(val)
	# Normalize Facility rows where name differs from facility_type_name
	for fac in frappe.get_all(
		"Facility", filters={"facility_type": ["is", "set"]}, fields=["name", "facility_type"]
	):
		val = (fac.facility_type or "").strip()
		if not val:
			continue
		if frappe.db.exists("Facility Type", val):
			continue
		match = frappe.db.get_value("Facility Type", {"facility_type_name": val}, "name")
		if match and match != val:
			frappe.db.set_value("Facility", fac.name, "facility_type", match, update_modified=False)
