"""Prep data for Cheque Leaf void Playwright E2E."""

from __future__ import annotations

import time

import frappe
from frappe.utils import now_datetime


def _provision_leaves(company: str, bank_account: str, count: int) -> list[str]:
	start = int(time.time()) % 700000 + 300000
	book = frappe.new_doc("Cheque Book")
	book.company = company
	book.bank_account = bank_account
	book.generation_mode = "prefix_plus_sequence"
	book.start_number = start
	book.end_number = start + count - 1
	book.number_width = 6
	book.insert(ignore_permissions=True)
	book.generate_leaves()
	leaves = frappe.get_all(
		"Cheque Leaf",
		filters={"cheque_book": book.name, "status": "Available"},
		pluck="name",
		order_by="sequence_no asc",
	)
	if len(leaves) < count:
		frappe.throw("Failed to provision Cheque Leaves for E2E")
	return leaves


def prepare_cheque_leaf_void_e2e():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
	if not company or not bank_account:
		frappe.throw("No Company / Bank Account for E2E")

	available_leaf, reserved_leaf, used_leaf = _provision_leaves(company, bank_account, 3)

	frappe.db.set_value(
		"Cheque Leaf",
		reserved_leaf,
		{"status": "Reserved", "reserved_on": now_datetime()},
		update_modified=False,
	)
	frappe.db.set_value(
		"Cheque Leaf",
		used_leaf,
		{"status": "Used", "used_on": now_datetime()},
		update_modified=False,
	)
	frappe.db.commit()

	return {
		"company": company,
		"bank_account": bank_account,
		"available_leaf": available_leaf,
		"reserved_leaf": reserved_leaf,
		"used_leaf": used_leaf,
	}
