# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from erpnext_extensions.consignment_stock.custom_fields import ensure_custom_fields


def after_migrate():
	ensure_custom_fields()
