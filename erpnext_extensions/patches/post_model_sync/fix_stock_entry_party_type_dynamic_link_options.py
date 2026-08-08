# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations


def execute():
	"""Repair Stock Entry party-type Dynamic Link controllers for Frappe v16.

	Sets ``custom_*_party_type`` Custom Field options from ``Party Type`` to ``DocType``
	via ``db.set_value`` so the patch succeeds while Stock Entry meta is still invalid.
	Does not rewrite Stock Entry document values.
	"""
	from erpnext_extensions.consignment_stock.party_type_meta import (
		repair_stock_entry_party_type_link_options,
	)

	repair_stock_entry_party_type_link_options()
	# Keep Custom Field definitions in sync after repair (options already DocType).
	from erpnext_extensions.consignment_stock.custom_fields import ensure_custom_fields
	from erpnext_extensions.consignment_stock.material_loan.custom_fields import (
		ensure_custom_fields as ensure_material_loan_custom_fields,
	)

	ensure_custom_fields()
	ensure_material_loan_custom_fields()
