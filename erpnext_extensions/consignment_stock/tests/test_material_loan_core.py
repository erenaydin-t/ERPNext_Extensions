# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.utils import flt

from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_ISSUE_RATE,
	F_RECOGNITION_STATUS,
	REC_SUBMITTED,
)
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
	gl_balance,
	make_material_loan_issue,
	make_material_loan_return,
	party_gl_balance,
	receive_stock,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory


class TestMaterialLoanCore(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		ensure_material_loan_ready()
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		frappe.db.set_value("Company", cls.company, "enable_item_wise_inventory_account", 0)
		_, cls.accounts, cls.wh = ensure_material_loan_settings(cls.company)
		cls.types = ensure_material_loan_stock_entry_types()
		cls.item = ensure_test_item(f"ML-ITEM-{frappe.generate_hash(length=5)}")
		cls.customer = ensure_customer(cls.company)
		cls.supplier = ensure_supplier(cls.company)
		receive_stock(
			company=cls.company,
			warehouse=cls.wh,
			item_code=cls.item,
			qty=1000,
			rate=10000,
		)

	def test_customer_full_cycle_gl_and_ple(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=100,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		rate = flt(frappe.db.get_value("Stock Entry Detail", issue.items[0].name, F_ISSUE_RATE))
		self.assertGreater(rate, 0)

		# Issue GL: Dr Temp / Cr Warehouse
		temp_rows = frappe.get_all(
			"GL Entry",
			filters={
				"voucher_type": "Stock Entry",
				"voucher_no": issue.name,
				"account": self.accounts["temporary"],
				"is_cancelled": 0,
			},
			fields=["debit", "credit"],
		)
		self.assertTrue(temp_rows)
		self.assertAlmostEqual(sum(flt(r.debit) for r in temp_rows), 100 * rate, places=2)

		je_name = create_recognition_journal_entry(issue.name)
		je = frappe.get_doc("Journal Entry", je_name)
		self.assertEqual(je.docstatus, 0)
		for row in je.accounts:
			self.assertFalse(row.reference_type)
			self.assertFalse(row.reference_name)
		je.submit()

		issue.reload()
		self.assertEqual(issue.get(F_RECOGNITION_STATUS), REC_SUBMITTED)
		self.assertAlmostEqual(
			party_gl_balance(
				self.accounts["customer_receivable"], "Customer", self.customer, self.company
			),
			100 * rate,
			places=2,
		)

		ple = frappe.get_all(
			"Payment Ledger Entry",
			filters={"voucher_type": "Journal Entry", "voucher_no": je.name, "delinked": 0},
			fields=["against_voucher_type", "against_voucher_no"],
		)
		self.assertTrue(ple)
		for p in ple:
			self.assertNotEqual(p.against_voucher_type, "Stock Entry")

		se_ple = frappe.get_all(
			"Payment Ledger Entry",
			filters={"against_voucher_type": "Stock Entry", "against_voucher_no": issue.name, "delinked": 0},
		)
		self.assertEqual(se_ple, [])

		ret = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=100,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		sje_name = create_settlement_journal_entry(ret.name)
		sje = frappe.get_doc("Journal Entry", sje_name)
		sje.submit()

		self.assertAlmostEqual(
			party_gl_balance(
				self.accounts["customer_receivable"], "Customer", self.customer, self.company
			),
			0,
			places=2,
		)
		# Temp clearing for this cycle's vouchers must net to zero
		cycle_vouchers = {("Stock Entry", issue.name), ("Stock Entry", ret.name), ("Journal Entry", je.name), ("Journal Entry", sje.name)}
		temp_net = 0.0
		for vt, vn in cycle_vouchers:
			for r in frappe.get_all(
				"GL Entry",
				filters={
					"voucher_type": vt,
					"voucher_no": vn,
					"account": self.accounts["temporary"],
					"is_cancelled": 0,
				},
				fields=["debit", "credit"],
			):
				temp_net += flt(r.debit) - flt(r.credit)
		self.assertAlmostEqual(temp_net, 0, places=2)

	def test_supplier_recognition_on_payable(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=10,
			party_type="Supplier",
			party=self.supplier,
			stock_entry_type=self.types["issue"],
		)
		je_name = create_recognition_journal_entry(issue.name)
		je = frappe.get_doc("Journal Entry", je_name)
		party_row = next(r for r in je.accounts if r.party_type == "Supplier")
		self.assertEqual(party_row.account, self.accounts["supplier_payable"])
		acct_type = frappe.db.get_value("Account", party_row.account, "account_type")
		self.assertEqual(acct_type, "Payable")
		je.submit()
		rate = flt(frappe.db.get_value("Stock Entry Detail", issue.items[0].name, F_ISSUE_RATE))
		self.assertAlmostEqual(
			party_gl_balance(
				self.accounts["supplier_payable"], "Supplier", self.supplier, self.company
			),
			10 * rate,
			places=2,
		)

	def test_reject_default_debtors_mapping(self):
		default_recv = frappe.get_cached_value("Company", self.company, "default_receivable_account")
		if not default_recv:
			self.skipTest("No default receivable")
		doc = frappe.get_doc("Consignment Stock Settings", self.company)
		doc.set("material_loan_party_accounts", [])
		doc.append("material_loan_party_accounts", {"party_type": "Customer", "account": default_recv})
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		# restore
		ensure_material_loan_settings(self.company)

	def test_reject_supplier_on_receivable_mapping(self):
		doc = frappe.get_doc("Consignment Stock Settings", self.company)
		doc.set("material_loan_party_accounts", [])
		doc.append(
			"material_loan_party_accounts",
			{"party_type": "Supplier", "account": self.accounts["customer_receivable"]},
		)
		with self.assertRaises(frappe.ValidationError):
			doc.save(ignore_permissions=True)
		ensure_material_loan_settings(self.company)

	def test_partial_returns_and_over_return(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=100,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		je = frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name))
		je.submit()

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
		frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret1.name)).submit()

		ret2 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=30,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret2.name)).submit()

		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
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

	def test_return_blocked_without_recognition(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=5,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
				company=self.company,
				warehouse=self.wh,
				item_code=self.item,
				qty=5,
				party_type="Customer",
				party=self.customer,
				stock_entry_type=self.types["return"],
				issue_name=issue.name,
				issue_detail=issue.items[0].name,
			)

	def test_cancellation_order(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=20,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		rje = frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name))
		rje.submit()
		ret = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=20,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		sje = frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret.name))
		sje.submit()

		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Stock Entry", issue.name).cancel()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Stock Entry", ret.name).cancel()
		with self.assertRaises(frappe.ValidationError):
			frappe.get_doc("Journal Entry", rje.name).cancel()

		frappe.get_doc("Journal Entry", sje.name).cancel()
		frappe.get_doc("Stock Entry", ret.name).cancel()
		frappe.get_doc("Journal Entry", rje.name).cancel()
		frappe.get_doc("Stock Entry", issue.name).cancel()

	def test_duplicate_recognition_blocked(self):
		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=3,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		create_recognition_journal_entry(issue.name)
		with self.assertRaises(frappe.ValidationError):
			create_recognition_journal_entry(issue.name)

	def test_reports_execute(self):
		from erpnext_extensions.consignment_stock.report.outstanding_material_loans.outstanding_material_loans import (
			execute as outstanding_execute,
		)
		from erpnext_extensions.consignment_stock.report.material_loan_ledger.material_loan_ledger import (
			execute as ledger_execute,
		)
		from erpnext_extensions.consignment_stock.report.material_loan_aging.material_loan_aging import (
			execute as aging_execute,
		)

		filters = {"company": self.company}
		self.assertTrue(outstanding_execute(filters))
		self.assertTrue(ledger_execute(filters))
		self.assertTrue(aging_execute(filters))

	def test_repost_blocked_after_return(self):
		from erpnext_extensions.consignment_stock.material_loan.repost_guards import (
			validate_repost_item_valuation,
		)

		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=8,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
		)
		frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name)).submit()
		ret = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=self.item,
			qty=8,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=issue.items[0].name,
		)
		frappe.get_doc("Journal Entry", create_settlement_journal_entry(ret.name)).submit()

		fake = frappe._dict(voucher_type="Stock Entry", voucher_no=issue.name)
		with self.assertRaises(frappe.ValidationError):
			validate_repost_item_valuation(fake)
