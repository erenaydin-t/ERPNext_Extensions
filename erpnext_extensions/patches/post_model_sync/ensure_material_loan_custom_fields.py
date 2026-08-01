# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations


def execute():
	from erpnext_extensions.consignment_stock.material_loan.custom_fields import ensure_custom_fields

	ensure_custom_fields()
