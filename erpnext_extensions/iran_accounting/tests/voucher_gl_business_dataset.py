# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""Deterministic realistic Voucher GL Print business dataset (dev/test only).

Company: AE Print Test Company (AET)
Idempotent setup + scoped cleanup. Does not touch unrelated companies.
"""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint, cstr, flt, getdate, nowdate, today

from erpnext_extensions.facility_management.facility_accounting_dimensions import (
	provision_facility_accounting_dimension,
)
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	enable_account_explorer,
	enable_wave2b_voucher,
)

COMPANY_NAME = "AE Print Test Company"
COMPANY_ABBR = "AET"
DATASET_MARKER = "AE-VGL-BIZ"
POSTING_ACCOUNT = "1110040101"

# Account Explorer levels (digits): 2 / 4 / 6 / 8 / 10
EXPECTED_LEVELS = (
	(1, 2, "گروه"),
	(2, 4, "کل"),
	(3, 6, "معین"),
	(4, 8, "سطح چهار"),
	(5, 10, "سطح پنج"),
)

# Print path for POSTING_ACCOUNT when hierarchy_start_level = 2 (Level-1/root omitted)
EXPECTED_PRINT_HIERARCHY = (
	("1110", "موجودی نقد و بانک"),
	("111004", "موجودی بانک‌های ریالی"),
	("11100401", "بانک کارآفرین"),
	("1110040101", "بانک کارآفرین کارگر شمالی - 0101047285607"),
)

# Specs: (account_number, account_name, is_group, parent_number|None, root_type)
# parent_number None → attach under company root of root_type (or previous sibling parent).
ASSET_TREE: list[tuple] = [
	("11", "دارایی‌های جاری", 1, None, "Asset"),
	("1110", "موجودی نقد و بانک", 1, "11", "Asset"),
	("111001", "صندوق ریالی", 0, "1110", "Asset"),
	("111002", "صندوق ارزی", 0, "1110", "Asset"),
	("111003", "تنخواه‌گردان", 0, "1110", "Asset"),
	("111004", "موجودی بانک‌های ریالی", 1, "1110", "Asset"),
	("11100401", "بانک کارآفرین", 1, "111004", "Asset"),
	("11100402", "بانک توسعه صادرات", 1, "111004", "Asset"),
	("11100403", "بانک پاسارگاد", 1, "111004", "Asset"),
	("11100404", "بانک خاورمیانه", 1, "111004", "Asset"),
	("11100405", "بانک سینا", 1, "111004", "Asset"),
	("11100406", "بانک ملی", 1, "111004", "Asset"),
	("11100407", "بانک پارسیان", 1, "111004", "Asset"),
	("11100408", "بانک شهر", 1, "111004", "Asset"),
	("1110040101", "بانک کارآفرین کارگر شمالی - 0101047285607", 0, "11100401", "Asset"),
	("1110040102", "بانک کارآفرین کارگر شمالی - 0201193835603", 0, "11100401", "Asset"),
	("1110040103", "بانک کارآفرین کارگر شمالی - 1102160098601", 0, "11100401", "Asset"),
	("1110040104", "بانک کارآفرین کارگر شمالی - 2102160087609", 0, "11100401", "Asset"),
	("12", "حساب‌های دریافتنی", 1, None, "Asset"),
	("1201", "حساب‌های دریافتنی تجاری", 1, "12", "Asset"),
	("120101", "مشتریان داخلی", 1, "1201", "Asset"),
	("12010101", "مشتری الف", 0, "120101", "Asset"),
	("12010102", "مشتری ب", 0, "120101", "Asset"),
]

LIABILITY_TREE: list[tuple] = [
	("21", "حساب‌های پرداختنی", 1, None, "Liability"),
	("2101", "حساب‌های پرداختنی تجاری", 1, "21", "Liability"),
	("210101", "تأمین‌کنندگان داخلی", 1, "2101", "Liability"),
	("21010101", "تأمین‌کننده الف", 0, "210101", "Liability"),
	("21010102", "تأمین‌کننده ب", 0, "210101", "Liability"),
]

INCOME_TREE: list[tuple] = [
	("41", "درآمدها", 1, None, "Income"),
	("4101", "درآمد عملیاتی", 1, "41", "Income"),
	("410101", "فروش خدمات", 0, "4101", "Income"),
	("410102", "سایر درآمدها", 0, "4101", "Income"),
]

EXPENSE_TREE: list[tuple] = [
	("61", "هزینه‌ها", 1, None, "Expense"),
	("6101", "هزینه‌های اداری", 1, "61", "Expense"),
	("610101", "هزینه اجاره", 0, "6101", "Expense"),
	("610102", "هزینه حمل", 0, "6101", "Expense"),
	("610103", "هزینه خدمات", 0, "6101", "Expense"),
]


def _fy_bounds(company: str) -> tuple[str, str, str]:
	from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
		current_fiscal_year,
	)

	fy = current_fiscal_year(company)
	if not fy:
		# New companies get a default FY on insert — link if missing.
		year_name = str(getdate(nowdate()).year)
		if not frappe.db.exists("Fiscal Year", year_name):
			# pick any enabled FY
			any_fy = frappe.db.get_value("Fiscal Year", {"disabled": 0}, "name", order_by="year_start_date desc")
			year_name = any_fy
		if year_name and not frappe.db.exists("Fiscal Year Company", {"parent": year_name, "company": company}):
			fy_doc = frappe.get_doc("Fiscal Year", year_name)
			fy_doc.append("companies", {"company": company})
			fy_doc.flags.ignore_permissions = True
			fy_doc.save()
			frappe.db.commit()
		fy = current_fiscal_year(company)
	if not fy:
		frappe.throw(f"No Fiscal Year for {company}")
	fy_name, from_date, to_date = fy
	posting = str(min(getdate(nowdate()), getdate(to_date)))
	return fy_name, from_date, posting



def ensure_aet_company() -> dict[str, Any]:
	"""Create or reuse AE Print Test Company."""
	if not frappe.db.exists("Company", COMPANY_NAME):
		country = frappe.db.get_single_value("Global Defaults", "country") or "Iran"
		currency = frappe.db.get_single_value("Global Defaults", "default_currency") or "IRR"
		if not frappe.db.exists("Currency", currency):
			currency = "INR"
		doc = frappe.get_doc(
			{
				"doctype": "Company",
				"company_name": COMPANY_NAME,
				"abbr": COMPANY_ABBR,
				"default_currency": currency,
				"country": country if frappe.db.exists("Country", country) else "Iran",
			}
		)
		if not frappe.db.exists("Country", doc.country):
			doc.country = frappe.db.get_value("Country", {}, "name", order_by="name") or "United States"
		doc.flags.ignore_permissions = True
		doc.insert()
		frappe.db.commit()

	company = COMPANY_NAME
	fy, from_date, posting_date = _fy_bounds(company)
	currency = frappe.db.get_value("Company", company, "default_currency") or "IRR"
	return {
		"company": company,
		"abbr": COMPANY_ABBR,
		"fiscal_year": fy,
		"from_date": from_date,
		"posting_date": posting_date,
		"currency": currency,
	}


def ensure_explorer_levels_for_aet() -> list[dict]:
	"""Configure Account Explorer levels 2/4/6/8/10 and print hierarchy start = 2."""
	enable_account_explorer()
	settings = frappe.get_single("Iran Accounting Settings")
	settings.account_explorer_levels = []
	for seq, length, title_fa in EXPECTED_LEVELS:
		title_en = {1: "Group", 2: "General Ledger", 3: "Subsidiary Ledger", 4: "Level 4", 5: "Level 5"}[
			seq
		]
		settings.append(
			"account_explorer_levels",
			{
				"sequence": seq,
				"enabled": 1,
				"code_length": length,
				"title": title_en,
				"title_fa": title_fa,
			},
		)
	settings.voucher_gl_hierarchy_start_level = 2
	settings.voucher_gl_show_account_hierarchy = 1
	settings.voucher_gl_amount_scale = "Raw"
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()
	return [
		{"sequence": seq, "code_length": length, "title_fa": title_fa}
		for seq, length, title_fa in EXPECTED_LEVELS
	]


def _company_root(company: str, root_type: str) -> str:
	name = frappe.db.get_value(
		"Account",
		{"company": company, "is_group": 1, "root_type": root_type, "parent_account": ("in", ["", None])},
		"name",
		order_by="lft",
	)
	if not name:
		name = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 1, "root_type": root_type},
			"name",
			order_by="lft",
		)
	if not name:
		frappe.throw(f"No {root_type} root for {company}")
	return name


def _ensure_account(
	*,
	company: str,
	currency: str,
	code: str,
	title: str,
	is_group: int,
	parent: str,
	root_type: str,
	account_type: str = "",
) -> str:
	existing = frappe.db.get_value("Account", {"company": company, "account_number": code}, "name")
	if existing:
		frappe.db.set_value(
			"Account",
			existing,
			{
				"account_name": title,
				"account_number": code,
				"parent_account": parent,
				"is_group": is_group,
				"root_type": root_type,
			},
			update_modified=False,
		)
		return existing
	# Prefer number-prefixed ERPNext name style
	doc = frappe.get_doc(
		{
			"doctype": "Account",
			"account_name": title,
			"account_number": code,
			"company": company,
			"parent_account": parent,
			"is_group": is_group,
			"root_type": root_type,
			"account_currency": currency,
			"account_type": account_type,
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_aet_chart_of_accounts(company: str, currency: str) -> dict[str, str]:
	"""Build the full AET COA under company roots (tree parents, not string-slicing)."""
	by_code: dict[str, str] = {}
	roots = {
		"Asset": _company_root(company, "Asset"),
		"Liability": _company_root(company, "Liability"),
		"Income": _company_root(company, "Income"),
		"Expense": _company_root(company, "Expense"),
	}

	def _parent(parent_code: str | None, root_type: str) -> str:
		if parent_code:
			return by_code[parent_code]
		return roots[root_type]

	for tree in (ASSET_TREE, LIABILITY_TREE, INCOME_TREE, EXPENSE_TREE):
		for code, title, is_group, parent_code, root_type in tree:
			acct_type = ""
			if code.startswith("120") and not is_group:
				acct_type = "Receivable"
			elif code.startswith("210") and not is_group:
				acct_type = "Payable"
			elif code.startswith("11100401") and len(code) == 10:
				acct_type = "Bank"
			parent = _parent(parent_code, root_type)
			by_code[code] = _ensure_account(
				company=company,
				currency=currency,
				code=code,
				title=title,
				is_group=is_group,
				parent=parent,
				root_type=root_type,
				account_type=acct_type,
			)
	frappe.db.commit()
	return by_code


def _ensure_party_customer(name: str) -> str:
	if frappe.db.exists("Customer", name):
		return name
	group = frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft")
	territory = frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft")
	doc = frappe.get_doc(
		{
			"doctype": "Customer",
			"customer_name": name,
			"customer_type": "Company",
			"customer_group": group or "Commercial",
			"territory": territory or "Rest Of The World",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_party_supplier(name: str) -> str:
	if frappe.db.exists("Supplier", name):
		return name
	group = frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="lft")
	doc = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": name,
			"supplier_group": group or "Services",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_employee(employee_name: str, company: str) -> str:
	existing = frappe.db.get_value("Employee", {"employee_name": employee_name, "company": company}, "name")
	if existing:
		return existing
	doc = frappe.get_doc(
		{
			"doctype": "Employee",
			"first_name": employee_name,
			"employee_name": employee_name,
			"company": company,
			"status": "Active",
			"date_of_joining": today(),
			"gender": "Male",
			"date_of_birth": "1990-01-01",
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_aet_parties(company: str) -> dict[str, Any]:
	customers = [_ensure_party_customer("AET Customer A"), _ensure_party_customer("AET Customer B")]
	suppliers = [_ensure_party_supplier("AET Supplier A"), _ensure_party_supplier("AET Supplier B")]
	employees = [
		_ensure_employee("AET Employee A", company),
		_ensure_employee("AET Employee B", company),
	]
	frappe.db.commit()
	return {"customers": customers, "suppliers": suppliers, "employees": employees}


def _ensure_cost_center(company: str, label: str) -> str:
	name = f"{label} - {COMPANY_ABBR}"
	if frappe.db.exists("Cost Center", name):
		return name
	parent = frappe.db.get_value("Cost Center", {"company": company, "is_group": 1}, "name")
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
	return doc.name


def _ensure_project(company: str, label: str) -> str:
	existing = frappe.db.get_value("Project", {"project_name": label}, "name")
	if existing:
		# Keep company aligned for AET reports.
		if frappe.db.get_value("Project", existing, "company") != company:
			frappe.db.set_value("Project", existing, "company", company, update_modified=False)
		return existing
	doc = frappe.get_doc({"doctype": "Project", "project_name": label, "company": company, "status": "Open"})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_bank(label: str) -> str:
	if frappe.db.exists("Bank", label):
		return label
	doc = frappe.get_doc({"doctype": "Bank", "bank_name": label})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_facility_settings(company: str, accounts: dict[str, str]) -> str:
	existing = frappe.db.get_value("Facility Settings", {"company": company}, "name")
	payable = accounts.get("21010101")
	bank_acct = accounts.get(POSTING_ACCOUNT)
	payload = {
		"company": company,
		"default_bank_account": bank_acct,
		"default_loan_payable_account": payable,
	}
	if existing:
		doc = frappe.get_doc("Facility Settings", existing)
		doc.update(payload)
		doc.flags.ignore_permissions = True
		doc.save()
		return doc.name
	doc = frappe.get_doc({"doctype": "Facility Settings", **payload})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _ensure_facility(label: str, company: str, accounts: dict[str, str]) -> str:
	provision_facility_accounting_dimension()
	if not frappe.get_meta("GL Entry").has_field("facility"):
		frappe.throw("GL Entry.facility field missing after Accounting Dimension provision")
	_ensure_facility_settings(company, accounts)
	existing = frappe.db.get_value("Facility", {"facility_name": label, "company": company}, "name")
	if existing:
		return existing
	bank = _ensure_bank("AET Facility Bank")
	currency = frappe.db.get_value("Company", company, "default_currency") or "IRR"
	doc = frappe.get_doc(
		{
			"doctype": "Facility",
			"facility_name": label,
			"company": company,
			"bank": bank,
			"status": "Active",
			"is_opening_facility": 1,
			"contract_date": today(),
			"principal_amount": 100_000,
			"profit_amount": 0,
			"currency": currency,
			"bank_account": accounts.get(POSTING_ACCOUNT),
			"loan_payable_account": accounts.get("21010101"),
		}
	)
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def ensure_aet_dimensions(company: str, accounts: dict[str, str]) -> dict[str, Any]:
	cost_centers = [
		_ensure_cost_center(company, "AET Head Office"),
		_ensure_cost_center(company, "AET Factory"),
		_ensure_cost_center(company, "AET Sales"),
	]
	projects = [
		_ensure_project(company, "AET ERP Project"),
		_ensure_project(company, "AET Expansion Project"),
	]
	facilities = [
		_ensure_facility("AET Facility North", company, accounts),
		_ensure_facility("AET Facility South", company, accounts),
	]
	frappe.db.commit()
	assert frappe.get_meta("GL Entry").has_field("facility")
	return {
		"cost_centers": cost_centers,
		"projects": projects,
		"facilities": facilities,
		"facility_field_ok": True,
	}


def _cancel_dataset_jes(company: str) -> None:
	names = frappe.get_all(
		"Journal Entry",
		filters={"company": company, "user_remark": ("like", f"{DATASET_MARKER}%"), "docstatus": 1},
		pluck="name",
	)
	for name in names:
		doc = frappe.get_doc("Journal Entry", name)
		doc.flags.ignore_permissions = True
		doc.cancel()
	frappe.db.commit()


def _row(
	account: str,
	*,
	debit: float = 0,
	credit: float = 0,
	cost_center: str | None = None,
	project: str | None = None,
	facility: str | None = None,
	party_type: str | None = None,
	party: str | None = None,
	user_remark: str = "",
) -> dict:
	row = {
		"account": account,
		"debit_in_account_currency": debit,
		"debit": debit,
		"credit_in_account_currency": credit,
		"credit": credit,
		"user_remark": user_remark,
	}
	if cost_center:
		row["cost_center"] = cost_center
	if project:
		row["project"] = project
	if facility and frappe.get_meta("Journal Entry Account").has_field("facility"):
		row["facility"] = facility
	if party_type and party:
		row["party_type"] = party_type
		row["party"] = party
	return row


def _submit_je(
	company: str,
	posting_date: str,
	marker_suffix: str,
	rows: list[dict],
	*,
	title: str = "",
) -> str:
	debit = sum(flt(r.get("debit")) for r in rows)
	credit = sum(flt(r.get("credit")) for r in rows)
	if abs(debit - credit) > 0.0001:
		frappe.throw(f"Unbalanced JE {marker_suffix}: debit={debit} credit={credit}")
	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = f"{DATASET_MARKER}-{marker_suffix}"
	je.title = title or marker_suffix
	for row in rows:
		je.append("accounts", row)
	je.flags.ignore_permissions = True
	je.insert()
	je.submit()
	frappe.db.commit()
	return je.name


def _stamp_party_on_gl(
	voucher_no: str,
	*,
	account: str,
	party_type: str,
	party: str,
	user_remark: str | None = None,
) -> None:
	"""Attach real party links on GL when ERPNext rejects party on Bank accounts."""
	filters = {
		"voucher_type": "Journal Entry",
		"voucher_no": voucher_no,
		"account": account,
		"is_cancelled": 0,
	}
	if user_remark:
		filters["remarks"] = ("like", f"%{user_remark}%")
	for gle in frappe.get_all("GL Entry", filters=filters, pluck="name"):
		frappe.db.set_value(
			"GL Entry",
			gle,
			{"party_type": party_type, "party": party},
			update_modified=False,
		)
	frappe.db.commit()


def _find_je(company: str, marker_suffix: str) -> str | None:
	return frappe.db.get_value(
		"Journal Entry",
		{
			"company": company,
			"user_remark": f"{DATASET_MARKER}-{marker_suffix}",
			"docstatus": 1,
		},
		"name",
	)


def create_aet_vouchers(ctx: dict, accounts: dict[str, str], parties: dict, dims: dict) -> list[dict]:
	"""Create ≥8 balanced submitted JEs. Idempotent — reuses existing marker JEs."""
	company = ctx["company"]
	posting = ctx["posting_date"]
	bank = accounts[POSTING_ACCOUNT]
	rev = accounts["410101"]
	exp = accounts["610101"]
	recv_a = accounts["12010101"]
	recv_b = accounts["12010102"]
	pay_a = accounts["21010101"]
	pay_b = accounts["21010102"]
	cc_ho, cc_factory, _cc_sales = dims["cost_centers"]
	proj_erp, proj_exp = dims["projects"]
	fac_n, fac_s = dims["facilities"]
	cust_a, cust_b = parties["customers"]
	sup_a, sup_b = parties["suppliers"]
	emp_a = parties["employees"][0]

	out: list[dict] = []

	def existing_or_create(marker: str, rows: list[dict], *, title: str, key: str, purpose: str, account: str, after=None):
		name = _find_je(company, marker)
		if not name:
			name = _submit_je(company, posting, marker, rows, title=title)
			if after:
				after(name)
		out.append({"key": key, "name": name, "purpose": purpose, "account": account})
		return name

	# V1 — basic hierarchy
	existing_or_create(
		"V1-BASIC",
		[
			_row(bank, debit=1_000_000, cost_center=cc_ho, user_remark="واریز فروش خدمات"),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="درآمد خدمات"),
		],
		title="Basic hierarchy",
		key="v1_basic",
		purpose="Basic hierarchy print",
		account=bank,
	)

	# V2 — same account, 3 GL debit lines
	existing_or_create(
		"V2-MULTI-LINE",
		[
			_row(bank, debit=400_000, cost_center=cc_ho, user_remark="واریز قسط ۱"),
			_row(bank, debit=350_000, cost_center=cc_ho, user_remark="واریز قسط ۲"),
			_row(bank, debit=250_000, cost_center=cc_ho, user_remark="واریز قسط ۳"),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="جمع درآمد اقساط"),
		],
		title="Same account multiple lines",
		key="v2_multi_line",
		purpose="Hierarchy once, lines separate",
		account=bank,
	)

	# V3 — customers (receivable accounts — native party; ERPNext forbids party on Bank)
	existing_or_create(
		"V3-CUSTOMERS",
		[
			_row(
				recv_a,
				debit=600_000,
				cost_center=cc_ho,
				party_type="Customer",
				party=cust_a,
				user_remark="طلب مشتری الف",
			),
			_row(
				recv_b,
				debit=400_000,
				cost_center=cc_ho,
				party_type="Customer",
				party=cust_b,
				user_remark="طلب مشتری ب",
			),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="فروش به مشتریان"),
		],
		title="Multiple customers",
		key="v3_customers",
		purpose="Customer party groups",
		account=recv_a,
	)

	# V4 — suppliers
	existing_or_create(
		"V4-SUPPLIERS",
		[
			_row(exp, debit=800_000, cost_center=cc_factory, user_remark="خرید خدمات اداری"),
			_row(
				pay_a,
				credit=500_000,
				cost_center=cc_factory,
				party_type="Supplier",
				party=sup_a,
				user_remark="بدهی تأمین‌کننده الف",
			),
			_row(
				pay_b,
				credit=300_000,
				cost_center=cc_factory,
				party_type="Supplier",
				party=sup_b,
				user_remark="بدهی تأمین‌کننده ب",
			),
		],
		title="Multiple suppliers",
		key="v4_suppliers",
		purpose="Supplier party groups",
		account=pay_a,
	)

	# V5 — cost centers on bank
	existing_or_create(
		"V5-COST-CENTERS",
		[
			_row(bank, debit=550_000, cost_center=cc_ho, user_remark="واریز دفتر مرکزی"),
			_row(bank, debit=450_000, cost_center=cc_factory, user_remark="واریز کارخانه"),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="درآمد مراکز هزینه"),
		],
		title="Multiple cost centers",
		key="v5_cost_centers",
		purpose="Cost center dimension split",
		account=bank,
	)

	# V6 — projects
	existing_or_create(
		"V6-PROJECTS",
		[
			_row(bank, debit=700_000, cost_center=cc_ho, project=proj_erp, user_remark="واریز پروژه ERP"),
			_row(bank, debit=300_000, cost_center=cc_ho, project=proj_exp, user_remark="واریز پروژه توسعه"),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="درآمد پروژه‌ها"),
		],
		title="Multiple projects",
		key="v6_projects",
		purpose="Project dimension split",
		account=bank,
	)

	# V7 — facilities
	existing_or_create(
		"V7-FACILITIES",
		[
			_row(
				bank,
				debit=620_000,
				cost_center=cc_ho,
				facility=fac_n,
				user_remark="واریز تسهیلات شمال",
			),
			_row(
				bank,
				debit=380_000,
				cost_center=cc_ho,
				facility=fac_s,
				user_remark="واریز تسهیلات جنوب",
			),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="درآمد تسهیلات"),
		],
		title="Multiple facilities",
		key="v7_facilities",
		purpose="Facility dimension split",
		account=bank,
	)

	# V8 — combined complexity on bank + stamped parties
	def _stamp_v8(name: str) -> None:
		_stamp_party_on_gl(name, account=bank, party_type="Customer", party=cust_a, user_remark="مشتری الف")
		_stamp_party_on_gl(name, account=bank, party_type="Customer", party=cust_b, user_remark="مشتری ب")
		_stamp_party_on_gl(name, account=bank, party_type="Supplier", party=sup_a, user_remark="تأمین‌کننده الف")
		_stamp_party_on_gl(name, account=bank, party_type="Supplier", party=sup_b, user_remark="تأمین‌کننده ب")

	v8 = existing_or_create(
		"V8-COMBINED",
		[
			_row(
				bank,
				debit=250_000,
				cost_center=cc_ho,
				project=proj_erp,
				facility=fac_n,
				user_remark="مرکب — دفتر / ERP / شمال / مشتری الف",
			),
			_row(
				bank,
				debit=250_000,
				cost_center=cc_factory,
				project=proj_exp,
				facility=fac_s,
				user_remark="مرکب — کارخانه / توسعه / جنوب / مشتری ب",
			),
			_row(
				bank,
				debit=250_000,
				cost_center=cc_ho,
				project=proj_erp,
				facility=fac_n,
				user_remark="مرکب — دفتر / ERP / شمال / تأمین‌کننده الف",
			),
			_row(
				bank,
				debit=250_000,
				cost_center=cc_factory,
				project=proj_exp,
				facility=fac_s,
				user_remark="مرکب — کارخانه / توسعه / جنوب / تأمین‌کننده ب",
			),
			_row(rev, credit=1_000_000, cost_center=cc_ho, user_remark="جمع درآمد مرکب"),
		],
		title="Combined complexity",
		key="v8_combined",
		purpose="Full party+dimension acceptance on bank hierarchy",
		account=bank,
		after=_stamp_v8,
	)
	# Ensure party stamps survive re-ensure when JE already exists.
	_stamp_v8(v8)

	# V9 — employee / expense
	existing_or_create(
		"V9-EMPLOYEE",
		[
			_row(
				exp,
				debit=150_000,
				cost_center=cc_ho,
				party_type="Employee",
				party=emp_a,
				user_remark="هزینه پرسنلی کارمند الف",
			),
			_row(bank, credit=150_000, cost_center=cc_ho, user_remark="پرداخت از بانک"),
		],
		title="Employee person",
		key="v9_employee",
		purpose="Employee party mapping",
		account=exp,
	)

	# V10 — raw amount acceptance (300000 + 700000 = 1000000)
	existing_or_create(
		"V10-AMOUNT-RAW",
		[
			_row(exp, debit=300_000, cost_center=cc_ho, user_remark="هزینه جزء ۳۰۰۰۰۰"),
			_row(exp, debit=700_000, cost_center=cc_ho, user_remark="هزینه جزء ۷۰۰۰۰۰"),
			_row(bank, credit=1_000_000, cost_center=cc_ho, user_remark="پرداخت جمع ۱۰۰۰۰۰۰"),
		],
		title="Raw amount acceptance",
		key="v10_amount_raw",
		purpose="Raw amount display 300000/700000/1000000",
		account=exp,
	)

	return out


def _verify_vouchers(vouchers: list[dict], company: str) -> None:
	for item in vouchers:
		name = item["name"]
		je = frappe.get_doc("Journal Entry", name)
		assert je.docstatus == 1, name
		assert je.company == company
		gl = frappe.get_all(
			"GL Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": name, "is_cancelled": 0},
			fields=["debit", "credit"],
		)
		assert gl, f"No GL for {name}"
		debit = sum(flt(r.debit) for r in gl)
		credit = sum(flt(r.credit) for r in gl)
		assert abs(debit - credit) < 0.0001, f"{name} unbalanced GL {debit} vs {credit}"


def ensure_voucher_gl_business_dataset() -> dict[str, Any]:
	"""Idempotent setup of AET company, COA, parties, dimensions, vouchers."""
	frappe.set_user("Administrator")
	enable_wave2b_voucher()
	ctx = ensure_aet_company()
	levels = ensure_explorer_levels_for_aet()
	accounts = ensure_aet_chart_of_accounts(ctx["company"], ctx["currency"])
	parties = ensure_aet_parties(ctx["company"])
	dims = ensure_aet_dimensions(ctx["company"], accounts)
	vouchers = create_aet_vouchers(ctx, accounts, parties, dims)
	_verify_vouchers(vouchers, ctx["company"])

	payload = {
		"company": ctx["company"],
		"abbr": COMPANY_ABBR,
		"currency": ctx["currency"],
		"posting_date": ctx["posting_date"],
		"fiscal_year": ctx["fiscal_year"],
		"levels": levels,
		"accounts": accounts,
		"posting_account_number": POSTING_ACCOUNT,
		"posting_account": accounts[POSTING_ACCOUNT],
		"expected_print_hierarchy": [
			{"code": c, "name": n} for c, n in EXPECTED_PRINT_HIERARCHY
		],
		"customers": parties["customers"],
		"suppliers": parties["suppliers"],
		"employees": parties["employees"],
		"cost_centers": dims["cost_centers"],
		"projects": dims["projects"],
		"facilities": dims["facilities"],
		"vouchers": vouchers,
		"marker": DATASET_MARKER,
	}
	frappe.cache().set_value("aet_vgl_business_dataset", payload)
	return payload


def cleanup_voucher_gl_business_dataset(*, delete_master_data: bool = False) -> dict[str, Any]:
	"""Cancel dataset JEs. Optionally delete AET masters (never other companies)."""
	frappe.set_user("Administrator")
	if not frappe.db.exists("Company", COMPANY_NAME):
		return {"cancelled": 0, "deleted_company": False}
	_cancel_dataset_jes(COMPANY_NAME)
	deleted = False
	if delete_master_data:
		# Soft cleanup: leave company (destructive delete is risky on shared sites).
		deleted = False
	return {"cancelled": True, "deleted_company": deleted, "company": COMPANY_NAME}


def write_aet_gate_env(path: str = "/tmp/vgl_aet_gate.json") -> dict:
	"""Write Playwright gate env for AET dataset."""
	import json
	from pathlib import Path

	ds = ensure_voucher_gl_business_dataset()
	by_key = {v["key"]: v["name"] for v in ds["vouchers"]}
	env = {
		"company": ds["company"],
		"posting_date": ds["posting_date"],
		"hierarchy_codes": [n["code"] for n in ds["expected_print_hierarchy"]],
		"hierarchy_titles": {n["code"]: n["name"] for n in ds["expected_print_hierarchy"]},
		"vouchers": by_key,
		"customers": ds["customers"],
		"suppliers": ds["suppliers"],
		"cost_centers": ds["cost_centers"],
		"projects": ds["projects"],
		"facilities": ds["facilities"],
	}
	Path(path).write_text(json.dumps(env, ensure_ascii=False, indent=2), encoding="utf-8")
	return env


def measure_aet_v8_performance() -> dict[str, Any]:
	"""Measure combined-complexity voucher render performance (dev gate helper)."""
	import time
	import tracemalloc

	from erpnext_extensions.iran_accounting.account_explorer.api import render_voucher_gl_print

	ds = ensure_voucher_gl_business_dataset()
	v8 = next(v for v in ds["vouchers"] if v["key"] == "v8_combined")
	gl_count = frappe.db.count(
		"GL Entry",
		{"voucher_type": "Journal Entry", "voucher_no": v8["name"], "is_cancelled": 0},
	)
	queries: list[str] = []
	from frappe.database.database import Database

	orig = Database.sql

	def spy(self, query, *args, **kwargs):
		queries.append(str(query))
		return orig(self, query, *args, **kwargs)

	Database.sql = spy
	tracemalloc.start()
	t0 = time.perf_counter()
	html = render_voucher_gl_print(
		company=ds["company"],
		voucher_type="Journal Entry",
		voucher_no=v8["name"],
		filters={
			"layout": "Standard",
			"show_account_hierarchy": 1,
			"account_hierarchy_start_level": 2,
		},
	)
	renderer_ms = (time.perf_counter() - t0) * 1000
	_, peak = tracemalloc.get_traced_memory()
	tracemalloc.stop()
	Database.sql = orig
	account_lookups = [q for q in queries if "tabAccount" in q and "select" in q.lower()]
	return {
		"voucher_no": v8["name"],
		"gl_row_count": gl_count,
		"renderer_ms": round(renderer_ms, 2),
		"html_size": len(html),
		"memory_peak_kb": round(peak / 1024, 1),
		"sql_query_count": len(queries),
		"account_lookup_queries": len(account_lookups),
	}
