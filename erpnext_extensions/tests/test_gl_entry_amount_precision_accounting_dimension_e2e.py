# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT
"""Integration test: GL Entry DECIMAL(30,9) patch + Accounting Dimension toggle without 1264.

Run from bench root::

    bench --site <site> run-tests --app erpnext_extensions \\
        --module erpnext_extensions.tests.test_gl_entry_amount_precision_accounting_dimension_e2e
"""

from __future__ import annotations

import json
import unittest
from decimal import Decimal
from unittest.mock import patch

import frappe
from erpnext.accounts.doctype.accounting_dimension.accounting_dimension import (
	make_dimension_in_accounting_doctypes,
	toggle_disabling,
)
from frappe.utils import today

from erpnext_extensions.patches.post_model_sync.expand_gl_entry_amount_precision import (
	execute as expand_gl_entry_amount_precision_execute,
)
from erpnext_extensions.patches.post_model_sync.set_gl_entry_amount_decimal_metadata import (
	execute as set_gl_entry_amount_decimal_metadata_execute,
)

GL_ENTRY_TABLE = "tabGL Entry"
TARGET_PRECISION = 30
TARGET_SCALE = 9

GL_ENTRY_AMOUNT_COLUMNS: tuple[str, ...] = (
	"transaction_exchange_rate",
	"debit_in_account_currency",
	"debit",
	"debit_in_transaction_currency",
	"credit_in_account_currency",
	"credit",
	"credit_in_transaction_currency",
	"reporting_currency_exchange_rate",
	"debit_in_reporting_currency",
	"credit_in_reporting_currency",
)

# Exceeds DECIMAL(21,9) integer capacity (12 digits); fits DECIMAL(30,9).
LARGE_ACCOUNT_CURRENCY_AMOUNT = Decimal("9999999999999.000000000")

TEST_COMPANY = "EE GL Precision Test Co"
TEST_COMPANY_ABBR = "EEGLP"
TEST_DIMENSION_LABEL = "EE GL Prec Test Dim"
TEST_BRANCH_NAME = "EE-GL-Prec-Branch"

_DIMENSION_DOCTYPE_CANDIDATES: tuple[str, ...] = (
	"Branch",
	"Sales Person",
	"Territory",
	"Employee",
	"Item Group",
)


def _is_out_of_range_decimal_error(exc: BaseException) -> bool:
	if getattr(exc, "args", None) and exc.args and exc.args[0] == 1264:
		return True
	cause = getattr(exc, "__cause__", None) or getattr(exc, "__context__", None)
	if cause and cause is not exc:
		return _is_out_of_range_decimal_error(cause)
	name = type(exc).__name__
	if name in ("DataError", "OperationalError", "InternalError"):
		msg = str(exc).lower()
		if "1264" in msg or "out of range value" in msg:
			return True
	return False


def _read_numeric_precision_scale(column: str) -> tuple[int | None, int | None]:
	db_name = frappe.db.sql("SELECT DATABASE()")[0][0]
	row = frappe.db.sql(
		"""
		SELECT NUMERIC_PRECISION, NUMERIC_SCALE
		FROM INFORMATION_SCHEMA.COLUMNS
		WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
		""",
		(db_name, GL_ENTRY_TABLE, column),
		as_dict=True,
	)
	if not row:
		return None, None
	prec = row[0].get("NUMERIC_PRECISION")
	scale = row[0].get("NUMERIC_SCALE")
	if prec is None or scale is None:
		return None, None
	return int(prec), int(scale)


def assert_gl_entry_amount_columns_decimal_30_9(test_case: unittest.TestCase) -> None:
	missing: list[str] = []
	wrong: list[str] = []
	for col in GL_ENTRY_AMOUNT_COLUMNS:
		prec, scale = _read_numeric_precision_scale(col)
		if prec is None and scale is None:
			missing.append(col)
			continue
		if prec != TARGET_PRECISION or scale != TARGET_SCALE:
			wrong.append(f"{col}=({prec},{scale})")
	if missing:
		test_case.fail(f"Missing GL Entry columns in INFORMATION_SCHEMA: {missing}")
	if wrong:
		test_case.fail(
			f"Expected DECIMAL({TARGET_PRECISION},{TARGET_SCALE}) on all amount columns; mismatches: {wrong}. "
			"If this follows frappe.db.updatedb('GL Entry'), DocType sync may be shrinking columns to decimal(21,9)."
		)


