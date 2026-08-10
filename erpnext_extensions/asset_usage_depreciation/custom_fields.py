# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

from erpnext_extensions.asset_usage_depreciation.constants import (
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
		],
	}


def ensure_custom_fields() -> None:
	create_custom_fields(get_custom_fields(), update=True)
