# Copyright (c) 2026, Farbod Siyahpoosh and contributors
"""API E2E: Voucher Summary party resolver + Unassigned dimension residual."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import today

from erpnext_extensions.iran_accounting.account_explorer import api
from erpnext_extensions.iran_accounting.account_explorer.constants import (
	NOT_SPECIFIED_DISPLAY_CODE,
	NOT_SPECIFIED_LABEL,
	VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX,
)
from erpnext_extensions.iran_accounting.account_explorer.voucher_summary import _party_name
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	build_payload,
	current_fiscal_year,
	enable_wave2a_analysis,
	enable_wave2b_voucher,
	require_site,
)

MARKER = "AE-PARTY-RESOLVER-E2E"


def _leaf_account(company: str, account_type: str | None = None, root_type: str | None = None) -> str | None:
	filters: dict = {"company": company, "is_group": 0}
	if account_type:
		filters["account_type"] = account_type
	if root_type:
		filters["root_type"] = root_type
	return frappe.db.get_value("Account", filters, "name", order_by="lft asc")


def _ensure_customer(company: str) -> tuple[str, str]:
	title = f"{MARKER} Customer"
	name = frappe.db.get_value("Customer", {"customer_name": title}, "name")
	if not name:
		doc = frappe.get_doc({"doctype": "Customer", "customer_name": title, "customer_type": "Company"})
		doc.flags.ignore_permissions = True
		doc.insert()
		name = doc.name
	return name, frappe.db.get_value("Customer", name, "customer_name") or title


def _ensure_supplier(company: str) -> tuple[str, str]:
	title = f"{MARKER} Supplier"
	name = frappe.db.get_value("Supplier", {"supplier_name": title}, "name")
	if not name:
		doc = frappe.get_doc({"doctype": "Supplier", "supplier_name": title})
		doc.flags.ignore_permissions = True
		doc.insert()
		name = doc.name
	return name, frappe.db.get_value("Supplier", name, "supplier_name") or title


def _ensure_employee(company: str) -> tuple[str, str]:
	title = f"{MARKER} Employee"
	name = frappe.db.get_value("Employee", {"employee_name": title, "company": company}, "name")
	if not name:
		# Prefer any existing employee to avoid HR mandatory-field churn.
		existing = frappe.db.get_value("Employee", {"company": company}, "name", order_by="creation asc")
		if existing:
			return existing, frappe.db.get_value("Employee", existing, "employee_name") or existing
		doc = frappe.get_doc(
			{
				"doctype": "Employee",
				"first_name": title,
				"employee_name": title,
				"company": company,
				"status": "Active",
				"date_of_joining": today(),
				"date_of_birth": "1990-01-01",
				"gender": "Male",
			}
		)
		doc.flags.ignore_permissions = True
		doc.insert()
		name = doc.name
	return name, frappe.db.get_value("Employee", name, "employee_name") or title


def _ensure_shareholder(company: str) -> tuple[str, str]:
	title = f"{MARKER} Shareholder"
	name = frappe.db.get_value("Shareholder", {"title": title, "company": company}, "name")
	if not name:
		doc = frappe.get_doc({"doctype": "Shareholder", "title": title, "company": company})
		doc.flags.ignore_permissions = True
		doc.insert()
		name = doc.name
	return name, frappe.db.get_value("Shareholder", name, "title") or title


def _submit_party_je(
	company: str,
	posting_date: str,
	marker: str,
	*,
	party_account: str,
	cash_account: str,
	party_type: str,
	party: str,
	cost_center: str | None,
) -> str:
	existing = frappe.db.get_value(
		"Journal Entry",
		{"company": company, "user_remark": f"{MARKER}-{marker}", "docstatus": 1},
		"name",
	)
	if existing:
		return existing

	amount = 1000.0
	debit_row = {
		"account": party_account,
		"debit_in_account_currency": amount,
		"debit": amount,
		"credit_in_account_currency": 0,
		"credit": 0,
		"party_type": party_type,
		"party": party,
	}
	credit_row = {
		"account": cash_account,
		"debit_in_account_currency": 0,
		"debit": 0,
		"credit_in_account_currency": amount,
		"credit": amount,
	}
	if cost_center:
		debit_row["cost_center"] = cost_center
		credit_row["cost_center"] = cost_center

	je = frappe.new_doc("Journal Entry")
	je.voucher_type = "Journal Entry"
	je.company = company
	je.posting_date = posting_date
	je.user_remark = f"{MARKER}-{marker}"
	je.title = marker
	je.append("accounts", debit_row)
	je.append("accounts", credit_row)
	je.flags.ignore_permissions = True
	try:
		je.insert()
		je.submit()
	except Exception:
		# Some party/account combinations reject party on insert — stamp GL after submit without party.
		frappe.db.rollback()
		je = frappe.new_doc("Journal Entry")
		je.voucher_type = "Journal Entry"
		je.company = company
		je.posting_date = posting_date
		je.user_remark = f"{MARKER}-{marker}"
		je.title = marker
		for row in (debit_row, credit_row):
			clean = {k: v for k, v in row.items() if k not in ("party_type", "party")}
			je.append("accounts", clean)
		je.flags.ignore_permissions = True
		je.insert()
		je.submit()
		for gle in frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Journal Entry",
				"voucher_no": je.name,
				"account": party_account,
				"is_cancelled": 0,
			},
			pluck="name",
		):
			frappe.db.set_value(
				"GL Entry",
				gle,
				{"party_type": party_type, "party": party},
				update_modified=False,
			)
	frappe.db.commit()
	return je.name


class TestAccountExplorerVoucherSummaryPartyE2E(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		if not frappe.db:
			raise unittest.SkipTest("Database not available")
		company = "_Test Company"
		if not frappe.db.exists("Company", company):
			raise unittest.SkipTest("ERPNext _Test Company not available")
		cls.company = company
		enable_wave2b_voucher()
		fy = current_fiscal_year(cls.company)
		if not fy:
			raise unittest.SkipTest("No fiscal year")
		cls.fiscal_year, cls.from_date, cls.to_date = fy
		cls.posting_date = cls.to_date
		cls.cash = _leaf_account(cls.company, account_type="Cash") or _leaf_account(
			cls.company, root_type="Asset"
		)
		cls.receivable = _leaf_account(cls.company, account_type="Receivable")
		cls.payable = _leaf_account(cls.company, account_type="Payable")
		cls.equity = _leaf_account(cls.company, account_type="Equity") or _leaf_account(
			cls.company, root_type="Equity"
		)
		cls.cost_center = frappe.db.get_value("Cost Center", {"company": cls.company, "is_group": 0}, "name")
		if not cls.cash or not cls.receivable or not cls.payable:
			raise unittest.SkipTest("Missing cash/receivable/payable accounts")

		_party_name._cache = {}
		cls.customer, cls.customer_title = _ensure_customer(cls.company)
		cls.supplier, cls.supplier_title = _ensure_supplier(cls.company)
		cls.employee, cls.employee_title = _ensure_employee(cls.company)
		cls.shareholder, cls.shareholder_title = _ensure_shareholder(cls.company)

		cls.vouchers = {
			"Customer": _submit_party_je(
				cls.company,
				cls.posting_date,
				"customer",
				party_account=cls.receivable,
				cash_account=cls.cash,
				party_type="Customer",
				party=cls.customer,
				cost_center=cls.cost_center,
			),
			"Supplier": _submit_party_je(
				cls.company,
				cls.posting_date,
				"supplier",
				party_account=cls.payable,
				cash_account=cls.cash,
				party_type="Supplier",
				party=cls.supplier,
				cost_center=cls.cost_center,
			),
			"Employee": _submit_party_je(
				cls.company,
				cls.posting_date,
				"employee",
				party_account=cls.payable,
				cash_account=cls.cash,
				party_type="Employee",
				party=cls.employee,
				cost_center=cls.cost_center,
			),
			"Shareholder": _submit_party_je(
				cls.company,
				cls.posting_date,
				"shareholder",
				party_account=cls.equity or cls.receivable,
				cash_account=cls.cash,
				party_type="Shareholder",
				party=cls.shareholder,
				cost_center=cls.cost_center,
			),
		}
		frappe.db.commit()

	def setUp(self):
		_party_name._cache = {}
		frappe.set_user("Administrator")

	def test_voucher_summary_all_party_types_no_server_error(self):
		settings = frappe.get_single("Iran Accounting Settings")
		prev_page = settings.server_page_size
		settings.server_page_size = 500
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		try:
			payload = build_payload(
				self.company,
				self.fiscal_year,
				self.from_date,
				self.to_date,
				analysis={
					"view_axis": "voucher",
					"page_size": 500,
					"page": 1,
					"sort_field": "posting_date",
				},
				document={
					"hide_zero_rows": 0,
					"status": {"include_opening_entries": 1},
					"from_date": self.posting_date,
					"to_date": self.posting_date,
				},
			)
			# Must not raise OperationalError for Shareholder / any party type.
			result = api.get_voucher_summary(payload)
			self.assertIn("rows", result)
			by_voucher = {(r["voucher_type"], r["voucher_no"]): r for r in result["rows"]}

			for party_type, voucher_no in self.vouchers.items():
				row = by_voucher.get(("Journal Entry", voucher_no))
				self.assertIsNotNone(row, f"missing voucher row for {party_type} {voucher_no}")
				self.assertEqual(row.get("party_type"), party_type)

			shareholder_row = by_voucher[("Journal Entry", self.vouchers["Shareholder"])]
			self.assertEqual(shareholder_row.get("party_name"), self.shareholder_title)
			self.assertNotEqual(shareholder_row.get("party_name"), "")

			customer_row = by_voucher[("Journal Entry", self.vouchers["Customer"])]
			self.assertEqual(customer_row.get("party_name"), self.customer_title)

			supplier_row = by_voucher[("Journal Entry", self.vouchers["Supplier"])]
			self.assertEqual(supplier_row.get("party_name"), self.supplier_title)

			employee_row = by_voucher[("Journal Entry", self.vouchers["Employee"])]
			self.assertEqual(employee_row.get("party_name"), self.employee_title)
		finally:
			settings = frappe.get_single("Iran Accounting Settings")
			settings.server_page_size = prev_page
			settings.flags.ignore_permissions = True
			settings.save()
			frappe.db.commit()


class TestAccountExplorerDimensionUnassignedE2E(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy

	def test_unassigned_dimension_row_is_hidden_from_grid(self):
		if not frappe.get_meta("GL Entry").has_field("cost_center"):
			self.skipTest("No cost_center")
		payload = build_payload(
			self.company,
			self.fiscal_year,
			self.from_date,
			self.to_date,
			analysis={
				"view_axis": "dimension",
				"dimension_scope": {"dimension_type": "cost_center"},
			},
			document={"hide_zero_rows": 0},
		)
		prev = frappe.local.lang
		frappe.local.lang = "en"
		try:
			result = api.get_dimension_summary(payload)
		finally:
			frappe.local.lang = prev

		# v4.6.2: empty-dimension residual is excluded from grid rows and totals.
		self.assertFalse(
			any(
				(row.get("row_key") or "").startswith(VIRTUAL_DIMENSION_UNSPECIFIED_PREFIX)
				for row in result.get("rows") or []
			),
			"empty-dimension residual row must be hidden from grid presentation",
		)
		self.assertIn("totals", result)
