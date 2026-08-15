# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from erpnext_extensions.asset_usage_depreciation.services.report_service import requested_vs_fulfilled


def execute(filters=None):
	return requested_vs_fulfilled(filters)
