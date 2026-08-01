# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from erpnext_extensions.consignment_stock.custom_fields import ensure_custom_fields
from erpnext_extensions.consignment_stock.material_loan.custom_fields import (
	ensure_custom_fields as ensure_material_loan_custom_fields,
)


def after_migrate():
	ensure_custom_fields()
	ensure_material_loan_custom_fields()
