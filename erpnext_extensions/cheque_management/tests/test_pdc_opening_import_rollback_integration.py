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
	get_rollback_target_states,
	rollback_workflow_state,
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
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			return import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")

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
