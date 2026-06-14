"""Set funding_source_type on existing PM Clearance Request Allocation rows."""

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.has_column("PM Clearance Request Allocation", "funding_source_type"):
		return
	frappe.db.sql(
		"""
		update `tabPM Clearance Request Allocation`
		set funding_source_type = 'PM Request'
		where ifnull(funding_source_type, '') = ''
			and ifnull(pm_request, '') != ''
		"""
	)
