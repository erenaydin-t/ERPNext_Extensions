from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# UX-only: extra button actions in the existing "PDC Advance Payments" section on PI/SI.
	for dt in ("Purchase Invoice", "Sales Invoice"):
		# Insert the new actions right after the existing "Get Advance PDCs" button field.
		create_custom_fields(
			{
				dt: [
					{
						"fieldname": "recalculate_pdc_advance_suggestions",
						"label": "Recalculate Suggested Amounts",
						"fieldtype": "Button",
						"insert_after": "get_advance_pdcs",
						"hidden": 1,
					},
					{
						"fieldname": "clear_draft_pdc_advances",
						"label": "Clear Draft PDC Advances",
						"fieldtype": "Button",
						"insert_after": "recalculate_pdc_advance_suggestions",
						"hidden": 1,
					},
				]
			},
			update=True,
		)

