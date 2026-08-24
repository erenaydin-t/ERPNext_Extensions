# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""v4.5.5: stop auto-creating fulfillment documents on Asset Request approval."""

from __future__ import annotations

import frappe

from erpnext_extensions.asset_usage_depreciation.constants import (
	FULFILLMENT_FULFILLED,
	FULFILLMENT_ISSUED_FROM_POOL,
	FULFILLMENT_PURCHASE_REQUESTED,
	FULFILLMENT_WAITING,
)


def execute():
	# Asset Request Settings is a Single: there is no `tabAsset Request Settings`.
	# Do not use table_exists/has_column here — has_column raises TableMissingError.
	if frappe.db.exists("DocType", "Asset Request Settings"):
		meta = frappe.get_meta("Asset Request Settings")
		for field in ("auto_create_material_request", "auto_create_asset_movement"):
			if meta.has_field(field):
				frappe.db.set_single_value("Asset Request Settings", field, 0)

	if not frappe.db.table_exists("Asset Request"):
		return
	if not frappe.db.has_column("Asset Request", "fulfillment_status"):
		return

	legacy_waiting = ("Not Started", "In Progress", "Waiting for fulfillment")
	for old in legacy_waiting:
		frappe.db.sql(
			"update `tabAsset Request` set fulfillment_status=%s where fulfillment_status=%s",
			(FULFILLMENT_WAITING, old),
		)

	frappe.db.sql(
		"""
		update `tabAsset Request`
		set fulfillment_status=%s
		where fulfillment_status in ('Closed', 'Fulfilled')
		""",
		(FULFILLMENT_FULFILLED,),
	)

	rows = frappe.db.sql(
		"""
		select name, material_request
		from `tabAsset Request`
		where fulfillment_status = 'Partially Fulfilled'
		""",
		as_dict=True,
	)
	for row in rows:
		has_am = False
		if frappe.db.table_exists("Asset Request Allocation"):
			has_am = bool(
				frappe.db.get_value(
					"Asset Request Allocation",
					{"parent": row.name, "asset_movement": ["!=", ""]},
					"name",
				)
			)
		if row.material_request:
			status = FULFILLMENT_PURCHASE_REQUESTED
		elif has_am:
			status = FULFILLMENT_ISSUED_FROM_POOL
		else:
			status = FULFILLMENT_WAITING
		frappe.db.set_value(
			"Asset Request", row.name, "fulfillment_status", status, update_modified=False
		)
