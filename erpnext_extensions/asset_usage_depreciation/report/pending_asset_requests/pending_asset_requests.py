# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from erpnext_extensions.asset_usage_depreciation.services.report_service import pending_asset_requests


def execute(filters=None):
	return pending_asset_requests(filters)
