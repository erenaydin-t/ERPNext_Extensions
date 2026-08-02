# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Allow issuing registered alternative items against a Material Request.

Upstream ERPNext scopes the Item Alternative feature to manufacturing
(BOM / Work Order / subcontracting). ``StockEntry.validate_with_material_request``
hard-rejects any row whose ``item_code`` differs from the linked Material
Request row (``MappingMismatchError``), so a warehouse cannot issue a defined
alternative while keeping the Material Request link — losing traceability and
automatic ``per_ordered`` / status updates.

This patch relaxes that single check. A differing item is accepted only when:

- the row's ``original_item`` equals the requested item, and
- an Item Alternative record registers the substitution
  (directly, or in reverse with ``two_way`` enabled).

Everything else is untouched: transit handling and the strict throw for
unregistered mismatches are preserved verbatim from upstream v16, and Material
Request fulfilment already aggregates by ``material_request_item`` without
comparing item codes, so ``per_ordered`` and status transitions keep working.
"""

from __future__ import annotations

import frappe
from frappe import _


def apply_patch() -> None:
	from erpnext.stock.doctype.stock_entry.stock_entry import StockEntry

	if getattr(StockEntry, "_mr_alternative_item_patched", None):
		# Idempotent: apply_monkey_patches may run on every request.
		return

	StockEntry.validate_with_material_request = validate_with_material_request
	StockEntry._mr_alternative_item_patched = True


def is_registered_alternative(item_code: str, requested_item_code: str) -> bool:
	"""True when Item Alternative registers ``item_code`` as a substitute of
	``requested_item_code`` (directly, or reverse with two_way)."""
	if frappe.db.exists(
		"Item Alternative",
		{"item_code": requested_item_code, "alternative_item_code": item_code},
	):
		return True

	return bool(
		frappe.db.exists(
			"Item Alternative",
			{"item_code": item_code, "alternative_item_code": requested_item_code, "two_way": 1},
		)
	)


def validate_with_material_request(self):
	"""Upstream ERPNext v16 logic plus the registered-alternative exemption."""
	for item in self.get("items"):
		material_request = item.material_request or None
		material_request_item = item.material_request_item or None
		if self.purpose == "Material Transfer" and self.outgoing_stock_entry:
			parent_se = frappe.get_value(
				"Stock Entry Detail",
				item.ste_detail,
				["material_request", "material_request_item"],
				as_dict=True,
			)
			if parent_se:
				material_request = parent_se.material_request
				material_request_item = parent_se.material_request_item

		if not material_request:
			continue

		mreq_item = frappe.db.get_value(
			"Material Request Item",
			{"name": material_request_item, "parent": material_request},
			["item_code", "warehouse", "idx"],
			as_dict=True,
		)
		if mreq_item.item_code != item.item_code and not (
			item.original_item == mreq_item.item_code
			and is_registered_alternative(item.item_code, mreq_item.item_code)
		):
			frappe.throw(
				_("Item for row {0} does not match Material Request").format(item.idx),
				frappe.MappingMismatchError,
			)