def _run_without_decimal_overflow(test_case: unittest.TestCase, label: str, fn) -> None:
	try:
		fn()
	except Exception as exc:
		if _is_out_of_range_decimal_error(exc):
			test_case.fail(f"{label} raised out-of-range DECIMAL error (1264): {exc}")
		raise


def _unused_accounting_dimension_doctype() -> str:
	used = set(frappe.get_all("Accounting Dimension", pluck="document_type") or [])
	for doctype in _DIMENSION_DOCTYPE_CANDIDATES:
		if doctype not in used:
			return doctype
	raise AssertionError(
		"Could not find an unused DocType for a test Accounting Dimension; "
		f"candidates exhausted (used: {sorted(used)})."
	)


def _ensure_link_record_for_doctype(doctype: str, *, company: str | None = None) -> None:
	if doctype == "Branch":
		if not frappe.db.exists("Branch", TEST_BRANCH_NAME):
			frappe.get_doc({"doctype": "Branch", "branch": TEST_BRANCH_NAME}).insert(ignore_permissions=True)
		return
	if doctype == "Territory":
		name = "EE-GL-Prec-Territory"
		if not frappe.db.exists("Territory", name):
			frappe.get_doc({"doctype": "Territory", "territory_name": name}).insert(ignore_permissions=True)
		return
	if doctype == "Item Group":
		name = "EE-GL-Prec-Item-Group"
		if not frappe.db.exists("Item Group", name):
			frappe.get_doc({"doctype": "Item Group", "item_group_name": name, "is_group": 0}).insert(
				ignore_permissions=True
			)
		return
	if doctype == "Sales Person":
		name = "EE-GL-Prec-Sales-Person"
		if not frappe.db.exists("Sales Person", name):
			frappe.get_doc({"doctype": "Sales Person", "sales_person_name": name}).insert(
				ignore_permissions=True
			)
		return
	if doctype == "Employee":
		name = "EE-GL-Prec-Employee"
		if not frappe.db.exists("Employee", name):
			emp = frappe.get_doc(
				{
					"doctype": "Employee",
					"first_name": "EE GL Prec",
					"employee_name": name,
					"company": company or TEST_COMPANY,
					"gender": "Male",
					"date_of_birth": "1990-01-01",
					"date_of_joining": today(),
				}
			)
			emp.insert(ignore_permissions=True)
		return
	raise AssertionError(f"No test link record helper for doctype {doctype}")


def _site_company_country_and_currency() -> tuple[str, str]:
	row = frappe.db.get_value(
		"Company",
		{},
		["country", "default_currency"],
		as_dict=True,
	)
	if not row or not row.country or not row.default_currency:
		raise AssertionError("No existing Company on site to derive country/currency for the test company")
	return row.country, row.default_currency


def _ensure_test_company() -> str:
	if frappe.db.exists("Company", TEST_COMPANY):
		return TEST_COMPANY

	country, currency = _site_company_country_and_currency()
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": TEST_COMPANY,
			"abbr": TEST_COMPANY_ABBR,
			"default_currency": currency,
			"country": country,
		}
	)
	company.insert(ignore_permissions=True)
	return company.name


def _ensure_ledger_account(company: str) -> str:
	account = frappe.db.get_value(
		"Account",
		{"company": company, "account_type": "Bank", "is_group": 0},
		"name",
	)
	if not account:
		account = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Cash", "is_group": 0},
			"name",
		)
	if not account:
		account = frappe.db.get_value("Account", {"company": company, "is_group": 0}, "name")
	if not account:
		raise AssertionError(f"No ledger account found for test company {company!r}")
	return account


