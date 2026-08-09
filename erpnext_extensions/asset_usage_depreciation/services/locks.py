# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe


def lock_asset(asset_name: str) -> None:
	frappe.db.sql("SELECT name FROM `tabAsset` WHERE name=%s FOR UPDATE", asset_name)


def lock_ads(ads_name: str) -> None:
	frappe.db.sql(
		"SELECT name FROM `tabAsset Depreciation Schedule` WHERE name=%s FOR UPDATE",
		ads_name,
	)
