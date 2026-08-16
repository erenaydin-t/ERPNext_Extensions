# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from frappe import _


def get_data():
	return {
		"fieldname": "name",
		"non_standard_fieldnames": {
			"Asset Movement": "reference_name",
			"Material Request": "custom_asset_request",
		},
		"internal_links": {
			"Asset": ["allocations", "allocated_asset"],
			"Purchase Receipt": ["allocations", "purchase_receipt"],
			"Purchase Order": ["allocations", "purchase_order"],
		},
		"transactions": [
			{"label": _("Fulfillment"), "items": ["Asset Movement", "Material Request", "Asset"]},
			{"label": _("Purchase"), "items": ["Purchase Order", "Purchase Receipt"]},
		],
	}
