# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

from erpnext_extensions.petty_management.services.report_service import (
	get_pm_opening_advance_availability_report_data,
)


def execute(filters=None):
	return get_pm_opening_advance_availability_report_data(filters)
