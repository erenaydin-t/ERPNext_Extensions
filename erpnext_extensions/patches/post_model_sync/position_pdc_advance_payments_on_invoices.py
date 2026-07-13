from __future__ import annotations

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields


def _best_insert_after_for_payments_tab(dt: str) -> str:
	"""Place near native Advances in Payments tab, if possible."""
	meta = frappe.get_meta(dt)
	# ERPNext standard fieldnames (vary across versions); pick the first that exists.
	for candidate in (
		"advances",  # child table (native Advance Payments)
		"get_advances",  # button in some versions
		"section_break_advances",  # section break in some versions
		"payments_section",  # generic payments section
		"payment_schedule",  # not ideal, but still Payments tab adjacent
	):
		if meta.has_field(candidate):
			return candidate
	return "name"


def execute():
	# Dedicated section + button in Payments tab.
	# Keep table (`pdc_invoice_applications`) visible in the same section.
	for dt in ("Purchase Invoice", "Sales Invoice"):
		insert_after = _best_insert_after_for_payments_tab(dt)

		create_custom_fields(
			{
				dt: [
					{
						"fieldname": "pdc_advance_payments_section",
						"label": "PDC Advance Payments",
						"fieldtype": "Section Break",
						"insert_after": insert_after,
						"collapsible": 1,
						"collapsed": 1,
					},
					{
						"fieldname": "get_advance_pdcs",
						"label": "Get Advance PDCs",
						"fieldtype": "Button",
						"insert_after": "pdc_advance_payments_section",
						"hidden": 1,
					},
					{
						"fieldname": "pdc_advance_actions_html",
						"label": " ",
						"fieldtype": "HTML",
						"insert_after": "get_advance_pdcs",
					},
					# Ensure table sits in the section. This field is created in the earlier schema patch.
					{
						"fieldname": "pdc_invoice_applications",
						"label": "PDC Advance Payments",
						"fieldtype": "Table",
						"options": "PDC Invoice Application",
						"insert_after": "pdc_advance_actions_html",
					},
				]
			},
			update=True,
		)
