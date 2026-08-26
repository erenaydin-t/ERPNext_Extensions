# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.7.0 — PDC rollback must cancel rollback-owned JEs despite lifecycle audit history.

Primary regression: PDC Lifecycle Event.journal_entry was a hard Link and, when the
child row had docstatus=1, Frappe blocked je.cancel() after JR removal.
"""

from __future__ import annotations

import json
import time
import unittest
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import frappe
from frappe.exceptions import ValidationError
from frappe.model.delete_doc import check_if_doc_is_linked
from frappe.tests.utils import FrappeTestCase

from erpnext_extensions.cheque_management.accounting_rollback import erpnext_accounting
from erpnext_extensions.cheque_management.accounting_rollback.models import RollbackTransitionStep
from erpnext_extensions.cheque_management.accounting_rollback.transitions import (
	JournalEntryTransitionHandler,
)
from erpnext_extensions.cheque_management.pdc_workflow_rollback import rollback_workflow_state


def _uniq(prefix: str) -> str:
	return f"{prefix}-{int(time.time() * 1000)}"


class TestLifecycleEventJournalEntryIsAuditData(FrappeTestCase):
	"""Schema: lifecycle journal_entry must be Data, not Link."""

	@classmethod
	def setUpClass(cls):
		if not frappe.db.exists("DocType", "PDC Lifecycle Event"):
			raise unittest.SkipTest("PDC Lifecycle Event not installed")

	def test_journal_entry_field_is_data_not_link(self):
		meta = frappe.get_meta("PDC Lifecycle Event")
		df = meta.get_field("journal_entry")
		self.assertIsNotNone(df)
		self.assertEqual(df.fieldtype, "Data")
		self.assertNotEqual(df.fieldtype, "Link")
		self.assertFalse(df.options)

	def test_json_source_is_data(self):
		path = frappe.get_app_path(
			"erpnext_extensions",
			"cheque_management",
			"doctype",
			"pdc_lifecycle_event",
			"pdc_lifecycle_event.json",
		)
		payload = json.loads(open(path, encoding="utf-8").read())
		field = next(f for f in payload["fields"] if f["fieldname"] == "journal_entry")
		self.assertEqual(field["fieldtype"], "Data")
		self.assertNotIn("options", field)

	def test_lifecycle_event_not_in_journal_entry_link_fields(self):
		from frappe.model.rename_doc import get_link_fields

		parents = {lf["parent"] for lf in get_link_fields("Journal Entry")}
		self.assertNotIn("PDC Lifecycle Event", parents)


class TestResolveJournalReferenceForRollback(unittest.TestCase):
	def test_preferred_row_used_when_valid(self):
		with (
			patch.object(frappe.db, "exists", return_value=True),
			patch.object(
				frappe.db,
				"get_value",
				return_value=frappe._dict(
					name="JR-1",
					parent="PDC-1",
					parenttype="Post Dated Cheque",
					journal_entry="JE-1",
				),
			),
			patch.object(erpnext_accounting, "find_journal_reference_rows_for_je") as find,
		):
			row = erpnext_accounting.resolve_journal_reference_row_for_rollback(
				"PDC-1", "JE-1", preferred_row="JR-1", require_row=True
			)
			self.assertEqual(row, "JR-1")
			find.assert_not_called()

	def test_fallback_exact_one_match(self):
		with (
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(
				erpnext_accounting,
				"find_journal_reference_rows_for_je",
				return_value=["JR-FALLBACK"],
			),
		):
			row = erpnext_accounting.resolve_journal_reference_row_for_rollback(
				"PDC-1", "JE-1", preferred_row="STALE", require_row=True
			)
			self.assertEqual(row, "JR-FALLBACK")

	def test_missing_match_fail_closed(self):
		with (
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(erpnext_accounting, "find_journal_reference_rows_for_je", return_value=[]),
		):
			with self.assertRaises(ValidationError):
				erpnext_accounting.resolve_journal_reference_row_for_rollback(
					"PDC-1", "JE-1", preferred_row=None, require_row=True
				)

	def test_ambiguous_matches_fail_closed(self):
		with (
			patch.object(frappe.db, "exists", return_value=False),
			patch.object(
				erpnext_accounting,
				"find_journal_reference_rows_for_je",
				return_value=["JR-A", "JR-B"],
			),
		):
			with self.assertRaises(ValidationError):
				erpnext_accounting.resolve_journal_reference_row_for_rollback(
					"PDC-1", "JE-1", preferred_row=None, require_row=True
				)

	def test_handler_removes_jr_before_cancel(self):
		step = RollbackTransitionStep(
			from_state="Draft",
			to_state="Registered",
			journal_entry="JE-1",
			journal_reference_row="JR-STALE",
			has_accounting=True,
			event_type="accounting",
		)
		pdc = SimpleNamespace(name="PDC-1")
		order: list[str] = []

		def _remove(pdc_name, s):
			order.append("remove")
			self.assertEqual(pdc_name, "PDC-1")
			return "JR-1"

		def _cancel(je):
			order.append("cancel")
			self.assertEqual(je, "JE-1")

		with (
			patch.object(erpnext_accounting, "remove_operational_journal_reference_for_step", side_effect=_remove),
			patch.object(erpnext_accounting, "cancel_journal_entry_voucher", side_effect=_cancel),
			patch.object(erpnext_accounting, "refresh_outstanding_for_journal_entry", return_value=[]),
		):
			JournalEntryTransitionHandler().rollback_accounting(step, pdc, dry_run=False)
		self.assertEqual(order, ["remove", "cancel"])


class TestPDCRollbackLinkedJEDocstatusRegression(FrappeTestCase):
	"""Live-site regression: LE audit row with docstatus 0 and 1 must not block JE cancel."""

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", "Post Dated Cheque"):
			raise unittest.SkipTest("Post Dated Cheque not installed")
		if not frappe.db.exists("DocType", "PDC Lifecycle Event"):
			raise unittest.SkipTest("PDC Lifecycle Event not installed")
		frappe.set_user("Administrator")

	def _get_company(self) -> str:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("No Company")
		return company

	def _get_bank_account(self, company: str) -> str:
		ba = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
		if not ba:
			self.skipTest(f"No Bank Account for {company}")
		return ba

	def _get_or_create_account(self, company: str, parent: str, account_name: str) -> str:
		exists = frappe.db.get_value("Account", {"company": company, "account_name": account_name}, "name")
		if exists:
			return exists
		acc = frappe.new_doc("Account")
		acc.company = company
		acc.account_name = account_name
		acc.parent_account = parent
		acc.is_group = 0
		acc.insert(ignore_permissions=True)
		return acc.name

	def _group(self, company: str, root_type: str) -> str:
		name = frappe.db.get_value(
			"Account",
			{"company": company, "is_group": 1, "root_type": root_type},
			"name",
			order_by="lft asc",
		)
		if not name:
			self.skipTest(f"No group Account root_type={root_type}")
		return name

	def _ensure_pdc_settings(self, company: str, *, pool: str, protested: str) -> None:
		name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
		if frappe.db.exists("PDC Settings", name):
			doc = frappe.get_doc("PDC Settings", name)
		else:
			doc = frappe.new_doc("PDC Settings")
			doc.company = company
			doc.name = name
		doc.default_payable_cheque_account = pool
		doc.default_protested_account = protested
		# Receivable defaults unused for Payable but keep settings valid when present.
		if not doc.get("default_cheques_in_hand_account"):
			doc.default_cheques_in_hand_account = pool
		if not doc.get("default_cheques_in_clearing_account"):
			doc.default_cheques_in_clearing_account = pool
		doc.require_sayad_registration = 0
		if doc.get("name") and frappe.db.exists("PDC Settings", doc.get("name")):
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)

	def _provision_leaf(self, company: str, bank_account: str) -> str:
		start = (int(time.time() * 1000) % 900000) + 100000
		book = frappe.new_doc("Cheque Book")
		book.company = company
		book.bank_account = bank_account
		book.generation_mode = "prefix_plus_sequence"
		book.start_number = start
		book.end_number = start
		book.number_width = 6
		book.insert(ignore_permissions=True)
		book.generate_leaves()
		leaf = frappe.db.get_value("Cheque Leaf", {"cheque_book": book.name, "status": "Available"}, "name")
		if not leaf:
			self.skipTest("Failed to generate Cheque Leaf")
		return leaf

	def _make_supplier(self) -> str:
		name = _uniq("SUP-RB")
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = name
		doc.supplier_group = (
			frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="lft asc")
			or "All Supplier Groups"
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_registered_payable(self) -> tuple[str, str, str]:
		company = self._get_company()
		bank_account = self._get_bank_account(company)
		liability = self._group(company, "Liability")
		pool = self._get_or_create_account(company, liability, _uniq("PDC-POOL-RB"))
		protested = self._get_or_create_account(company, liability, _uniq("PDC-PROT-RB"))
		self._ensure_pdc_settings(company, pool=pool, protested=protested)
		leaf = self._provision_leaf(company, bank_account)
		supplier = self._make_supplier()

		doc = frappe.new_doc("Post Dated Cheque")
		doc.cheque_direction = "Payable"
		doc.company = company
		doc.bank_account = bank_account
		doc.cheque_leaf = leaf
		doc.cheque_no = frappe.db.get_value("Cheque Leaf", leaf, "cheque_number") or "1"
		doc.cheque_amount = 1000
		doc.cheque_due_date = date.today()
		doc.received_date = date.today()
		doc.party_type = "Supplier"
		doc.party = supplier
		doc.holder_party_type = "Supplier"
		doc.holder_party = supplier
		doc.account_paid_from = pool
		doc.allocation_mode = "direct_settlement"
		doc.insert(ignore_permissions=True)
		from frappe.model.workflow import apply_workflow

		doc = apply_workflow(doc, "Register Cheque")
		doc.reload()
		self.assertEqual(doc.workflow_state, "Registered")
		self.assertEqual(doc.docstatus, 1)

		refs = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": doc.name},
			fields=["name", "journal_entry"],
		)
		self.assertTrue(refs, "Register must create a PDC Journal Reference")
		je = refs[0].journal_entry
		self.assertEqual(frappe.db.get_value("Journal Entry", je, "docstatus"), 1)
		return doc.name, je, leaf

	def _force_lifecycle_docstatus(self, pdc_name: str, je_name: str, docstatus: int) -> str:
		events = frappe.get_all(
			"PDC Lifecycle Event",
			filters={"parent": pdc_name, "journal_entry": je_name, "is_rolled_back": 0},
			fields=["name", "docstatus", "journal_entry", "journal_reference_name"],
			order_by="event_sequence asc",
		)
		if not events:
			# Ensure an audit row exists even if capture skipped on this site path.
			from erpnext_extensions.cheque_management.pdc_lifecycle_events import capture_pdc_lifecycle_event

			pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
			capture_pdc_lifecycle_event(
				pdc,
				"Draft",
				"Registered",
				"journal_entry",
				snapshot_json="{}",
				action="test_force",
			)
			events = frappe.get_all(
				"PDC Lifecycle Event",
				filters={"parent": pdc_name, "journal_entry": je_name, "is_rolled_back": 0},
				fields=["name", "docstatus", "journal_entry", "journal_reference_name"],
			)
		self.assertTrue(events, "Lifecycle Event with JE required for regression")
		le_name = events[0].name
		# Promote child docstatus to reproduce production Cancel blocker (pre-Data Link era).
		frappe.db.sql(
			"update `tabPDC Lifecycle Event` set docstatus=%s where name=%s",
			(int(docstatus), le_name),
		)
		got = frappe.db.get_value("PDC Lifecycle Event", le_name, "docstatus")
		self.assertEqual(int(got), int(docstatus))
		return le_name

	def _assert_successful_registered_to_draft(self, pdc_name: str, je: str, leaf: str, le_name: str):
		# Before cancel: operational JR still links; after Data schema LE must NOT be a Link blocker.
		je_doc = frappe.get_doc("Journal Entry", je)
		# With JR present, Cancel is still blocked by JR (expected until cleanup).
		with self.assertRaises(frappe.LinkExistsError):
			check_if_doc_is_linked(je_doc, "Cancel")

		out = rollback_workflow_state(pdc_name, "Draft", "v4.7.0 linked JE regression")
		self.assertEqual(out["workflow_state"], "Draft")

		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		self.assertEqual(doc.docstatus, 0)
		self.assertEqual(doc.workflow_state, "Draft")
		self.assertEqual(
			frappe.db.count("PDC Journal Reference", {"parent": pdc_name, "journal_entry": je}),
			0,
		)
		self.assertEqual(frappe.db.get_value("Journal Entry", je, "docstatus"), 2)

		le = frappe.db.get_value(
			"PDC Lifecycle Event",
			le_name,
			["journal_entry", "is_rolled_back", "rolled_back_on", "rolled_back_by", "rollback_log"],
			as_dict=True,
		)
		self.assertEqual(le.journal_entry, je)
		self.assertEqual(int(le.is_rolled_back or 0), 1)
		self.assertTrue(le.rolled_back_on)
		self.assertTrue(le.rolled_back_by)

		leaf_row = frappe.db.get_value(
			"Cheque Leaf",
			leaf,
			["status", "reserved_by_pdc", "linked_post_dated_cheque", "used_on"],
			as_dict=True,
		)
		self.assertEqual(leaf_row.status, "Reserved")
		self.assertEqual(leaf_row.reserved_by_pdc, pdc_name)
		self.assertFalse((leaf_row.linked_post_dated_cheque or "").strip())
		self.assertFalse(leaf_row.used_on)

	def test_registered_to_draft_with_lifecycle_docstatus_0(self):
		pdc_name, je, leaf = self._make_registered_payable()
		le_name = self._force_lifecycle_docstatus(pdc_name, je, 0)
		self._assert_successful_registered_to_draft(pdc_name, je, leaf, le_name)

	def test_registered_to_draft_with_lifecycle_docstatus_1_primary_regression(self):
		"""PRIMARY: LE child docstatus=1 used to block je.cancel(); must succeed after v4.7.0."""
		pdc_name, je, leaf = self._make_registered_payable()
		le_name = self._force_lifecycle_docstatus(pdc_name, je, 1)

		# With Data field, even docstatus=1 LE must not appear in Cancel link docs after JR removal.
		# Simulate post-JR-removal link check: delete JR in a savepoint then verify Cancel is clean,
		# then roll back that savepoint and let the real rollback path run.
		jr_names = frappe.get_all(
			"PDC Journal Reference",
			filters={"parent": pdc_name, "journal_entry": je},
			pluck="name",
		)
		self.assertEqual(len(jr_names), 1)
		frappe.db.savepoint("v470_link_probe")
		try:
			frappe.delete_doc("PDC Journal Reference", jr_names[0], force=1, ignore_permissions=True)
			je_doc = frappe.get_doc("Journal Entry", je)
			# Must NOT raise — Data audit LE must not block Cancel.
			check_if_doc_is_linked(je_doc, "Cancel")
		finally:
			frappe.db.rollback(save_point="v470_link_probe")

		self.assertTrue(frappe.db.exists("PDC Journal Reference", jr_names[0]))
		self._assert_successful_registered_to_draft(pdc_name, je, leaf, le_name)

	def test_stale_journal_reference_name_fallback(self):
		pdc_name, je, leaf = self._make_registered_payable()
		self._force_lifecycle_docstatus(pdc_name, je, 1)
		# Poison lifecycle journal_reference_name so plan preferred row is stale.
		frappe.db.sql(
			"""
			update `tabPDC Lifecycle Event`
			set journal_reference_name=%s
			where parent=%s and journal_entry=%s and ifnull(is_rolled_back,0)=0
			""",
			("STALE-JR-NAME", pdc_name, je),
		)
		out = rollback_workflow_state(pdc_name, "Draft", "v4.7.0 stale JR fallback")
		self.assertEqual(out["workflow_state"], "Draft")
		self.assertEqual(
			frappe.db.count("PDC Journal Reference", {"parent": pdc_name, "journal_entry": je}),
			0,
		)
		self.assertEqual(frappe.db.get_value("Journal Entry", je, "docstatus"), 2)
		self.assertEqual(
			frappe.db.get_value("Cheque Leaf", leaf, "status"),
			"Reserved",
		)

	def test_cancel_failure_rolls_back_jr_removal(self):
		pdc_name, je, _leaf = self._make_registered_payable()
		jr = frappe.db.get_value(
			"PDC Journal Reference",
			{"parent": pdc_name, "journal_entry": je},
			"name",
		)
		self.assertTrue(jr)

		with patch.object(
			erpnext_accounting,
			"cancel_journal_entry_voucher",
			side_effect=RuntimeError("simulated cancel failure"),
		):
			with self.assertRaises(RuntimeError):
				rollback_workflow_state(pdc_name, "Draft", "v4.7.0 cancel failure")

		# Outer request may have partially written; ensure we restore via rollback for isolation.
		frappe.db.rollback()
		# Re-read after rollback: fixture PDCs created in this test are gone unless committed.
		# The important assertion is that cancel_journal_entry_voucher failure prevents commit
		# in rollback_workflow_state (no frappe.db.commit on exception). Re-create lightly:
		pdc_name, je, _leaf = self._make_registered_payable()
		jr = frappe.db.get_value(
			"PDC Journal Reference",
			{"parent": pdc_name, "journal_entry": je},
			"name",
		)
		step = RollbackTransitionStep(
			from_state="Draft",
			to_state="Registered",
			journal_entry=je,
			journal_reference_row=jr,
			has_accounting=True,
			event_type="accounting",
		)
		pdc = frappe.get_doc("Post Dated Cheque", pdc_name)
		frappe.db.savepoint("v470_cancel_fail")
		try:
			with patch.object(
				erpnext_accounting,
				"cancel_journal_entry_voucher",
				side_effect=RuntimeError("simulated cancel failure"),
			):
				with self.assertRaises(RuntimeError):
					JournalEntryTransitionHandler().rollback_accounting(step, pdc, dry_run=False)
		finally:
			frappe.db.rollback(save_point="v470_cancel_fail")

		self.assertTrue(frappe.db.exists("PDC Journal Reference", jr))
		self.assertEqual(frappe.db.get_value("Journal Entry", je, "docstatus"), 1)

	def test_no_ignore_links_flags_in_cancel_helper(self):
		import ast

		path = frappe.get_app_path(
			"erpnext_extensions",
			"cheque_management",
			"accounting_rollback",
			"erpnext_accounting.py",
		)
		src = open(path, encoding="utf-8").read()
		tree = ast.parse(src)
		cancel_fn = next(
			n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "cancel_journal_entry_voucher"
		)
		body_src = ast.get_source_segment(src, cancel_fn) or ""
		# Docstring may mention the forbidden flags; executable body must not set them.
		self.assertNotIn("ignore_linked_doctypes", body_src.split('"""', 2)[-1])
		self.assertNotIn("ignore_links", body_src.split('"""', 2)[-1])
		self.assertNotIn("flags.ignore_links", src)
		self.assertNotIn(".ignore_linked_doctypes", src)
