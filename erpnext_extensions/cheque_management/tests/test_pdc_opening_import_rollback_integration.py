# Copyright (c) 2026, ERPNext Extensions contributors
"""Integration: opening-import PDC rollback respects import baseline."""

from __future__ import annotations

import frappe
from frappe.tests import IntegrationTestCase

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	import_row,
)
from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
	_base_payable_row,
	_base_receivable_row,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import (
	get_pdc_workflow_rollback_preview,
	get_rollback_target_states,
	rollback_workflow_state,
	sql_integrity_is_clean,
	sql_verify_pdc_rollback_integrity,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_site_context,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup import _ensure_drawer_bank


class TestOpeningImportRollbackIntegration(IntegrationTestCase):
	def setUp(self):
		frappe.set_user("Administrator")

	def _import_payable_at(self, workflow_state: str) -> str:
		ctx = _site_context()
		chq = _unique_cheque_no(f"OI-P-{workflow_state[:3]}")
		row = _base_payable_row(ctx, chq, workflow_state)
		from frappe.utils import today

		if workflow_state == "Issued":
			row["handover_date"] = today()
		if workflow_state == "Cleared":
			row["handover_date"] = today()
			row["cleared_date"] = today()
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			return import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")

	def test_payable_issued_baseline_import_clear_rollback(self):
		from frappe.utils import today

		pdc_name = self._import_payable_at("Issued")
		row = frappe.db.get_value(
			"Post Dated Cheque",
			pdc_name,
			["opening_import_workflow_state", "workflow_state"],
			as_dict=True,
		)
		self.assertEqual(row.opening_import_workflow_state, WORKFLOW_ISSUED)
		self.assertEqual(row.workflow_state, WORKFLOW_ISSUED)
		self.assertEqual(get_rollback_target_states(pdc_name), [])

		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		doc.workflow_state = WORKFLOW_CLEARED
		doc.cleared_date = today()
		if not doc.handover_date:
			doc.handover_date = doc.received_date or today()
		doc.save()

		refs = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": pdc_name},
			fields=["pdc_transition_key", "journal_entry"],
		)
		self.assertTrue(
			any("|Issued|Cleared" in (r.pdc_transition_key or "") for r in refs),
			msg=f"Expected Issued→Cleared journal reference, got {refs}",
		)

		targets = get_rollback_target_states(pdc_name)
		self.assertEqual(targets, [WORKFLOW_ISSUED])
		self.assertNotIn(WORKFLOW_REGISTERED, targets)
		self.assertNotIn(WORKFLOW_DRAFT, targets)

		prev = get_pdc_workflow_rollback_preview(pdc_name, WORKFLOW_ISSUED)
		self.assertEqual(prev.get("opening_import_baseline"), WORKFLOW_ISSUED)
		self.assertEqual(len(prev.get("steps") or []), 1)
		cancelled_je = (prev["steps"][0].get("journal_entry") or "").strip()

		rollback_workflow_state(pdc_name, WORKFLOW_ISSUED, "integration issued baseline rollback")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "workflow_state"), WORKFLOW_ISSUED
		)
		self.assertFalse(frappe.db.get_value("Post Dated Cheque", pdc_name, "cleared_date"))
		self.assertEqual(get_rollback_target_states(pdc_name), [])

		if cancelled_je:
			report = sql_verify_pdc_rollback_integrity(
				pdc_name, cancelled_journal_entries=[cancelled_je]
			)
			self.assertTrue(sql_integrity_is_clean(report, [cancelled_je]))

	def test_payable_cleared_baseline_no_rollback(self):
		pdc_name = self._import_payable_at("Cleared")
		from frappe.utils import today

		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		if not doc.cleared_date:
			doc.cleared_date = today()
			doc.save()
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "opening_import_workflow_state"),
			WORKFLOW_CLEARED,
		)
		self.assertEqual(get_rollback_target_states(pdc_name), [])

	def test_payable_registered_baseline_then_issue_clear_rollback(self):
		pdc_name = self._import_payable_at("Registered")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "opening_import_workflow_state"),
			WORKFLOW_REGISTERED,
		)
		self.assertEqual(get_rollback_target_states(pdc_name), [])

		from frappe.utils import today

		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		doc.workflow_state = WORKFLOW_ISSUED
		doc.handover_date = today()
		doc.save()
		doc.reload()
		doc.workflow_state = WORKFLOW_CLEARED
		doc.cleared_date = today()
		doc.save()

		targets = get_rollback_target_states(pdc_name)
		self.assertIn(WORKFLOW_ISSUED, targets)
		self.assertIn(WORKFLOW_REGISTERED, targets)
		self.assertNotIn(WORKFLOW_DRAFT, targets)

		rollback_workflow_state(pdc_name, WORKFLOW_ISSUED, "integration clear to issued")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "workflow_state"), WORKFLOW_ISSUED
		)

		rollback_workflow_state(pdc_name, WORKFLOW_REGISTERED, "integration issued to registered")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "workflow_state"), WORKFLOW_REGISTERED
		)
		self.assertEqual(get_rollback_target_states(pdc_name), [])

	def test_receivable_sent_to_bank_baseline(self):
		ctx = _site_context()
		_ensure_drawer_bank(ctx)
		chq = _unique_cheque_no("OI-R-STB")
		row = _base_receivable_row(ctx, chq, "Sent to Bank")
		from frappe.utils import today

		row["sent_to_bank_date"] = today()
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			pdc_name = import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")

		self.assertEqual(get_rollback_target_states(pdc_name), [])
		self.assertNotIn(
			WORKFLOW_REGISTERED,
			get_rollback_target_states(pdc_name),
		)

		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		from frappe.utils import today

		doc.workflow_state = WORKFLOW_CLEARED
		doc.cleared_date = today()
		doc.save()
		targets = get_rollback_target_states(pdc_name)
		self.assertIn(WORKFLOW_SENT_TO_BANK, targets)
		self.assertNotIn(WORKFLOW_REGISTERED, targets)
