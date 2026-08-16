# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from erpnext_extensions.asset_usage_depreciation.services.report_service import substituted_assets


def execute(filters=None):
	return substituted_assets(filters)
