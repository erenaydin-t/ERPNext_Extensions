# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Pool-asset availability for Asset Request (acquisition only)."""

from __future__ import annotations

import frappe
from frappe.utils import cint

from erpnext_extensions.asset_usage_depreciation.constants import (
	ALLOC_CANCELLED,
	ASSET_REQUEST_ALLOCATION_DOCTYPE,
	ASSET_REQUEST_SETTINGS_DOCTYPE,
	OPEN_ALLOCATION_STATUSES,
	UNAVAILABLE_ASSET_STATUSES,
	COMPANY_FIELD_AR_POOL_LOCATION,
)


def get_settings():
	if not frappe.db.exists("DocType", ASSET_REQUEST_SETTINGS_DOCTYPE):
		return frappe._dict()
	try:
		return frappe.get_single(ASSET_REQUEST_SETTINGS_DOCTYPE)
	except Exception:
		return frappe._dict()


def allow_category_substitution() -> bool:
	return bool(cint(get_settings().get("allow_category_substitution", 1)))


def get_reserved_asset_names(exclude_request: str | None = None) -> set[str]:
	"""Assets already reserved or issued on an open Asset Request Allocation."""
	filters: dict = {
		"allocated_asset": ("is", "set"),
		"fulfillment_status": ("in", list(OPEN_ALLOCATION_STATUSES)),
	}
	rows = frappe.get_all(
		ASSET_REQUEST_ALLOCATION_DOCTYPE,
		filters=filters,
		fields=["allocated_asset", "parent"],
	)
	names = set()
	for row in rows:
		if exclude_request and row.parent == exclude_request:
			continue
		if row.allocated_asset:
			names.add(row.allocated_asset)
	return names


def _item_is_fixed_asset(item_code: str) -> bool:
	return bool(cint(frappe.db.get_value("Item", item_code, "is_fixed_asset")))


def get_compatible_item_codes(
	requested_item_code: str | None,
	requested_asset_category: str | None,
	fulfilled_item_code: str | None = None,
) -> list[str]:
	"""Items that may fulfill a requested need.

	Priority: explicit fulfilled item, else same category (if substitution allowed),
	else exact requested item.
	"""
	if fulfilled_item_code:
		return [fulfilled_item_code]

	if requested_item_code and not allow_category_substitution():
		return [requested_item_code]

	category = requested_asset_category
	if not category and requested_item_code:
		category = frappe.db.get_value("Item", requested_item_code, "asset_category")

	if category and allow_category_substitution():
		items = frappe.get_all(
			"Item",
			filters={
				"asset_category": category,
				"is_fixed_asset": 1,
				"disabled": 0,
				"is_grouped_asset": 0,
			},
			pluck="name",
		)
		if items:
			return items

	if requested_item_code:
		return [requested_item_code]
	return []


def get_available_assets(
	company: str,
	requested_item_code: str | None = None,
	requested_asset_category: str | None = None,
	fulfilled_item_code: str | None = None,
	exclude_request: str | None = None,
	limit: int | None = None,
) -> list[dict]:
	"""Return unassigned pool assets compatible with the requested need."""
	item_codes = get_compatible_item_codes(
		requested_item_code, requested_asset_category, fulfilled_item_code
	)
	if not item_codes or not company:
		return []

	reserved = get_reserved_asset_names(exclude_request=exclude_request)
	pool_location = frappe.db.get_value("Company", company, COMPANY_FIELD_AR_POOL_LOCATION)

	filters: dict = {
		"company": company,
		"docstatus": 1,
		"item_code": ("in", item_codes),
		"status": ("not in", list(UNAVAILABLE_ASSET_STATUSES)),
	}
	if pool_location:
		filters["location"] = pool_location

	assets = frappe.get_all(
		"Asset",
		filters=filters,
		fields=["name", "item_code", "asset_name", "asset_category", "location", "status", "creation", "custodian"],
		order_by="creation asc",
		limit_page_length=0,
	)
	available = [a for a in assets if a.name not in reserved and not (a.custodian or "").strip()]
	if limit:
		return available[:limit]
	return available


def get_available_asset_count(
	company: str,
	requested_item_code: str | None = None,
	requested_asset_category: str | None = None,
	fulfilled_item_code: str | None = None,
	exclude_request: str | None = None,
) -> int:
	return len(
		get_available_assets(
			company,
			requested_item_code=requested_item_code,
			requested_asset_category=requested_asset_category,
			fulfilled_item_code=fulfilled_item_code,
			exclude_request=exclude_request,
		)
	)
