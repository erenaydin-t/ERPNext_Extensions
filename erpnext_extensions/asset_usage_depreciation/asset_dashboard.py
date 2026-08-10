# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Additive Asset dashboard extension for Asset Usage Period Connections."""

from __future__ import annotations

import frappe
from frappe import _


def get_data(data=None):
	"""Extend the ERPNext Asset dashboard with Asset Usage Period.

	Called via ``override_doctype_dashboards`` with the existing dashboard
	``data`` from ``asset_dashboard.py`` plus DocType Link rows. Mutates
	additively — does not replace core groups.
	"""
	data = frappe._dict(data or {})

	if not data.get("non_standard_fieldnames"):
		data.non_standard_fieldnames = {}
	# Asset Usage Period links via ``asset`` (core default fieldname is asset_name)
	data.non_standard_fieldnames["Asset Usage Period"] = "asset"

	if not data.get("transactions"):
		data.transactions = []

	usage_label = _("Usage")
	for group in data.transactions:
		if _(group.get("label") or "") == usage_label:
			items = group.setdefault("items", [])
			if "Asset Usage Period" not in items:
				items.append("Asset Usage Period")
			return data

	data.transactions.append({"label": usage_label, "items": ["Asset Usage Period"]})
	return data
