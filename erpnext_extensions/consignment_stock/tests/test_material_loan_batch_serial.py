# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.consignment_stock.material_loan.recognition_service import (
	create_recognition_journal_entry,
)
from erpnext_extensions.consignment_stock.material_loan.returnable_qty import (
	get_remaining_returnable_qty,
)
from erpnext_extensions.consignment_stock.material_loan.settlement_service import (
	create_settlement_journal_entry,
)
from erpnext_extensions.consignment_stock.tests.material_loan_helpers import (
	enable_serial_batch_fields,
	ensure_batch_item,
	ensure_customer,
	ensure_material_loan_ready,
	ensure_material_loan_settings,
	ensure_material_loan_stock_entry_types,
	ensure_serial_item,
	get_irr_company,
	make_batch,
	make_material_loan_issue,
	make_material_loan_return,
	receive_stock_with_batch_or_serial,
)
from erpnext_extensions.iran_accounting.e2e_bootstrap import enable_perpetual_inventory


class TestMaterialLoanBatchSerial(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_material_loan_ready()
		enable_serial_batch_fields()
		cls.company = get_irr_company("ESPAD")
		enable_perpetual_inventory(cls.company)
		frappe.db.set_value("Company", cls.company, "enable_item_wise_inventory_account", 0)
		_, cls.accounts, cls.wh = ensure_material_loan_settings(cls.company)
		cls.types = ensure_material_loan_stock_entry_types()
		cls.customer = ensure_customer(cls.company)

	def test_batch_partial_wrong_over_cancel(self):
		item = ensure_batch_item()
		batch_a = make_batch(item, f"MLA-{frappe.generate_hash(length=5)}")
		batch_b = make_batch(item, f"MLB-{frappe.generate_hash(length=5)}")
		receive_stock_with_batch_or_serial(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=100,
			rate=10000,
			batch_no=batch_a,
		)
		receive_stock_with_batch_or_serial(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=20,
			rate=10000,
			batch_no=batch_b,
		)

		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=50,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
			batch_no=batch_a,
		)
		frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name)).submit()
		detail = issue.items[0].name

		# Partial return same batch
		ret1 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=20,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=detail,
			batch_no=batch_a,
		)
		self.assertAlmostEqual(get_remaining_returnable_qty(detail), 30, places=4)

		# Wrong batch blocked
		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=5,
				party_type="Customer",
				party=self.customer,
				stock_entry_type=self.types["return"],
				issue_name=issue.name,
				issue_detail=detail,
				batch_no=batch_b,
			)

		# Over-return blocked
		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=40,
				party_type="Customer",
				party=self.customer,
				stock_entry_type=self.types["return"],
				issue_name=issue.name,
				issue_detail=detail,
				batch_no=batch_a,
			)

		# Cancel restore
		ret1.cancel()
		self.assertAlmostEqual(get_remaining_returnable_qty(detail), 50, places=4)

	def test_serial_subset_unknown_duplicate_cancel(self):
		item = ensure_serial_item()
		sns = [f"SN-{frappe.generate_hash(length=6)}" for _ in range(3)]
		serial_text = "\n".join(sns)
		receive_stock_with_batch_or_serial(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=3,
			rate=10000,
			serial_no=serial_text,
		)

		issue = make_material_loan_issue(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=3,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["issue"],
			serial_no=serial_text,
		)
		frappe.get_doc("Journal Entry", create_recognition_journal_entry(issue.name)).submit()
		detail = issue.items[0].name

		# Return subset
		ret1 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=1,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=detail,
			serial_no=sns[0],
		)
		self.assertAlmostEqual(get_remaining_returnable_qty(detail), 2, places=4)

		# Unknown serial blocked
		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=1,
				party_type="Customer",
				party=self.customer,
				stock_entry_type=self.types["return"],
				issue_name=issue.name,
				issue_detail=detail,
				serial_no=f"SN-UNKNOWN-{frappe.generate_hash(length=4)}",
			)

		# Duplicate serial return blocked
		with self.assertRaises(frappe.ValidationError):
			make_material_loan_return(
				company=self.company,
				warehouse=self.wh,
				item_code=item,
				qty=1,
				party_type="Customer",
				party=self.customer,
				stock_entry_type=self.types["return"],
				issue_name=issue.name,
				issue_detail=detail,
				serial_no=sns[0],
			)

		# Cancel restores returnability of serial
		ret1.cancel()
		ret2 = make_material_loan_return(
			company=self.company,
			warehouse=self.wh,
			item_code=item,
			qty=1,
			party_type="Customer",
			party=self.customer,
			stock_entry_type=self.types["return"],
			issue_name=issue.name,
			issue_detail=detail,
			serial_no=sns[0],
			submit=False,
		)
		ret2.submit()
		self.assertAlmostEqual(get_remaining_returnable_qty(detail), 2, places=4)
