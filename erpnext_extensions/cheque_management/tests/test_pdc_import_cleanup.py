# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import today

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	import_row,
)
from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
	_base_receivable_row,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	PDCImportCleanupError,
	audit_pdc_import_cleanup_safety,
	unlink_opening_import_and_delete_pdc,
)


def _ensure_drawer_bank(ctx: dict) -> None:
	if not ctx.get("drawer_bank"):
		ctx["drawer_bank"] = frappe.db.get_value("Bank", {}, "name", order_by="modified desc")


def _create_draft_receivable_pdc(ctx: dict, cheque_no: str) -> str:
	_ensure_drawer_bank(ctx)
	row = _base_receivable_row(ctx, cheque_no, "Draft")
	coi = frappe.new_doc("Cheque Opening Import")
	coi.import_status = "Draft"
	coi.insert(ignore_permissions=True)
	frappe.flags.cheque_opening_import_name = coi.name
	try:
		return import_row(1, row)
	finally:
		if hasattr(frappe.flags, "cheque_opening_import_name"):
			delattr(frappe.flags, "cheque_opening_import_name")


def _attach_coi_import_link(pdc_name: str, *, row_status: str = "Imported") -> str:
	coi = frappe.new_doc("Cheque Opening Import")
	coi.import_status = "Completed"
	coi.append(
		"items",
		{
			"row_number": 1,
			"row_status": row_status,
			"validation_message": pdc_name,
			"imported_pdc": pdc_name,
			"post_dated_cheque": pdc_name,
		},
	)
	coi.insert(ignore_permissions=True)
	frappe.db.commit()
	return coi.name