def _ensure_test_accounting_dimension_fieldname(*, company: str) -> str:
	fieldname = frappe.db.get_value("Accounting Dimension", {"label": TEST_DIMENSION_LABEL}, "fieldname")
	if not fieldname:
		doctype = _unused_accounting_dimension_doctype()
		_ensure_link_record_for_doctype(doctype, company=company)
		dim = frappe.new_doc("Accounting Dimension")
		dim.label = TEST_DIMENSION_LABEL
		dim.document_type = doctype
		dim.insert(ignore_permissions=True)
		fieldname = dim.fieldname

	if not frappe.db.exists("Custom Field", {"dt": "GL Entry", "fieldname": fieldname}):
		dim_doc = frappe.get_doc("Accounting Dimension", TEST_DIMENSION_LABEL)
		make_dimension_in_accounting_doctypes(dim_doc)

	if not frappe.db.exists("Custom Field", {"dt": "GL Entry", "fieldname": fieldname}):
		raise AssertionError(f"Custom Field on GL Entry for test dimension {fieldname!r} was not created")
	return fieldname


def _insert_test_gl_entry_with_large_amount(company: str, account: str, amount: Decimal) -> str:
	voucher_no = f"EE-GL-PREC-{frappe.generate_hash(length=10)}"
	currency = frappe.get_cached_value("Company", company, "default_currency") or "USD"
	gle = frappe.new_doc("GL Entry")
	gle.flags.ignore_validate = True
	gle.flags.from_repost = True
	gle.update(
		{
			"company": company,
			"account": account,
			"voucher_type": "Journal Entry",
			"voucher_no": voucher_no,
			"posting_date": today(),
			"debit": amount,
			"credit": 0,
			"debit_in_account_currency": amount,
			"credit_in_account_currency": 0,
			"account_currency": currency,
			"transaction_exchange_rate": 1,
			"reporting_currency_exchange_rate": 1,
			"is_cancelled": 0,
		}
	)
	gle.insert(ignore_permissions=True, ignore_links=True)
	return gle.name


class TestGLEntryAmountPrecisionAccountingDimensionE2E(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def tearDown(self):
		frappe.db.rollback()
		frappe.local.request_cache.clear()

	def test_patch_then_dimension_toggle_preserves_gl_entry_decimal_30_9(self):
		if frappe.db.db_type != "mariadb":
			self.skipTest(f"GL Entry precision integration test requires MariaDB (got {frappe.db.db_type})")

		company = _ensure_test_company()
		account = _ensure_ledger_account(company)
		fieldname = _ensure_test_accounting_dimension_fieldname(company=company)

		# DDL in the DB patch cannot run inside Frappe's open test transaction (ImplicitCommitError).
		frappe.db.commit()
		set_gl_entry_amount_decimal_metadata_execute()
		frappe.clear_cache(doctype="GL Entry")
		expand_gl_entry_amount_precision_execute()
		assert_gl_entry_amount_columns_decimal_30_9(self)

		gle_name = _insert_test_gl_entry_with_large_amount(company, account, LARGE_ACCOUNT_CURRENCY_AMOUNT)

		stored_debit = frappe.db.get_value("GL Entry", gle_name, "debit_in_account_currency")
		self.assertIsNotNone(stored_debit)
		if isinstance(stored_debit, str):
			stored_debit = Decimal(stored_debit)
		self.assertGreaterEqual(stored_debit, LARGE_ACCOUNT_CURRENCY_AMOUNT)

		def _toggle_disable_enable():
			# Production toggles all accounting_dimension_doctypes; scope to GL Entry so this
			# test only exercises the schema path we fixed (not unrelated doctype updatedb).
			with patch(
				"erpnext.accounts.doctype.accounting_dimension.accounting_dimension.get_doctypes_with_dimensions",
				return_value=["GL Entry"],
			):
				toggle_disabling(doc=json.dumps({"fieldname": fieldname, "disabled": 1}))
				toggle_disabling(doc=json.dumps({"fieldname": fieldname, "disabled": 0}))

		_run_without_decimal_overflow(
			self,
			"toggle_disabling (disable then enable)",
			_toggle_disable_enable,
		)

		def _sync_gl_entry_schema():
			frappe.db.updatedb("GL Entry")

		_run_without_decimal_overflow(self, "frappe.db.updatedb('GL Entry')", _sync_gl_entry_schema)

		assert_gl_entry_amount_columns_decimal_30_9(self)
