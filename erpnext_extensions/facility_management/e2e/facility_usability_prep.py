"""Prep facility for usability / search E2E."""

from __future__ import annotations

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc


def prepare_search_facility():
	frappe.set_user("Administrator")
	company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
	settings = get_facility_settings_doc(company)
	bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
	name_part = "وام سرمایه در گردش تست سرچ"
	existing = frappe.db.get_value("Facility", {"facility_name": name_part}, "name")
	if existing:
		return {"facility": existing, "facility_name": name_part, "company": company}

	fac = frappe.new_doc("Facility")
	fac.facility_name = name_part
	fac.company = company
	fac.bank = bank
	fac.contract_date = today()
	fac.principal_amount = 50000
	fac.profit_amount = 5000
	fac.is_opening_facility = 1
	fac.status = "Active"
	for fn in (
		"default_bank_account",
		"default_loan_payable_account",
		"default_deferred_loan_interest_account",
		"default_interest_expense_account",
		"default_penalty_expense_account",
		"default_cost_center",
	):
		if settings and settings.get(fn):
			fac.set(fn.replace("default_", ""), settings.get(fn))
	fac.insert(ignore_permissions=True)
	frappe.db.commit()
	return {"facility": fac.name, "facility_name": name_part, "company": company}


def check_interest_field():
	return {"has_field": frappe.get_meta("Facility Repayment").has_field("interest_expense_account")}


def run_balance_report(company: str, facility_name: str):
	from erpnext_extensions.facility_management.report.facility_balance.facility_balance import get_data

	rows = get_data({"company": company, "facility_name": facility_name})
	return {"count": len(rows), "facilities": [r.get("facility") for r in rows[:5]]}


def run_ledger_report(company: str, facility_name: str):
	from erpnext_extensions.facility_management.report.facility_ledger.facility_ledger import execute

	_cols, data = execute(
		{
			"company": company,
			"facility_name": facility_name,
			"from_date": "2000-01-01",
			"to_date": today(),
		}
	)
	return {"count": len(data), "sample": data[0] if data else None}


def find_repayments_by_facility_name(facility_name: str):
	return frappe.get_all(
		"Facility Repayment",
		filters={"facility_name": ["like", f"%{(facility_name or '')[:20]}%"]},
		fields=["name", "facility_name", "facility"],
		limit=10,
	)


def run_e2e_reports():
	prep = prepare_search_facility()
	return {
		"prep": prep,
		"balance": run_balance_report(prep["company"], "سرمایه در گردش"),
		"ledger": run_ledger_report(prep["company"], "سرمایه در گردش"),
	}

def prepare_usability_unit_facility():
	"""Active opening facility with accounts for unit tests (no skip)."""
	return prepare_search_facility()

