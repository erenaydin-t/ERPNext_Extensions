# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from erpnext_extensions.asset_usage_depreciation.services.report_service import fulfillment_accuracy


def execute(filters=None):
	return fulfillment_accuracy(filters)
