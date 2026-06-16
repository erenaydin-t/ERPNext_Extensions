"""Party propagation for PM accounting (Journal Entry / Payment Entry alignment)."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document


def account_requires_mandatory_party(account: str | None) -> bool:
	"""True when ERPNext Journal Entry validation requires party on this account."""
	if not account:
		return False
	account_type = frappe.get_cached_value("Account", account, "account_type")
	return account_type in ("Receivable", "Payable")


def get_account_configured_party_type(account: str | None) -> str | None:
	"""Optional ``party_type`` on Account (custom field on some sites)."""
	if not account:
		return None
	meta = frappe.get_meta("Account")
	if not meta.has_field("party_type"):
		return None
	return (frappe.get_cached_value("Account", account, "party_type") or "").strip() or None


def resolve_clearance_employee(doc: Document | None) -> str | None:
	"""Employee on clearance, or from linked PM Holder when header field is empty."""
	if not doc:
		return None
	emp = (getattr(doc, "employee", None) or "").strip()
	if emp:
		return emp
	holder = (getattr(doc, "holder", None) or "").strip()
	if holder:
		return (frappe.db.get_value("PM Holder", holder, "employee") or "").strip() or None
	return None


def is_pm_employee_petty_cash_account(
	account: str,
	company: str,
	employee: str | None,
	*,
	holder: str | None = None,
) -> bool:
	"""Petty cash wallet on PM Holder or Employee party-account mapping for this company."""
	if not account:
		return False

	if holder:
		row = frappe.db.get_value(
			"PM Holder",
			holder,
			["employee", "company", "petty_cash_account"],
			as_dict=True,
		)
		if row and (row.petty_cash_account or "").strip() == account.strip():
			if company and row.company and row.company != company:
				return False
			return bool((row.employee or "").strip())

	if not (company and employee):
		return False

	if frappe.db.exists(
		"PM Holder",
		{
			"employee": employee,
			"company": company,
			"petty_cash_account": account,
			"is_blocked": 0,
		},
	):
		return True
	if frappe.db.exists(
		"Party Account",
		{"parenttype": "Employee", "parent": employee, "company": company, "account": account},
	):
		return True
	try:
		from erpnext.accounts.party import get_party_account

		if get_party_account("Employee", employee, company) == account:
			return True
	except Exception:
		pass
	return False


def journal_entry_party_for_petty_cash_credit(
	account: str,
	*,
	company: str,
	employee: str | None,
	holder: str | None = None,
) -> dict:
	"""Return ``party_type`` / ``party`` for the credited petty cash line when required."""
	employee = (employee or "").strip() or None
	if not employee and holder:
		employee = (frappe.db.get_value("PM Holder", holder, "employee") or "").strip() or None

	configured_party = get_account_configured_party_type(account)
	if configured_party == "Employee" and employee:
		return {"party_type": "Employee", "party": employee}

	if account_requires_mandatory_party(account):
		if not employee:
			return {}
		return {"party_type": "Employee", "party": employee}

	if is_pm_employee_petty_cash_account(account, company, employee, holder=holder):
		party_employee = employee
		if not party_employee and holder:
			party_employee = (frappe.db.get_value("PM Holder", holder, "employee") or "").strip() or None
		if party_employee:
			return {"party_type": "Employee", "party": party_employee}

	return {}


def journal_entry_party_for_supplier_line(account: str, supplier: str | None) -> dict:
	if not account or not supplier:
		return {}
	if account_requires_mandatory_party(account):
		return {"party_type": "Supplier", "party": supplier}
	return {}


def validate_petty_cash_credit_party(doc: Document, credit_line: dict) -> None:
	"""Fail fast before JE insert when employee party is required but missing."""
	petty = (credit_line.get("account") or "").strip()
	if not petty:
		return
	employee = resolve_clearance_employee(doc)
	holder = (getattr(doc, "holder", None) or "").strip() or None
	required = journal_entry_party_for_petty_cash_credit(
		petty,
		company=doc.company,
		employee=employee,
		holder=holder,
	)
	if not required:
		return
	if (credit_line.get("party_type") or "").strip() == required.get("party_type") and (
		credit_line.get("party") or ""
	).strip() == (required.get("party") or "").strip():
		return
	frappe.throw(
		_(
			"Petty cash account {0} requires Employee party on the settlement Journal Entry. "
			"Expected Employee {1}."
		).format(petty, required.get("party") or employee or "?"),
		title=_("Journal Entry party"),
	)
