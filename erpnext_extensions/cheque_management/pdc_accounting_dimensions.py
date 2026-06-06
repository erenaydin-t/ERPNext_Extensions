# Copyright (c) 2026, ERPNext Extensions contributors
# For license information, please see license.txt

"""Accounting Dimension provisioning for Post Dated Cheque."""

from __future__ import annotations

import frappe


def after_migrate() -> None:
	"""Idempotent: ensure active Accounting Dimensions have Custom Fields on PDC."""
	provision_post_dated_cheque_accounting_dimensions()


def provision_post_dated_cheque_accounting_dimensions() -> None:
	"""Create missing dimension Custom Fields on Post Dated Cheque only (safe to re-run)."""
	if not frappe.db.exists("DocType", "Post Dated Cheque"):
		return
	if not frappe.db.exists("DocType", "Accounting Dimension"):
		return

	from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
		make_dimension_in_accounting_doctypes,
	)

	meta = frappe.get_meta("Post Dated Cheque", cached=False)
	existing = {f.fieldname for f in meta.get("fields")}

	for row in frappe.get_all("Accounting Dimension", filters={"disabled": 0}, pluck="name"):
		doc = frappe.get_doc("Accounting Dimension", row)
		fieldname = (doc.fieldname or "").strip()
		if fieldname and fieldname in existing:
			continue
		try:
			make_dimension_in_accounting_doctypes(doc, doclist=["Post Dated Cheque"])
		except Exception:
			frappe.log_error(
				title="PDC accounting dimension provisioning skipped",
				message=frappe.get_traceback(),
			)

	frappe.clear_cache(doctype="Post Dated Cheque")
	sync_pdc_accounting_dimension_fields_allow_on_submit()


def sync_pdc_accounting_dimension_fields_allow_on_submit() -> None:
	"""Ensure dimension fields on PDC stay editable after submit (templates for future JEs)."""
	if not frappe.db.exists("DocType", "Post Dated Cheque"):
		return
	try:
		from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
			get_accounting_dimensions,
		)
	except Exception:
		def get_accounting_dimensions():
			return []

	fieldnames = set(get_accounting_dimensions() or [])
	fieldnames.update({"project", "cost_center"})
	for fieldname in fieldnames:
		if not fieldname:
			continue
		cf_name = frappe.db.get_value(
			"Custom Field", {"dt": "Post Dated Cheque", "fieldname": fieldname}, "name"
		)
		if cf_name and not frappe.db.get_value("Custom Field", cf_name, "allow_on_submit"):
			frappe.db.set_value("Custom Field", cf_name, "allow_on_submit", 1, update_modified=False)

	frappe.clear_cache(doctype="Post Dated Cheque")