class TestPDCImportCleanupUnit(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_safe_delete_only_import_link(self):
		ctx = _site_context()
		chq = _unique_cheque_no("UT-SAFE")
		pdc = _create_draft_receivable_pdc(ctx, chq)
		coi_name = _attach_coi_import_link(pdc)
		item = frappe.db.get_value(
			"Cheque Opening Import Item",
			{"parent": coi_name, "imported_pdc": pdc},
			["name", "row_status"],
			as_dict=True,
		)
		self.assertTrue(item)

		out = unlink_opening_import_and_delete_pdc(pdc, reason="unit safe delete")
		self.assertTrue(out["ok"])
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc))
		self.assertTrue(frappe.db.exists("Cheque Opening Import", coi_name))

		item_after = frappe.db.get_value(
			"Cheque Opening Import Item",
			item.name,
			["imported_pdc", "post_dated_cheque", "row_status"],
			as_dict=True,
		)
		self.assertIsNone(item_after.imported_pdc)
		self.assertIsNone(item_after.post_dated_cheque)
		self.assertEqual(item_after.row_status, "Imported")

	def test_block_journal_reference(self):
		ctx = _site_context()
		chq = _unique_cheque_no("UT-JR")
		pdc = _create_draft_receivable_pdc(ctx, chq)
		je = frappe.db.get_value("Journal Entry", {"company": ctx["company"]}, "name", order_by="modified desc")
		if not je:
			self.skipTest("no Journal Entry for link test")
		doc = frappe.get_doc("Post Dated Cheque", pdc)
		doc.append(
			"journal_references",
			{
				"journal_entry": je,
				"purpose": "Receive",
				"posting_date": today(),
				"amount": 100,
			},
		)
		doc.save(ignore_permissions=True)
		_attach_coi_import_link(pdc)
		with self.assertRaises(PDCImportCleanupError):
			unlink_opening_import_and_delete_pdc(pdc, reason="should block")

	def test_block_gl_exists(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UT-GL"))
		with patch(
			"erpnext_extensions.cheque_management.utils.pdc_import_cleanup._gl_entry_count_for_pdc",
			return_value=2,
		):
			report = audit_pdc_import_cleanup_safety(pdc)
		self.assertFalse(report["safe_to_unlink_and_delete"])
		self.assertTrue(any("GL Entry" in b for b in report["blockers"]))

	def test_block_payment_ledger_exists(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UT-PLE"))
		with patch(
			"erpnext_extensions.cheque_management.utils.pdc_import_cleanup._payment_ledger_count_for_pdc",
			return_value=1,
		):
			report = audit_pdc_import_cleanup_safety(pdc)
		self.assertFalse(report["safe_to_unlink_and_delete"])
		self.assertTrue(any("Payment Ledger" in b for b in report["blockers"]))

	def test_block_journal_entry_linked(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UT-JE"))
		with patch(
			"erpnext_extensions.cheque_management.utils.pdc_import_cleanup._linked_journal_entries",
			return_value={"ACC-JV-BLOCK"},
		):
			report = audit_pdc_import_cleanup_safety(pdc)
		self.assertFalse(report["safe_to_unlink_and_delete"])
		self.assertTrue(any("Journal Entry" in b for b in report["blockers"]))

	def test_block_pdc_journal_reference_via_audit(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UT-REF"))
		je = frappe.db.get_value("Journal Entry", {}, "name")
		if not je:
			self.skipTest("no Journal Entry")
		doc = frappe.get_doc("Post Dated Cheque", pdc)
		doc.append(
			"journal_references",
			{
				"journal_entry": je,
				"purpose": "Receive",
				"posting_date": today(),
				"amount": 1,
			},
		)
		doc.save(ignore_permissions=True)
		report = audit_pdc_import_cleanup_safety(pdc)
		self.assertFalse(report["safe_to_unlink_and_delete"])


class TestPDCImportCleanupIntegration(unittest.TestCase):
	def test_import_delete_reimport_no_orphan_links(self):
		frappe.set_user("Administrator")
		ctx = _site_context()
		_ensure_drawer_bank(ctx)
		chq = _unique_cheque_no("INT-RE")
		row = _base_receivable_row(ctx, chq, "Registered")

		coi1 = frappe.new_doc("Cheque Opening Import")
		coi1.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi1.name
		pdc1 = import_row(1, row)
		delattr(frappe.flags, "cheque_opening_import_name")

		coi1.reload()
		coi1.items = []
		coi1.append(
			"items",
			{
				"row_number": 1,
				"row_status": "Imported",
				"imported_pdc": pdc1,
				"post_dated_cheque": pdc1,
				"validation_message": pdc1,
			},
		)
		coi1.import_status = "Completed"
		coi1.save(ignore_permissions=True)
		frappe.db.commit()

		unlink_opening_import_and_delete_pdc(pdc1, reason="integration re-import test")
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc1))
		orphan = frappe.db.count(
			"Cheque Opening Import Item",
			{"imported_pdc": pdc1},
		) + frappe.db.count("Cheque Opening Import Item", {"post_dated_cheque": pdc1})
		self.assertEqual(orphan, 0)
		self.assertTrue(frappe.db.exists("Cheque Opening Import", coi1.name))

		coi2 = frappe.new_doc("Cheque Opening Import")
		coi2.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi2.name
		pdc2 = import_row(1, row)
		delattr(frappe.flags, "cheque_opening_import_name")
		frappe.db.commit()

		self.assertTrue(frappe.db.exists("Post Dated Cheque", pdc2))
		opening_count = frappe.db.count(
			"Post Dated Cheque",
			{
				"cheque_direction": "Receivable",
				"cheque_no": chq,
				"company": ctx["company"],
				"party": ctx["customer"],
				"is_opening_import": 1,
			},
		)
		self.assertEqual(opening_count, 1)
		report = audit_pdc_import_cleanup_safety(pdc2)
		self.assertEqual(report["gl_entry_count"], 0)
		self.assertEqual(report["payment_ledger_entry_count"], 0)
		self.assertEqual(len(report["journal_references"]), 0)


if __name__ == "__main__":
	unittest.main()
