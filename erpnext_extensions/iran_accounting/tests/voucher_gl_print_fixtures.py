# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Deterministic vouchers for Enterprise Voucher GL Printing tests."""

from __future__ import annotations

import frappe
from frappe.utils import flt, getdate

from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	enable_wave2b_voucher,
)

PRINT_MARKER = "AE-VGL-PRINT"


def ensure_print_company(test_case) -> dict:
	if not frappe.db:
		test_case.skipTest("Database not available")
	company = "_Test Company"
	if not frappe.db.exists("Company", company):
		test_case.skipTest("ERPNext _Test Company not available")
	enable_wave2b_voucher()
	fy = current_fiscal_year(company)
	if not fy:
		test_case.skipTest("No fiscal year for test company")
	fiscal_year, from_date, to_date = fy
	posting_date = str(to_date)
	today = getdate()
	if getdate(from_date) <= today <= getdate(to_date):
		posting_date = str(today)
	return {
		"company": company,
		"fiscal_year": fiscal_year,
		"from_date": str(from_date),
		"to_date": str(to_date),
		"posting_date": posting_date,
		"currency": frappe.db.get_value("Company", company, "default_currency") or "INR",
		"cost_center": frappe.db.get_value(
			"Cost Center", {"company": company, "is_group": 0}, "name", order_by="lft"
		),
	}


def _leaf_accounts(company: str, need: int = 6, currency: str | None = None) -> list[str]:
	values: list = [company]
	currency_clause = ""
	if currency:
		currency_clause = " and account_currency=%s"
		values.append(currency)
	values.append(need)
	rows = frappe.db.sql(
		f"""
		select name from `tabAccount`
		where company=%s and is_group=0 and disabled=0
		  and ifnull(account_type,'') not in ('Receivable','Payable')
		  {currency_clause}
		order by lft
		limit %s
		""",
		tuple(values),
		as_dict=True,
	)
	return [row.name for row in rows]


def _receivable(company: str) -> str | None:
	return frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Receivable", "is_group": 0, "disabled": 0},
		"name",
		order_by="lft",
	)


def _payable(company: str) -> str | None:
	return frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Payable", "is_group": 0, "disabled": 0},
		"name",
		order_by="lft",
	)


def cancel_print_fixture_jes(company: str) -> None:
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{PRINT_MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()


def ensure_print_dataset(ctx: dict) -> dict:
	"""Create multi-line JE (multi debit/credit, optional party, dimensions)."""
	company = ctx["company"]
	cancel_print_fixture_jes(company)
	accounts = _leaf_accounts(company, 6, ctx.get("currency")) or _leaf_accounts(company, 6)
	if len(accounts) < 4:
		frappe.throw("Need at least 4 non-party leaf accounts for Voucher GL Print fixtures")

	cost_center = ctx.get("cost_center")
	customer = "_Test Customer" if frappe.db.exists("Customer", "_Test Customer") else None
	supplier = "_Test Supplier" if frappe.db.exists("Supplier", "_Test Supplier") else None
	receivable = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_type": "Receivable",
			"is_group": 0,
			"disabled": 0,
			"account_currency": ctx.get("currency"),
		},
		"name",
		order_by="lft",
	) or _receivable(company)
	payable = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"account_type": "Payable",
			"is_group": 0,
			"disabled": 0,
			"account_currency": ctx.get("currency"),
		},
		"name",
		order_by="lft",
	) or _payable(company)

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = ctx["posting_date"]
	je.user_remark = f"{PRINT_MARKER}-MULTI"
	# Multiple debit / credit lines
	je.append(
		"accounts",
		{
			"account": accounts[0],
			"debit_in_account_currency": 1000,
			"debit": 1000,
			"cost_center": cost_center,
		},
	)
	je.append(
		"accounts",
		{
			"account": accounts[1],
			"debit_in_account_currency": 500,
			"debit": 500,
			"cost_center": cost_center,
		},
	)
	je.append(
		"accounts",
		{
			"account": accounts[2],
			"credit_in_account_currency": 900,
			"credit": 900,
			"cost_center": cost_center,
		},
	)
	je.append(
		"accounts",
		{
			"account": accounts[3],
			"credit_in_account_currency": 600,
			"credit": 600,
			"cost_center": cost_center,
		},
	)
	if receivable and customer:
		je.append(
			"accounts",
			{
				"account": receivable,
				"party_type": "Customer",
				"party": customer,
				"debit_in_account_currency": 200,
				"debit": 200,
				"cost_center": cost_center,
			},
		)
		je.append(
			"accounts",
			{
				"account": accounts[0],
				"credit_in_account_currency": 200,
				"credit": 200,
				"cost_center": cost_center,
			},
		)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	frappe.db.commit()

	# Opening-flagged sibling (same balances, tagged for include/exclude tests)
	opening = frappe.new_doc("Journal Entry")
	opening.voucher_type = "Journal Entry"
	opening.company = company
	opening.posting_date = ctx["posting_date"]
	opening.user_remark = f"{PRINT_MARKER}-OPENING"
	opening.is_opening = "Yes"
	opening.append(
		"accounts",
		{
			"account": accounts[0],
			"debit_in_account_currency": 50,
			"debit": 50,
			"cost_center": cost_center,
			"is_opening": "Yes",
		},
	)
	opening.append(
		"accounts",
		{
			"account": accounts[2],
			"credit_in_account_currency": 50,
			"credit": 50,
			"cost_center": cost_center,
			"is_opening": "Yes",
		},
	)
	opening.flags.ignore_permissions = True
	try:
		opening.insert()
		opening.submit()
		frappe.db.commit()
		opening_name = opening.name
	except Exception:
		frappe.db.rollback()
		opening_name = None

	return {
		**ctx,
		"accounts": accounts,
		"customer": customer,
		"supplier": supplier,
		"receivable": receivable,
		"payable": payable,
		"je_multi": je.name,
		"je_opening": opening_name,
		"expected_debit": 1700.0 if (receivable and customer) else 1500.0,
		"expected_credit": 1700.0 if (receivable and customer) else 1500.0,
	}


