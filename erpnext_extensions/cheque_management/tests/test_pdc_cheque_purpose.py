# Copyright (c) 2026, ERPNext Extensions contributors
"""Unit + integration tests for Post Dated Cheque ``cheque_purpose``.

Run via::

	bench --site development.localhost execute \\
	  erpnext_extensions.cheque_management.tests.run_cheque_purpose_tests.run
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace

import frappe

from erpnext_extensions.cheque_management.doctype.cheque_opening_import.cheque_opening_import import (
	TEMPLATE_HEADERS,
	import_row,
)
from erpnext_extensions.cheque_management.doctype.cheque_opening_import.run_live_opening_import_accounting_e2e import (
	_base_payable_row,
	_base_receivable_row,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import rollback_workflow_state
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
)
from erpnext_extensions.cheque_management.run_live_party_orchestration_e2e import (
	_new_payable_pdc,
	_new_receivable_pdc,
	_transition,
	_unique_cheque_no,
)
from erpnext_extensions.cheque_management.tests.cheque_purpose_context import (
	ensure_cheque_purpose_context,
)
from erpnext_extensions.cheque_management.tests.test_pdc_import_cleanup import (
	_attach_coi_import_link,
)
from erpnext_extensions.cheque_management.utils.descriptions import (
	PDCDescriptionContext,
	render_description_template,
	render_pdc_je_text,
)
from erpnext_extensions.cheque_management.utils.pdc_import_cleanup import (
	audit_pdc_import_cleanup_safety,
	unlink_opening_import_and_delete_pdc,
)


class TestChequePurposeUnit(unittest.TestCase):
	"""Schema / template unit tests."""

	def test_field_exists_small_text_optional(self):
		meta = frappe.get_meta("Post Dated Cheque")
		df = meta.get_field("cheque_purpose")
		self.assertIsNotNone(df)
		self.assertEqual(df.fieldtype, "Small Text")
		self.assertFalse(df.reqd)
		self.assertEqual(int(df.permlevel or 0), 0)
		self.assertFalse(int(df.hidden or 0))
		search = (meta.search_fields or "").replace(" ", "")
		self.assertIn("cheque_purpose", search.split(","))

	def test_template_placeholder_renders_purpose(self):
		ctx = PDCDescriptionContext(
			pdc_name="PDC-1",
			cheque_no="CHK-1",
			party="SUP-1",
			party_type="Supplier",
			cheque_amount=100,
			cheque_due_date="2026-08-01",
			cheque_purpose="Settlement of Purchase Invoice PI-00045",
			workflow_state="Registered",
			cheque_status="Registered",
			cheque_direction="Payable",
			company="_TC",
			bank_account="BA-1",
			from_state="Draft",
			to_state="Registered",
		)
		out = render_pdc_je_text(
			"{cheque_no} - {cheque_purpose}",
			fallback_text="fallback",
			context=ctx,
		)
		self.assertEqual(out, "CHK-1 - Settlement of Purchase Invoice PI-00045")

	def test_empty_placeholder_does_not_raise(self):
		ctx = PDCDescriptionContext.from_doc(
			SimpleNamespace(name="PDC-2", cheque_no="CHK-2", cheque_purpose=None)
		)
		out = render_description_template("{cheque_no} - {cheque_purpose}", ctx.as_dict())
		self.assertEqual(out, "CHK-2 - ")
		out2 = render_pdc_je_text(
			"{cheque_no} - {cheque_purpose}",
			fallback_text="fallback",
			context=ctx,
		)
		self.assertEqual(out2, "CHK-2 - ")

	def test_opening_template_includes_cheque_purpose(self):
		self.assertIn("cheque_purpose", TEMPLATE_HEADERS)


class TestChequePurposeIntegration(unittest.TestCase):
	def setUp(self):
		frappe.set_user("Administrator")
		self.ctx = ensure_cheque_purpose_context()
		frappe.db.commit()

	def test_payable_saves_persian_purpose(self):
		purpose = "تسویه فاکتور خرید شماره PI-00045"
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("UT-P-FA"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)
		got = frappe.get_doc("Post Dated Cheque", doc.name)
		self.assertEqual(got.cheque_purpose, purpose)

	def test_receivable_saves_english_purpose(self):
		purpose = "Collection for April sales"
		doc = _new_receivable_pdc(self.ctx, _unique_cheque_no("UT-R-EN"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)

	def test_whitespace_trimmed(self):
		doc = _new_receivable_pdc(self.ctx, _unique_cheque_no("UT-TRIM"))
		doc.cheque_purpose = "  Office rent payment  "
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		self.assertEqual(doc.cheque_purpose, "Office rent payment")

	def test_whitespace_only_becomes_empty(self):
		doc = _new_receivable_pdc(self.ctx, _unique_cheque_no("UT-WS"))
		doc.cheque_purpose = "   \t  "
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		self.assertFalse(doc.cheque_purpose)

	def test_existing_pdc_without_purpose_remains_valid(self):
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("UT-EMPTY"))
		self.assertFalse(doc.cheque_purpose)
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		self.assertFalse(doc.cheque_purpose)

	def test_purpose_returned_by_get_doc_and_api_list(self):
		purpose = "Advance payment to supplier"
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("UT-API"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		got = frappe.get_doc("Post Dated Cheque", doc.name)
		self.assertEqual(got.cheque_purpose, purpose)
		rows = frappe.get_list(
			"Post Dated Cheque",
			filters={"name": doc.name},
			fields=["name", "cheque_purpose"],
		)
		self.assertEqual(rows[0].cheque_purpose, purpose)

	def test_payable_workflow_preserves_purpose(self):
		purpose = "تسویه فاکتور خرید شماره PI-00045"
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("INT-P-WF"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		if doc.docstatus == 0:
			doc.submit()
			frappe.db.commit()
			doc.reload()
		_transition(doc, WORKFLOW_REGISTERED, received_date=frappe.utils.today())
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)
		from frappe.utils import today

		_transition(doc, WORKFLOW_ISSUED, handover_date=today())
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)

	def test_receivable_workflow_preserves_purpose(self):
		purpose = "دریافت بابت فروش فروردین"
		doc = _new_receivable_pdc(self.ctx, _unique_cheque_no("INT-R-WF"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		if doc.docstatus == 0:
			doc.submit()
			frappe.db.commit()
			doc.reload()
		_transition(doc, WORKFLOW_REGISTERED, received_date=frappe.utils.today())
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)

	def test_opening_import_with_purpose(self):
		purpose = "تسویه فاکتور خرید شماره PI-00045"
		chq = _unique_cheque_no("OI-PURP")
		row = _base_payable_row(self.ctx, chq, "Draft", cheque_purpose=purpose)
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			pdc_name = import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")
		self.assertEqual(
			frappe.db.get_value("Post Dated Cheque", pdc_name, "cheque_purpose"),
			purpose,
		)

	def test_opening_import_without_purpose_column(self):
		chq = _unique_cheque_no("OI-NOP")
		row = _base_receivable_row(self.ctx, chq, "Draft")
		self.assertNotIn("cheque_purpose", row)
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			pdc_name = import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")
		self.assertFalse(frappe.db.get_value("Post Dated Cheque", pdc_name, "cheque_purpose"))

	def test_rollback_preserves_purpose(self):
		purpose = "Loan installment payment"
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("INT-RB"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		if doc.docstatus == 0:
			doc.submit()
			frappe.db.commit()
			doc.reload()
		from frappe.utils import today

		_transition(doc, WORKFLOW_REGISTERED, received_date=today())
		doc.reload()
		_transition(doc, WORKFLOW_ISSUED, handover_date=today())
		doc.reload()
		self.assertEqual(doc.cheque_purpose, purpose)
		rollback_workflow_state(doc.name, WORKFLOW_REGISTERED, "cheque purpose rollback test")
		doc.reload()
		self.assertEqual(doc.workflow_state, WORKFLOW_REGISTERED)
		self.assertEqual(doc.cheque_purpose, purpose)

	def test_delete_imported_pdc_still_works(self):
		purpose = "Security deposit received"
		chq = _unique_cheque_no("OI-DEL")
		row = _base_receivable_row(self.ctx, chq, "Draft", cheque_purpose=purpose)
		coi = frappe.new_doc("Cheque Opening Import")
		coi.insert(ignore_permissions=True)
		frappe.flags.cheque_opening_import_name = coi.name
		try:
			pdc_name = import_row(1, row)
		finally:
			if hasattr(frappe.flags, "cheque_opening_import_name"):
				delattr(frappe.flags, "cheque_opening_import_name")
		_attach_coi_import_link(pdc_name)
		report = audit_pdc_import_cleanup_safety(pdc_name)
		self.assertTrue(report["safe_to_unlink_and_delete"])
		out = unlink_opening_import_and_delete_pdc(pdc_name, reason="cheque purpose delete test")
		self.assertTrue(out["ok"])
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc_name))

	def test_je_template_with_purpose_placeholder(self):
		purpose = "Office rent payment"
		doc = _new_payable_pdc(self.ctx, _unique_cheque_no("INT-JE"))
		doc.cheque_purpose = purpose
		doc.save(ignore_permissions=True)
		frappe.db.commit()
		doc.reload()
		ctx = PDCDescriptionContext.from_doc(doc, from_state=WORKFLOW_DRAFT, to_state=WORKFLOW_REGISTERED)
		remark = render_pdc_je_text(
			"{cheque_no} - {cheque_purpose}",
			fallback_text="fallback",
			context=ctx,
		)
		self.assertIn(purpose, remark)
		self.assertIn(doc.cheque_no, remark)
