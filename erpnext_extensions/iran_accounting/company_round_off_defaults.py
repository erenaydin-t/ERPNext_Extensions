# Copyright (c) 2026, ERPNext Extensions contributors
"""Ensure Round Off Dimension Default child rows are validated on Company save.

Frappe does not call child Document.validate() when saving a parent with a Table
field, so duplicate / forbidden / invalid Dynamic Link checks on the child DocType
would otherwise never run from Company → Round Off Dimension Defaults.
"""

from __future__ import annotations


def validate_company_round_off_dimension_defaults(doc, method=None):
	rows = doc.get("round_off_dimension_defaults") or []
	if not rows:
		return
	for row in rows:
		row.parent_doc = doc
		row.parent = doc.name
		row.parenttype = "Company"
		row.parentfield = "round_off_dimension_defaults"
		row.validate()