def direct_voucher_gl_totals(company, voucher_type, voucher_no, include_cancelled=0, include_opening=1):
	conditions = ["company=%s", "voucher_type=%s", "voucher_no=%s"]
	values = [company, voucher_type, voucher_no]
	if not include_cancelled:
		conditions.append("is_cancelled=0")
	if not include_opening:
		conditions.append("is_opening='No'")
	row = frappe.db.sql(
		f"""
		select coalesce(sum(debit),0) d, coalesce(sum(credit),0) c, count(*) n
		from `tabGL Entry`
		where {" and ".join(conditions)}
		""",
		tuple(values),
		as_dict=True,
	)[0]
	return {"debit": flt(row.d), "credit": flt(row.c), "count": int(row.n)}


HIER_MARKER = "AE-VGL-HIER"
HIER_CODES = ("12", "1201", "120123")


def _ensure_cost_centers(company: str) -> tuple[str, str]:
	existing = frappe.get_all(
		"Cost Center",
		filters={"company": company, "is_group": 0, "disabled": 0},
		pluck="name",
		order_by="lft",
		limit=2,
	)
	if len(existing) >= 2:
		return existing[0], existing[1]
	parent = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
	names = []
	for idx, label in enumerate(("AE-VGL-CC-A", "AE-VGL-CC-B"), start=1):
		name = f"{label} - {company}"
		if frappe.db.exists("Cost Center", name):
			names.append(name)
			continue
		doc = frappe.get_doc(
			{
				"doctype": "Cost Center",
				"cost_center_name": label,
				"company": company,
				"parent_cost_center": parent,
				"is_group": 0,
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		names.append(doc.name)
	frappe.db.commit()
	return names[0], names[1]


def _ensure_numbered_account_tree(company: str, currency: str) -> dict:
	"""Create 12 → 1201 → 120123 with Persian titles for hierarchy acceptance."""
	root = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": "Asset"},
		"name",
		order_by="lft",
	)
	if not root:
		frappe.throw(f"No Asset group account for {company}")

	specs = [
		("12", "دارایی جاری پایه", 1, root),
		("1201", "موجودی مواد و کالا", 1, None),
		("120123", "کنترل خرید داخلی", 0, None),
	]
	created = {}
	parent_name = root
	for code, title, is_group, forced_parent in specs:
		existing = frappe.db.get_value(
			"Account",
			{"company": company, "account_number": code},
			"name",
		)
		if existing:
			# Keep titles aligned for assertion stability.
			frappe.db.set_value(
				"Account",
				existing,
				{"account_name": title, "account_number": code},
				update_modified=False,
			)
			created[code] = existing
			parent_name = existing
			continue
		parent = forced_parent or parent_name
		doc = frappe.get_doc(
			{
				"doctype": "Account",
				"account_name": title,
				"account_number": code,
				"company": company,
				"parent_account": parent,
				"is_group": is_group,
				"account_currency": currency,
				# Empty type avoids party constraints that block Supplier on inventory-like leaves.
				"account_type": "",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		created[code] = doc.name
		parent_name = doc.name
	frappe.db.commit()
	return created


def ensure_hierarchy_business_fixture(ctx: dict) -> dict:
	"""Balanced voucher on 120123 with two parties + two cost centers + distinct remarks."""
	company = ctx["company"]
	currency = ctx.get("currency") or frappe.db.get_value("Company", company, "default_currency")
	# Cancel prior hier fixtures
	for name in frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{HIER_MARKER}%"), "docstatus": 1},
		pluck="name",
	):
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()

	accounts = _ensure_numbered_account_tree(company, currency)
	leaf = accounts["120123"]
	cc_a, cc_b = _ensure_cost_centers(company)

	# Offset / cash-like leaf for credit side
	offset = frappe.db.get_value(
		"Account",
		{
			"company": company,
			"is_group": 0,
			"disabled": 0,
			"account_currency": currency,
			"name": ("!=", leaf),
		},
		"name",
		order_by="lft",
	)
	if not offset:
		frappe.throw("Need an offset leaf account for hierarchy fixture")

	supplier_a = "_Test Supplier"
	supplier_b = "_Test Supplier 1"
	if not frappe.db.exists("Supplier", supplier_a):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": supplier_a}).insert(ignore_permissions=True)
	if not frappe.db.exists("Supplier", supplier_b):
		frappe.get_doc({"doctype": "Supplier", "supplier_name": supplier_b}).insert(ignore_permissions=True)

	payable = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Payable", "is_group": 0, "disabled": 0},
		"name",
		order_by="lft",
	)
	# Prefer posting stock expense lines on 120123 without party-type account constraints.
	# Use plain GL lines with party fields only when account type allows; otherwise party on payable.
	je = frappe.new_doc("Journal Entry")
	je.company = company
	je.posting_date = ctx["posting_date"]
	je.user_remark = f"{HIER_MARKER}-MULTI"
	# Debit 120123 / party A / CC A
	je.append(
		"accounts",
		{
			"account": leaf,
			"party_type": "Supplier",
			"party": supplier_a,
			"debit_in_account_currency": 700,
			"debit": 700,
			"cost_center": cc_a,
			"user_remark": "خرید مواد اولیه — طرف الف",
		},
	)
	# Debit 120123 / party B / CC B
	je.append(
		"accounts",
		{
			"account": leaf,
			"party_type": "Supplier",
			"party": supplier_b,
			"debit_in_account_currency": 300,
			"debit": 300,
			"cost_center": cc_b,
			"user_remark": "خرید مواد اولیه — طرف ب",
		},
	)
	# Credits to offset (no party)
	je.append(
		"accounts",
		{
			"account": offset,
			"credit_in_account_currency": 700,
			"credit": 700,
			"cost_center": cc_a,
			"user_remark": "تسویه طرف الف",
		},
	)
	je.append(
		"accounts",
		{
			"account": offset,
			"credit_in_account_currency": 300,
			"credit": 300,
			"cost_center": cc_b,
			"user_remark": "تسویه طرف ب",
		},
	)

	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	frappe.db.commit()

	# If ERPNext dropped party on non-party accounts, stamp GL rows for print-only fixture fidelity.
	# Does not change debit/credit amounts.
	gl_rows = frappe.get_all(
		"GL Entry",
		filters={"voucher_type": "Journal Entry", "voucher_no": je.name, "account": leaf},
		fields=["name", "debit", "cost_center", "remarks"],
		order_by="debit desc, name",
	)
	if gl_rows and not frappe.db.get_value("GL Entry", gl_rows[0].name, "party"):
		for row, supplier, cc, remark in (
			(gl_rows[0], supplier_a, cc_a, "خرید مواد اولیه — طرف الف"),
			(gl_rows[1] if len(gl_rows) > 1 else gl_rows[0], supplier_b, cc_b, "خرید مواد اولیه — طرف ب"),
		):
			frappe.db.set_value(
				"GL Entry",
				row.name,
				{
					"party_type": "Supplier",
					"party": supplier,
					"cost_center": cc,
					"remarks": remark,
				},
				update_modified=False,
			)
		frappe.db.commit()

	return {
		**ctx,
		"hier_accounts": accounts,
		"hier_je": je.name,
		"hier_leaf": leaf,
		"hier_cc_a": cc_a,
		"hier_cc_b": cc_b,
		"hier_supplier_a": supplier_a,
		"hier_supplier_b": supplier_b,
		"hier_payable": payable,
		"hier_expected_debit": flt(je.total_debit) or 1000.0,
		"hier_expected_credit": flt(je.total_credit) or 1000.0,
	}
