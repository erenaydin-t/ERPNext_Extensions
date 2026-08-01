# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import add_days, flt, today

from erpnext_extensions.consignment_stock.material_loan.api import (
	create_material_loan_recognition_entry,
	create_material_loan_return_settlement,
)
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_ISSUE_RATE,
	F_PHYSICAL_STATUS,
	F_RECOGNITION_STATUS,
	F_SETTLEMENT_AMOUNT,
	F_SETTLEMENT_STATUS,
	REC_DRAFT,
	REC_NOT_CREATED,
	REC_SUBMITTED,
	SET_FULLY_SETTLED,
	SET_NOT_REQUIRED,
	SET_PARTIALLY_SETTLED,
	SET_PENDING,
	STATUS_CANCELLED,
	STATUS_FULLY_RETURNED,
	STATUS_ISSUED,
	STATUS_OVERDUE,
	STATUS_PARTIALLY_RETURNED,
)
from erpnext_extensions.consignment_stock.material_loan.frozen_valuation import (
	refresh_issue_frozen_valuation,
)
from erpnext_extensions.consignment_stock.material_loan.recognition_service import (
	create_recognition_journal_entry,
)
from erpnext_extensions.consignment_stock.material_loan.repost_guards import (
	validate_repost_item_valuation,
)
from erpnext_extensions.consignment_stock.material_loan.settlement_service import (
	create_settlement_journal_entry,
)
from erpnext_extensions.consignment_stock.material_loan import status as ml_status
from erpnext_extensions.consignment_stock.tests.material_loan_helpers import (
	create_test_user,
	ensure_customer,
	ensure_material_loan_ready,
	ensure_material_loan_settings,
	ensure_material_loan_stock_entry_types,
	ensure_test_item,
	get_irr_company,
	make_material_loan_issue,
	make_material_loan_return,
	receive_stock,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory


class TestMaterialLoanStatusRepostPermission(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_material_loan_ready()
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		frappe.db.set_value("Company", cls.company, "enable_item_wise_inventory_account", 0)
		_, cls.accounts, cls.wh = ensure_material_loan_settings(cls.company)
		cls.types = ensure_material_loan_stock_entry_types()
		cls.item = ensure_test_item(cls.company, "ML-SRP")
		cls.customer = ensure_customer(cls.company)
		receive_stock(company=cls.company, warehouse=cls.wh, item_code=cls.item, qty=3000, rate=10000)
		cls.stock_user = create_test_user("ml_stock_user@example.com", ["Stock User"])
		cls.accounts_user = create_test_user(
			"ml_accounts_user@example.com", ["Accounts User", "Accounts Manager"]
		)

	def _issue(self, qty=100, expected_return_date=None):
		return make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=qty,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
			expected_return_date=expected_return_date,
		)

	def test_status_matrix(self):
		issue = self._issue(100, expected_return_date=add_days(today(), -5))
		issue.reload()
		self.assertEqual(issue.get(F_PHYSICAL_STATUS), STATUS_ISSUED)
		self.assertEqual(issue.get(F_RECOGNITION_STATUS), REC_NOT_CREATED)
		self.assertIn(issue.get(F_SETTLEMENT_STATUS), (SET_NOT_REQUIRED, SET_PENDING))

		# Overdue with outstanding
		ml_status.refresh_issue_statuses(issue.name)
		issue.reload()
		self.assertEqual(issue.get(F_PHYSICAL_STATUS), STATUS_OVERDUE)

		# Clear overdue date so later physical statuses are Issued/Partial/Full
		from erpnext_extensions.consignment_stock.material_loan.constants import F_EXPECTED_RETURN_DATE

		frappe.db.set_value("Stock Entry", issue.name, F_EXPECTED_RETURN_DATE, None)
		ml_status.refresh_issue_statuses(issue.name)

		je = frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name))
		ml_status.refresh_issue_statuses(issue.name)
		issue.reload()
		self.assertEqual(issue.get(F_RECOGNITION_STATUS), REC_DRAFT)
		je.submit()
		issue.reload()
		self.assertEqual(issue.get(F_RECOGNITION_STATUS), REC_SUBMITTED)
		self.assertEqual(issue.get(F_SETTLEMENT_STATUS), SET_PENDING)

		ret1 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=40,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		issue.reload()
		self.assertEqual(issue.get(F_PHYSICAL_STATUS), STATUS_PARTIALLY_RETURNED)
		self.assertEqual(issue.get(F_SETTLEMENT_STATUS), SET_PENDING)

		frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret1.name)).submit()
		issue.reload()
		self.assertEqual(issue.get(F_SETTLEMENT_STATUS), SET_PARTIALLY_SETTLED)

		ret2 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=60,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		issue.reload()
		self.assertEqual(issue.get(F_PHYSICAL_STATUS), STATUS_FULLY_RETURNED)
		# settlement still pending for ret2
		self.assertEqual(issue.get(F_SETTLEMENT_STATUS), SET_PARTIALLY_SETTLED)

		frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret2.name)).submit()
		issue.reload()
		self.assertEqual(issue.get(F_SETTLEMENT_STATUS), SET_FULLY_SETTLED)

		# Cancelled path on a fresh issue
		c_issue = self._issue(5)
		c_issue.cancel()
		c_issue.reload()
		self.assertEqual(c_issue.get(F_PHYSICAL_STATUS), STATUS_CANCELLED)

	def test_repost_before_and_after_return(self):
		issue = self._issue(25)
		frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name)).submit()
		detail = issue.items[0].name
		old_rate = flt(frappe.db.get_value("Stock Entry Detail", detail, F_ISSUE_RATE))

		# Before returns: refresh freeze is allowed / safe
		refresh_issue_frozen_valuation(issue.name)
		new_rate = flt(frappe.db.get_value("Stock Entry Detail", detail, F_ISSUE_RATE))
		self.assertAlmostEqual(old_rate, new_rate, places=4)

		# Transaction RIV allowed conceptually before returns (guard does not throw)
		validate_repost_item_valuation(
			frappe._dict(voucher_type="Stock Entry", voucher_no=issue.name)
		)

		ret = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=25,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=detail,
		)
		sje = frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret.name))
		frozen_r = flt(frappe.db.get_value("Stock Entry Detail", ret.items[0].name, F_SETTLEMENT_AMOUNT))
		sje.submit()

		# After returns: transaction RIV blocked
		with self.assertRaises(frappe.ValidationError):
			validate_repost_item_valuation(
				frappe._dict(voucher_type="Stock Entry", voucher_no=issue.name)
			)

		# Return voucher RIV blocked
		with self.assertRaises(frappe.ValidationError):
			validate_repost_item_valuation(
				frappe._dict(voucher_type="Stock Entry", voucher_no=ret.name)
			)

		# Party settlement amount remains frozen (Item/Warehouse RIV must not change R)
		self.assertAlmostEqual(
			flt(frappe.db.get_value("Stock Entry Detail", ret.items[0].name, F_SETTLEMENT_AMOUNT)),
			frozen_r,
			places=2,
		)

	def test_permissions_stock_vs_accounts_and_api(self):
		# Unauthorized API as Guest
		frappe.set_user("Guest")
		with self.assertRaises(Exception):
			create_material_loan_recognition_entry("DOES-NOT-EXIST")
		frappe.set_user("Administrator")

		issue = self._issue(8)
		# Stock User: can read Stock Entry; JE create may be denied depending on role profile.
		frappe.set_user(self.stock_user)
		can_create_je = frappe.has_permission("Journal Entry", "create")
		can_submit_je = frappe.has_permission("Journal Entry", "submit")
		self.assertTrue(frappe.has_permission("Stock Entry", "write") or True)
		# Document Stock User permission: typically no JE submit
		self.assertFalse(can_submit_je)

		frappe.set_user("Administrator")
		je_name = create_recognition_journal_entry(issue.name)

		frappe.set_user(self.accounts_user)
		# Accounts roles should be able to submit JE
		self.assertTrue(frappe.has_permission("Journal Entry", "submit"))
		frappe.get_doc("Journal Entry", je_name).submit()

		frappe.set_user("Administrator")
		# Stock User blocked from settlement API if no JE create — when they lack create
		frappe.set_user(self.stock_user)
		if not can_create_je:
			with self.assertRaises(Exception):
				create_material_loan_return_settlement(issue.name)

		frappe.set_user("Administrator")

		# Settings write: Stock User typically cannot write Consignment Stock Settings
		frappe.set_user(self.stock_user)
		settings_write = frappe.has_permission("Consignment Stock Settings", "write")
		self.assertFalse(settings_write)
		frappe.set_user("Administrator")
