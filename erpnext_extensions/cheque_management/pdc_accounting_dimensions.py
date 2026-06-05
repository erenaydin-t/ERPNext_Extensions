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
