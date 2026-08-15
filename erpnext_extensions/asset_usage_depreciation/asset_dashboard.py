# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Additive Asset dashboard extension for Usage Period and Asset Request."""

from __future__ import annotations

import frappe
from frappe import _


def get_data(data=None):
	"""Extend the ERPNext Asset dashboard additively — does not replace core groups."""
	data = frappe._dict(data or {})

	if not data.get("non_standard_fieldnames"):
		data.non_standard_fieldnames = {}
	data.non_standard_fieldnames["Asset Usage Period"] = "asset"

	if not data.get("internal_links"):
		data.internal_links = {}
	data.internal_links["Asset Request"] = ["allocations", "allocated_asset"]

	if not data.get("transactions"):
		data.transactions = []

	_append_group(data, _("Usage"), "Asset Usage Period")
	_append_group(data, _("Request"), "Asset Request")
	return data


def _append_group(data, label: str, item: str) -> None:
	for group in data.transactions:
		if _(group.get("label") or "") == label:
			items = group.setdefault("items", [])
			if item not in items:
				items.append(item)
			return
	data.transactions.append({"label": label, "items": [item]})
