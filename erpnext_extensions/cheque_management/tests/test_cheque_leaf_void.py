# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf import void_cheque_leaf
from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	PostDatedCheque,
	_pdc_assert_cheque_leaf_usable_by_pdc,
)
from erpnext_extensions.cheque_management.tests.test_pdc_cheque_leaf_validation import _row


class TestChequeLeafVoidUnit(FrappeTestCase):
	def test_void_without_reason_fails(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-VOID-TEST-1",
				"status": "Available",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9001",
				"sequence_no": 1,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError):
				void_cheque_leaf("CL-VOID-TEST-1", "  ")

	def test_used_leaf_cannot_be_voided(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-USED",
				"status": "Used",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9002",
				"sequence_no": 2,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError) as ctx:
				void_cheque_leaf("CL-USED", "Damaged")
			self.assertIn("Only available cheque leaves can be voided", str(ctx.exception))

	def test_reserved_leaf_cannot_be_voided(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-RES",
				"status": "Reserved",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9002b",
				"sequence_no": 2,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError) as ctx:
				void_cheque_leaf("CL-RES", "Damaged")
			self.assertIn("Only available cheque leaves can be voided", str(ctx.exception))

	def test_void_leaf_cannot_be_voided_again(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-VOID2",
				"status": "Void",
				"void_reason": "done",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9002c",
				"sequence_no": 2,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError) as ctx:
				void_cheque_leaf("CL-VOID2", "Again")
			self.assertIn("already void", str(ctx.exception))

	def test_reserved_by_pdc_cannot_be_voided(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-RES-PDC",
				"status": "Available",
				"reserved_by_pdc": "PDC-88",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9002d",
				"sequence_no": 2,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError):
				void_cheque_leaf("CL-RES-PDC", "Damaged")

	def test_available_leaf_can_be_voided_mocked(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-AVAIL",
				"status": "Available",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9002e",
				"sequence_no": 2,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		), patch.object(leaf, "save") as save_mock:
			out = void_cheque_leaf("CL-AVAIL", "Torn")
			save_mock.assert_called_once()
			self.assertEqual(out["status"], "Void")
			self.assertEqual(leaf.status, "Void")
			self.assertEqual(leaf.void_reason, "Torn")

	def test_linked_pdc_cannot_be_voided(self):
		leaf = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-LINK",
				"status": "Available",
				"linked_post_dated_cheque": "PDC-99",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9003",
				"sequence_no": 3,
			}
		)
		with patch.object(frappe, "get_doc", return_value=leaf), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.frappe.db.exists",
			return_value=True,
		), patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=True,
		):
			with self.assertRaises(ValidationError):
				void_cheque_leaf("CL-LINK", "Damaged")

	def test_void_to_available_blocked_on_validate(self):
		doc = frappe.get_doc(
			{
				"doctype": "Cheque Leaf",
				"name": "CL-V2A",
				"status": "Void",
				"void_reason": "x",
				"voided_on": frappe.utils.now_datetime(),
				"voided_by": "Administrator",
				"company": "C",
				"bank_account": "BA",
				"cheque_book": "CB",
				"cheque_number": "9004",
				"sequence_no": 4,
			}
		)
		before = frappe.get_doc(doc.as_dict())
		before.status = "Void"
		doc.status = "Available"
		with patch.object(doc, "get_doc_before_save", return_value=before), patch.object(
			doc, "is_new", return_value=False
		):
			with self.assertRaises(ValidationError):
				doc._validate_status_safety()

	def test_void_leaf_blocked_on_pdc(self):
		with self.assertRaises(ValidationError):
			_pdc_assert_cheque_leaf_usable_by_pdc(_row(status="Void", name="LEAF-V"), "PDC-A")

	def test_pdc_validate_rejects_void_leaf(self):
		pdc = frappe.get_doc(
			{
				"doctype": "Post Dated Cheque",
				"name": "PDC-VOID-LEAF",
				"cheque_direction": "Payable",
				"company": "C1",
				"bank_account": "BA1",
				"cheque_no": "1001",
				"cheque_leaf": "LEAF-V",
				"docstatus": 0,
			}
		)
		row = _row(status="Void", name="LEAF-V")
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_get_cheque_leaf_row_for_update",
			return_value=row,
		):
			with self.assertRaises(ValidationError):
				PostDatedCheque._validate_cheque_leaf_integration(pdc)


class TestChequeLeafVoidIntegration(FrappeTestCase):
	def _provision_leaf(self) -> str:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		bank_account = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
		if not company or not bank_account:
			self.skipTest("No Company / Bank Account for integration")
		import random

		start = random.randint(100_000_000, 999_999_000)
		book = frappe.new_doc("Cheque Book")
		book.company = company
		book.bank_account = bank_account
		book.generation_mode = "prefix_plus_sequence"
		book.start_number = start
		book.end_number = start + 1
		book.number_width = 6
		book.insert(ignore_permissions=True)
		book.generate_leaves()
		leaf = frappe.db.get_value(
			"Cheque Leaf",
			{"cheque_book": book.name, "status": "Available"},
			"name",
			order_by="sequence_no asc",
		)
		if not leaf:
			self.skipTest("Could not generate leaf")
		return leaf

	def test_available_leaf_void_populates_fields(self):
		frappe.set_user("Administrator")
		leaf = self._provision_leaf()
		out = void_cheque_leaf(leaf, "Physical damage — torn")
		self.assertEqual(out["status"], "Void")
		doc = frappe.get_doc("Cheque Leaf", leaf)
		self.assertEqual(doc.status, "Void")
		self.assertEqual(doc.void_reason, "Physical damage — torn")
		self.assertTrue(doc.voided_on)
		self.assertEqual(doc.voided_by, "Administrator")

	def test_voided_leaf_cannot_be_voided_again_integration(self):
		frappe.set_user("Administrator")
		leaf = self._provision_leaf()
		void_cheque_leaf(leaf, "Once")
		with self.assertRaises(ValidationError) as ctx:
			void_cheque_leaf(leaf, "Twice")
		self.assertIn("already void", str(ctx.exception))

	def test_permission_denied_when_not_allowed(self):
		frappe.set_user("Administrator")
		leaf = self._provision_leaf()
		with patch(
			"erpnext_extensions.cheque_management.doctype.cheque_leaf.cheque_leaf.user_may_void_cheque_leaf",
			return_value=False,
		):
			with self.assertRaises(ValidationError):
				void_cheque_leaf(leaf, "Should fail")
