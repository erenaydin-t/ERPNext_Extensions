# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Idempotent: provision Accounting Dimension custom fields on Asset Request doctypes."""

from erpnext_extensions.asset_usage_depreciation.services.dimension_service import (
	provision_asset_request_accounting_dimensions,
)


def execute():
	provision_asset_request_accounting_dimensions()
