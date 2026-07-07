"""Shared bench helpers for Playwright fixture isolation (no business rules)."""

from __future__ import annotations

import frappe

from erpnext_extensions.e2e.e2e_unique import e2e_run_id, e2e_unique_tag


def e2e_commit() -> dict:
	"""Explicit commit between prep steps (short transactions)."""
	frappe.db.commit()
	return {"ok": True}


def e2e_run_context() -> dict:
	"""Attach to prep payloads so suites never share implicit state."""
	return {"run_id": e2e_run_id(), "tag": e2e_unique_tag("RUN")}


def e2e_submitted_journal_entry_for_company(company: str, *, amount: float = 1.0) -> str:
	"""Return a submitted JE for ``company`` (creates one if needed)."""
	existing = frappe.db.get_value(
		"Journal Entry",
		{"docstatus": 1, "company": company},
		"name",
		order_by="creation desc",
	)
	if existing:
		return existing

	cash = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Cash", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	bank = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0},
		"name",
		order_by="modified desc",
	)
	if not cash or not bank:
		frappe.throw(f"Need Cash and Bank GL for test JE (company={company})")

	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = frappe.utils.today()
	je.voucher_type = "Journal Entry"
	je.user_remark = e2e_unique_tag("E2E-JE")
	je.append("accounts", {"account": cash, "debit_in_account_currency": amount})
	je.append("accounts", {"account": bank, "credit_in_account_currency": amount})
	je.insert(ignore_permissions=True)
	je.submit()
	frappe.db.commit()
	return je.name
