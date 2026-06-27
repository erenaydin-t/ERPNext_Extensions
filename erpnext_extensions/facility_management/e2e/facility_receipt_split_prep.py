"""Prep draft Facility for receipt-split Playwright (preview + submit)."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_e2e_context import (
	apply_facility_test_accounts,
	ensure_bank_master,
)


def prepare_receipt_split_browser_facility():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc") or ensure_bank_master()
	fac = frappe.new_doc("Facility")
	fac.facility_name = f"E2E Receipt Split {random_string(4)}"
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.receive_date = today()
	fac.principal_amount = 8000
	fac.profit_amount = 1000
	apply_facility_test_accounts(fac)
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"facility": fac.name, "principal": 8000, "profit": 1000}
