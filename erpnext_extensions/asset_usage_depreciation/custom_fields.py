# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext_extensions.asset_usage_depreciation.constants import (
	COMPANY_FIELD_AR_CEO_MIN_QTY,
	COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION,
	COMPANY_FIELD_AR_POOL_LOCATION,
	COMPANY_FIELD_AR_REQUIRE_CEO,
	COMPANY_FIELD_AR_REQUIRE_PLANNING,
	COMPANY_FIELD_REDUCED_HANDLING,
	HANDLING_ADJUST_FINAL,
	HANDLING_EXTEND,
	MODULE,
)


def get_custom_fields() -> dict:
	return {
		"Company": [
			{
				"fieldname": "custom_aud_section",
				"label": "Asset Usage Depreciation",
				"fieldtype": "Section Break",
				"insert_after": "depreciation_cost_center",
				"collapsible": 1,
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_REDUCED_HANDLING,
				"label": "Reduced Depreciation Handling",
				"fieldtype": "Select",
				"options": f"{HANDLING_EXTEND}\n{HANDLING_ADJUST_FINAL}",
				"default": HANDLING_EXTEND,
				"insert_after": "custom_aud_section",
				"description": (
					"How unrecognized depreciation from reduced usage is handled when "
					"replanning Asset Depreciation Schedules. "
					"'Adjust Final Depreciation Installment' keeps the original end date "
					"and applies the cumulative usage difference to the final installment."
				),
				"module": MODULE,
			},
			{
				"fieldname": "custom_ar_section",
				"label": "Asset Request",
				"fieldtype": "Section Break",
				"insert_after": COMPANY_FIELD_REDUCED_HANDLING,
				"collapsible": 1,
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_AR_REQUIRE_PLANNING,
				"label": "Require Planning Approval",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "custom_ar_section",
				"description": "Optional Planning Department stage on Asset Request.",
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_AR_REQUIRE_CEO,
				"label": "Require CEO Approval",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": COMPANY_FIELD_AR_REQUIRE_PLANNING,
				"description": "Optional CEO stage on Asset Request.",
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_AR_CEO_MIN_QTY,
				"label": "CEO Approval Minimum Qty",
				"fieldtype": "Int",
				"default": "0",
				"insert_after": COMPANY_FIELD_AR_REQUIRE_CEO,
				"description": (
					"When CEO approval is enabled, require CEO only if total requested qty "
					"is at least this value. 0 means always require CEO when the flag is on."
				),
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_AR_POOL_LOCATION,
				"label": "Asset Pool Location",
				"fieldtype": "Link",
				"options": "Location",
				"insert_after": COMPANY_FIELD_AR_CEO_MIN_QTY,
				"description": (
					"Only unassigned assets at this location count as available pool stock. "
					"Leave empty to accept any location with no custodian."
				),
				"module": MODULE,
			},
			{
				"fieldname": COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION,
				"label": "Default Issue Target Location",
				"fieldtype": "Link",
				"options": "Location",
				"insert_after": COMPANY_FIELD_AR_POOL_LOCATION,
				"description": "Fallback target location when issuing a pool asset to the requester.",
				"module": MODULE,
			},
		],
		"Material Request": [
			{
				"fieldname": "custom_asset_request",
				"label": "Asset Request",
				"fieldtype": "Link",
				"options": "Asset Request",
				"insert_after": "work_order",
				"read_only": 1,
				"no_copy": 1,
				"module": MODULE,
			},
			{
				"fieldname": "custom_created_from_asset_request",
				"label": "Created From Asset Request",
				"fieldtype": "Check",
				"default": "0",
				"insert_after": "custom_asset_request",
				"read_only": 1,
				"no_copy": 1,
				"module": MODULE,
			},
		],
		"Material Request Item": [
			{
				"fieldname": "custom_asset_request_item",
				"label": "Asset Request Item",
				"fieldtype": "Data",
				"insert_after": "job_card_item",
				"read_only": 1,
				"no_copy": 1,
				"module": MODULE,
			},
		],
	}


def ensure_custom_fields() -> None:
	create_custom_fields(get_custom_fields(), update=True)
