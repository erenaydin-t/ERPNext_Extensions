# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest.mock import patch

import frappe
from frappe.utils import today

from erpnext_extensions.cheque_management.pdc_import_cleanup_ui import (
	delete_imported_pdc_from_ui,
	preview_delete_imported_pdc,
	user_may_delete_imported_pdc_ui,
)
from erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup import (
	_attach_coi_import_link,
	_create_draft_receivable_pdc,
	_ensure_drawer_bank,
)
from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	PDCImportCleanupError,
	unlink_opening_import_and_delete_pdc,
)
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


class TestPDCImportCleanupUI(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_administrator_can_preview_safe(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-PREV"))
		coi = _attach_coi_import_link(pdc)
		out = preview_delete_imported_pdc(pdc)
		self.assertTrue(out["allowed"])
		self.assertEqual(out["cheque_opening_import"], coi)
		self.assertEqual(out["audit_summary"]["gl_entry_count"], 0)

	def test_non_administrator_cannot_preview_or_delete(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-NOADM"))
		_attach_coi_import_link(pdc)
		frappe.set_user("Guest")
		with self.assertRaises(frappe.PermissionError):
			preview_delete_imported_pdc(pdc)
		with self.assertRaises(frappe.PermissionError):
			delete_imported_pdc_from_ui(pdc, "should fail")
		self.assertFalse(user_may_delete_imported_pdc_ui())

	def test_delete_requires_reason(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-REASON"))
		_attach_coi_import_link(pdc)
		with self.assertRaises(frappe.ValidationError):
			delete_imported_pdc_from_ui(pdc, "")

	def test_delete_blocks_journal_reference(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-JR"))
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
		_attach_coi_import_link(pdc)
		out = preview_delete_imported_pdc(pdc)
		self.assertFalse(out["allowed"])
		with self.assertRaises(PDCImportCleanupError):
			delete_imported_pdc_from_ui(pdc, "blocked")

	def test_delete_blocks_linked_journal_entry(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-JE"))
		_attach_coi_import_link(pdc)
		with patch(
			"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.audit_pdc_import_cleanup_safety",
			return_value={
				"safe_to_unlink_and_delete": False,
				"cheque_opening_import_items": [frappe._dict(parent="COI-TEST", row_number=1)],
				"journal_references": [],
				"journal_entries": ["JV-1"],
				"gl_entry_count": 0,
				"payment_ledger_entry_count": 0,
				"blockers": ["Journal Entry linked (JV-1)."],
			},
		):
			out = preview_delete_imported_pdc(pdc)
		self.assertFalse(out["allowed"])

	def test_delete_blocks_gl(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-GL"))
		_attach_coi_import_link(pdc)
		with patch(
			"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.audit_pdc_import_cleanup_safety",
			return_value={
				"safe_to_unlink_and_delete": False,
				"cheque_opening_import_items": [frappe._dict(parent="COI-TEST", row_number=1)],
				"journal_references": [],
				"journal_entries": [],
				"gl_entry_count": 3,
				"payment_ledger_entry_count": 0,
				"blockers": ["GL Entry exists (3 row(s))."],
			},
		):
			out = preview_delete_imported_pdc(pdc)
		self.assertFalse(out["allowed"])

	def test_delete_blocks_ple(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-PLE"))
		_attach_coi_import_link(pdc)
		with patch(
			"erpnext_extensions.cheque_management.pdc_import_cleanup_ui.audit_pdc_import_cleanup_safety",
			return_value={
				"safe_to_unlink_and_delete": False,
				"cheque_opening_import_items": [frappe._dict(parent="COI-TEST", row_number=1)],
				"journal_references": [],
				"journal_entries": [],
				"gl_entry_count": 0,
				"payment_ledger_entry_count": 2,
				"blockers": ["Payment Ledger Entry exists (2 row(s))."],
			},
		):
			out = preview_delete_imported_pdc(pdc)
		self.assertFalse(out["allowed"])

	def test_safe_delete_via_ui_clears_links_only(self):
		ctx = _site_context()
		chq = _unique_cheque_no("UI-SAFE")
		pdc = _create_draft_receivable_pdc(ctx, chq)
		coi_name = _attach_coi_import_link(pdc)
		item = frappe.db.get_value(
			"Cheque Opening Import Item",
			{"parent": coi_name, "imported_pdc": pdc},
			"name",
		)
		delete_imported_pdc_from_ui(pdc, "ui safe delete")
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc))
		item_after = frappe.db.get_value(
			"Cheque Opening Import Item",
			item,
			["imported_pdc", "post_dated_cheque", "row_status"],
			as_dict=True,
		)
		self.assertIsNone(item_after.imported_pdc)
		self.assertIsNone(item_after.post_dated_cheque)
		self.assertEqual(item_after.row_status, "Imported")

	def test_safe_delete_does_not_set_row_failed(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-NOFAIL"))
		coi_name = _attach_coi_import_link(pdc, row_status="Imported")
		delete_imported_pdc_from_ui(pdc, "no failed status")
		st = frappe.db.get_value(
			"Cheque Opening Import Item",
			{"parent": coi_name},
			"row_status",
		)
		self.assertNotEqual(st, "Failed")
		self.assertEqual(st, "Imported")

	def test_coi_parent_remains(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-PARENT"))
		coi_name = _attach_coi_import_link(pdc)
		delete_imported_pdc_from_ui(pdc, "keep parent")
		self.assertTrue(frappe.db.exists("Cheque Opening Import", coi_name))

	def test_timeline_comment_on_coi(self):
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-CMT"))
		coi_name = _attach_coi_import_link(pdc)
		delete_imported_pdc_from_ui(pdc, "audit trail reason")
		comments = frappe.get_all(
			"Comment",
			filters={
				"reference_doctype": "Cheque Opening Import",
				"reference_name": coi_name,
				"comment_type": "Info",
			},
			fields=["content"],
		)
		self.assertTrue(any(pdc in (c.content or "") for c in comments))
		self.assertTrue(any("audit trail reason" in (c.content or "") for c in comments))


class TestPDCImportCleanupUIIntegration(unittest.TestCase):
	def test_scenario_a_import_delete_reimport(self):
		frappe.set_user("Administrator")
		ctx = _site_context()
		_ensure_drawer_bank(ctx)
		chq = _unique_cheque_no("UI-INT-A")
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
			},
		)
		coi1.import_status = "Completed"
		coi1.save(ignore_permissions=True)
		frappe.db.commit()

		delete_imported_pdc_from_ui(pdc1, "integration A")
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc1))
		self.assertTrue(frappe.db.exists("Cheque Opening Import", coi1.name))
		orphan = frappe.db.count("Cheque Opening Import Item", {"imported_pdc": pdc1})
		self.assertEqual(orphan, 0)

		coi2 = frappe.new_doc("Cheque Opening Import")
		coi2.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi2.name
		pdc2 = import_row(1, row)
		delattr(frappe.flags, "cheque_opening_import_name")
		self.assertTrue(frappe.db.exists("Post Dated Cheque", pdc2))

	def test_scenario_b_accounting_blocks_ui_delete(self):
		frappe.set_user("Administrator")
		ctx = _site_context()
		pdc = _create_draft_receivable_pdc(ctx, _unique_cheque_no("UI-INT-B"))
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
		_attach_coi_import_link(pdc)
		with self.assertRaises(PDCImportCleanupError):
			delete_imported_pdc_from_ui(pdc, "must block")
		self.assertTrue(frappe.db.exists("Post Dated Cheque", pdc))


if __name__ == "__main__":
	unittest.main()
