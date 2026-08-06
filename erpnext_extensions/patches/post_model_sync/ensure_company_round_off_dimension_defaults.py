# Copyright (c) 2026, ERPNext Extensions contributors
"""Ensure Company Round Off Dimension Defaults table field exists (schema only)."""

from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	"""Idempotent: create Company.round_off_dimension_defaults Table field.

	Does not insert child rows, AD defaults, or fake departments.
	"""
	create_custom_fields(
		{
			"Company": [
				{
					"fieldname": "round_off_dimension_defaults",
					"label": "Round Off Dimension Defaults",
					"fieldtype": "Table",
					"options": "Round Off Dimension Default",
					"insert_after": "round_off_cost_center",
					"description": (
						"Company-owned defaults for mandatory Accounting Dimensions on "
						"IRR Round Off residual GL rows. Not used for Stock Adjustment. "
						"Do not use Accounting Dimension Detail defaults for Round Off."
					),
				}
			]
		},
		update=True,
	)
