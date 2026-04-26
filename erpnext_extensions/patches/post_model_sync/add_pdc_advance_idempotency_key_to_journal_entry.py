from __future__ import annotations

from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def execute():
	# Stores idempotency key for PDC advance application JEs:
	# apply_pdc_advance|<Invoice DocType>|<Invoice Name>
	#
	# Do NOT overload `user_remark`/`title` (max length constraints).
	create_custom_fields(
		{
			"Journal Entry": [
				{
					"fieldname": "pdc_advance_idempotency_key",
					"label": "PDC Advance Idempotency Key",
					"fieldtype": "Data",
					"read_only": 1,
					"no_copy": 1,
					"hidden": 1,
					"insert_after": "user_remark",
					"description": "Internal: idempotency key for advance PDC application/reversal JEs.",
				}
			]
		},
		update=True,
	)

