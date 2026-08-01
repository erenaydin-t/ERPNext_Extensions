# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.utils import flt, now_datetime

from erpnext_extensions.consignment_stock.material_loan.constants import F_ISSUE_RATE
from erpnext_extensions.consignment_stock.material_loan.recognition_service import (
	create_recognition_journal_entry,
)
from erpnext_extensions.consignment_stock.material_loan.settlement_service import (
	create_settlement_journal_entry,
)
from erpnext_extensions.consignment_stock.tests.material_loan_helpers import (
	ensure_customer,
	ensure_material_loan_ready,
	ensure_material_loan_settings,
	ensure_material_loan_stock_entry_types,
	ensure_supplier,
	ensure_test_item,
	get_irr_company,
	make_material_loan_issue,
	make_material_loan_return,
	party_gl_balance,
	receive_stock,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory


def run():
	ensure_material_loan_ready()
	company = get_irr_company("ESPAD")
	enable_perpetual_inventory(company)
	frappe.db.set_value("Company", company, "enable_item_wise_inventory_account", 0)
	_, accounts, wh = ensure_material_loan_settings(company)
	types = ensure_material_loan_stock_entry_types()
	item = ensure_test_item(f"ML-EVID-{frappe.generate_hash(length=4)}")
	customer = ensure_customer(company)
	supplier = ensure_supplier(company)
	receive_stock(company=company, warehouse=wh, item_code=item, qty=500, rate=10000)

	evidence = {
		"generated_at": str(now_datetime()),
		"company": company,
		"accounts": accounts,
		"customer_example": {},
		"supplier_example": {},
		"ple": {},
		"cancellation": {},
		"repost": {},
		"reports": {},
	}

	# Customer full cycle
	issue = make_material_loan_issue(
		company=company,
		warehouse=wh,
		item_code=item,
		qty=100,
		party_type="Customer",
		party=customer,
		stock_entry_type=types["issue"],
	)
	rate = flt(frappe.db.get_value("Stock Entry Detail", issue.items[0].name, F_ISSUE_RATE))
	rje = frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name))
	rje.submit()
	ret = make_material_loan_return(
		company=company,
		warehouse=wh,
		item_code=item,
		qty=100,
		party_type="Customer",
		party=customer,
		stock_entry_type=types["return"],
		issue_name=issue.name,
		issue_detail=issue.items[0].name,
	)
	sje = frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret.name))
	sje.submit()
	evidence["customer_example"] = {
		"issue": issue.name,
		"recognition_je": rje.name,
		"return": ret.name,
		"settlement_je": sje.name,
		"rate": rate,
		"party_balance_after": party_gl_balance(
			accounts["customer_receivable"], "Customer", customer, company
		),
		"issue_gl": frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Stock Entry", "voucher_no": issue.name, "is_cancelled": 0},
			fields=["account", "debit", "credit"],
		),
		"recognition_gl": frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": rje.name, "is_cancelled": 0},
			fields=["account", "party_type", "party", "debit", "credit"],
		),
	}

	ple = frappe.get_all(
		"Payment Ledger Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": rje.name, "delinked": 0},
		fields=["against_voucher_type", "against_voucher_no", "account", "party"],
	)
	se_ple = frappe.get_all(
		"Payment Ledger Entry",
		filters={"against_voucher_type": "Stock Entry", "against_voucher_no": issue.name, "delinked": 0},
	)
	evidence["ple"] = {
		"recognition_ple": ple,
		"stock_entry_against_ple_count": len(se_ple),
	}

	# Supplier recognition
	s_issue = make_material_loan_issue(
		company=company,
		warehouse=wh,
		item_code=item,
		qty=10,
		party_type="Supplier",
		party=supplier,
		stock_entry_type=types["issue"],
	)
	srje = frappe.get_doc("Journal Entry", create_recognition_journal_entry(s_issue.name))
	srje.submit()
	evidence["supplier_example"] = {
		"issue": s_issue.name,
		"recognition_je": srje.name,
		"party_account": accounts["supplier_payable"],
		"account_type": frappe.db.get_value("Account", accounts["supplier_payable"], "account_type"),
		"party_balance": party_gl_balance(
			accounts["supplier_payable"], "Supplier", supplier, company
		),
	}

	# Cancellation order sample (new small cycle)
	c_issue = make_material_loan_issue(
		company=company,
		warehouse=wh,
		item_code=item,
		qty=5,
		party_type="Customer",
		party=customer,
		stock_entry_type=types["issue"],
	)
	c_rje = frappe.get_doc("Journal Entry", create_recognition_journal_entry(c_issue.name))
	c_rje.submit()
	c_ret = make_material_loan_return(
		company=company,
		warehouse=wh,
		item_code=item,
		qty=5,
		party_type="Customer",
		party=customer,
		stock_entry_type=types["return"],
		issue_name=c_issue.name,
		issue_detail=c_issue.items[0].name,
	)
	c_sje = frappe.get_doc("Journal Entry", create_settlement_journal_entry(c_ret.name))
	c_sje.submit()
	blocked_issue = False
	try:
		frappe.get_doc("Stock Entry", c_issue.name).cancel()
	except Exception:
		blocked_issue = True
	frappe.get_doc("Journal Entry", c_sje.name).cancel()
	frappe.get_doc("Stock Entry", c_ret.name).cancel()
	frappe.get_doc("Journal Entry", c_rje.name).cancel()
	frappe.get_doc("Stock Entry", c_issue.name).cancel()
	evidence["cancellation"] = {
		"blocked_issue_while_returns_exist": blocked_issue,
		"full_reverse_ok": True,
	}

	from erpnext_extensions.consignment_stock.material_loan.repost_guards import (
		validate_repost_item_valuation,
	)

	repost_blocked = False
	# Use customer full-cycle issue which has returns
	try:
		validate_repost_item_valuation(
			frappe._dict(voucher_type="Stock Entry", voucher_no=issue.name)
		)
	except Exception:
		repost_blocked = True
	evidence["repost"] = {"transaction_repost_blocked_with_returns": repost_blocked}

	from erpnext_extensions.consignment_stock.report.outstanding_material_loans.outstanding_material_loans import (
		execute as outstanding_execute,
	)
	from erpnext_extensions.consignment_stock.report.material_loan_ledger.material_loan_ledger import (
		execute as ledger_execute,
	)
	from erpnext_extensions.consignment_stock.report.material_loan_aging.material_loan_aging import (
		execute as aging_execute,
	)

	filters = {"company": company}
	evidence["reports"] = {
		"outstanding_columns": len(outstanding_execute(filters)[0]),
		"outstanding_rows": len(outstanding_execute(filters)[1]),
		"ledger_columns": len(ledger_execute(filters)[0]),
		"aging_columns": len(aging_execute(filters)[0]),
	}

	path = Path(__file__).with_name("staging_validation_3_8_1_evidence.json")
	path.write_text(json.dumps(evidence, indent=2, default=str))
	frappe.db.commit()
	return str(path)


if __name__ == "__main__":
	print(run())
