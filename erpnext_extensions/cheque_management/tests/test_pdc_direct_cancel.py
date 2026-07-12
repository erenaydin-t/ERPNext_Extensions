# Copyright (c) 2026, ERPNext Extensions contributors

"""Block direct Post Dated Cheque cancel (desk Cancel / doc.cancel)."""

from __future__ import annotations

import time
import unittest
from datetime import date, timedelta

import frappe
from frappe.exceptions import ValidationError

from erpnext_extensions.cheque_management.pdc_direct_cancel_policy import (
	can_cancel_document,
	pdc_internal_direct_cancel,
	validate_pdc_direct_cancel_allowed,
)
from erpnext_extensions.cheque_management.pdc_workflow_to_cheque_status import (
	map_workflow_state_to_cheque_status,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup import (
	_attach_coi_import_link,
	_create_draft_receivable_pdc,
)
from erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback_lifecycle_integration import (
	_apply_action,
	_ensure_pdc_settings,
	_get_bank_account,
	_get_company,
	_get_group_account,
	_get_or_create_account,
	_provision_payable_leaf,
)
from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	unlink_opening_import_and_delete_pdc,
)


def _uniq(prefix: str) -> str:
	return f"{prefix}-{int(time.time() * 1000)}"


def _make_submitted_registered_payable() -> frappe.model.document.Document:
	company = _get_company()
	bank_account = _get_bank_account(company)
	assets = _get_group_account(company, "Asset")
	liab = _get_group_account(company, "Liability")
	ci_hand = _get_or_create_account(company, assets, _uniq("UT-CIH"))
	ci_clear = _get_or_create_account(company, assets, _uniq("UT-CLR"))
	protested = _get_or_create_account(company, assets, _uniq("UT-PROT"))
	pool = _get_or_create_account(company, liab, _uniq("UT-POOL"))
	ap = _get_or_create_account(company, liab, _uniq("UT-AP"))
	_ensure_pdc_settings(company, ci_hand=ci_hand, ci_clear=ci_clear, pool=pool, protested=protested)
	leaf = _provision_payable_leaf(company, bank_account)
	cheque_no = frappe.db.get_value("Cheque Leaf", leaf, "cheque_number")
	supplier = frappe.get_doc(
		{
			"doctype": "Supplier",
			"supplier_name": _uniq("SUP-CAN"),
			"supplier_type": "Individual",
			"supplier_group": frappe.db.get_value("Supplier Group", {}, "name", order_by="lft asc")
			or "All Supplier Groups",
		}
	).insert(ignore_permissions=True)
	pdc = frappe.new_doc("Post Dated Cheque")
	pdc.naming_series = "PDC-.YYYY.-"
	pdc.company = company
	pdc.cheque_direction = "Payable"
	pdc.allocation_mode = "direct_settlement"
	pdc.advance_scope = "order_based"
	pdc.party_type = "Supplier"
	pdc.party = supplier.name
	pdc.cheque_no = cheque_no
	pdc.cheque_due_date = date.today() + timedelta(days=30)
	pdc.received_date = date.today()
	pdc.cheque_amount = 1000
	pdc.bank_account = bank_account
	pdc.cheque_leaf = leaf
	pdc.account_paid_from = pool
	pdc.account_paid_to = ap
	pdc.insert(ignore_permissions=True)
	return _apply_action(pdc, "Register Cheque")


def _issue_payable(doc):
	if not doc.get("handover_date"):
		doc.handover_date = date.today()
		doc.save(ignore_permissions=True)
	return _apply_action(doc, "Issue Cheque")


class TestPDCDirectCancelUnit(unittest.TestCase):
	def test_can_cancel_document_false_for_pdc(self):
		self.assertFalse(can_cancel_document("Post Dated Cheque"))

	def test_can_cancel_document_other_doctype_unchanged(self):
		self.assertIsInstance(can_cancel_document("PM Request"), bool)

	def test_validate_blocks_without_flag(self):
		with self.assertRaises(ValidationError) as ctx:
			validate_pdc_direct_cancel_allowed()
		self.assertIn("Rollback Workflow State", str(ctx.exception))

	def test_internal_flag_allows_validate_only(self):
		with pdc_internal_direct_cancel(flag="allow_pdc_direct_cancel"):
			validate_pdc_direct_cancel_allowed()


class TestPDCDirectCancelIntegration(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def test_submitted_pdc_direct_cancel_blocked(self):
		doc = _make_submitted_registered_payable()
		self.assertEqual(doc.docstatus, 1)
		ws_before = doc.workflow_state
		with self.assertRaises(ValidationError) as ctx:
			frappe.get_doc("Post Dated Cheque", doc.name).cancel()
		self.assertIn("Rollback Workflow State", str(ctx.exception))
		row = frappe.db.get_value(
			"Post Dated Cheque",
			doc.name,
			["docstatus", "workflow_state"],
			as_dict=True,
		)
		self.assertEqual(row.docstatus, 1)
		self.assertEqual(row.workflow_state, ws_before)

	def test_legacy_cancelled_pdc_readable(self):
		doc = _make_submitted_registered_payable()
		doc = _issue_payable(doc)
		status = map_workflow_state_to_cheque_status("Payable", "Cancelled")
		frappe.db.set_value(
			"Post Dated Cheque",
			doc.name,
			{"workflow_state": "Cancelled", "cheque_status": status},
			update_modified=False,
		)
		doc = frappe.get_doc("Post Dated Cheque", doc.name)
		with pdc_internal_direct_cancel(flag="allow_pdc_direct_cancel"):
			doc.flags.ignore_validate = True
			doc.cancel()
		frappe.db.commit()
		loaded = frappe.get_doc("Post Dated Cheque", doc.name)
		self.assertEqual(loaded.docstatus, 2)
		self.assertEqual(loaded.workflow_state, "Cancelled")

	def test_import_cleanup_cancel_with_internal_flag(self):
		ctx = _site_context()
		chq = _unique_cheque_no("UT-DEL-CAN")
		pdc = _create_draft_receivable_pdc(ctx, chq)
		_attach_coi_import_link(pdc)
		frappe.db.commit()
		out = unlink_opening_import_and_delete_pdc(pdc, reason="direct cancel policy test")
		self.assertTrue(out["ok"])
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc))

	def test_rollback_still_works(self):
		from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
			get_rollback_target_states,
			rollback_workflow_state,
		)

		doc = _make_submitted_registered_payable()
		doc = _issue_payable(doc)
		targets = get_rollback_target_states(doc.name)
		self.assertIn("Registered", targets)
		out = rollback_workflow_state(doc.name, "Registered", "integration rollback after cancel policy")
		self.assertEqual(out.get("workflow_state"), "Registered")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", doc.name, "workflow_state"),
			"Registered",
		)
