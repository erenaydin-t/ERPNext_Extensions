# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Additive Material Request dashboard link back to Asset Request."""

from __future__ import annotations

import frappe
from frappe import _


def get_data(data=None):
	data = frappe._dict(data or {})
	if not data.get("non_standard_fieldnames"):
		data.non_standard_fieldnames = {}
	data.non_standard_fieldnames["Asset Request"] = "custom_asset_request"

	if not data.get("transactions"):
		data.transactions = []

	label = _("Assets")
	for group in data.transactions:
		if _(group.get("label") or "") == label:
			items = group.setdefault("items", [])
			if "Asset Request" not in items:
				items.append("Asset Request")
			return data
	data.transactions.append({"label": label, "items": ["Asset Request"]})
	return data
