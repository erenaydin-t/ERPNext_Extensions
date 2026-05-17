# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Set default settlement_type on existing PM Clearance Detail rows."""

import frappe


def execute():
	if not frappe.db.has_table("tabPM Clearance Detail"):
		return
	if not frappe.db.has_column("tabPM Clearance Detail", "settlement_type"):
		return
	frappe.db.sql(
		"""
		UPDATE `tabPM Clearance Detail`
		SET settlement_type = 'Purchase Invoice'
		WHERE settlement_type IS NULL OR settlement_type = ''
		"""
	)
