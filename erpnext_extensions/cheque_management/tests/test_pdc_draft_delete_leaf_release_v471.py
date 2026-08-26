# Copyright (c) 2026, ERPNext Extensions contributors
"""v4.7.1 — Draft PDC delete must release owned Cheque Leaf reservation."""

from __future__ import annotations

import time
import unittest
from datetime import date
from unittest.mock import patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import now_datetime

from erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque import (
	_pdc_assert_and_release_leaf_on_draft_trash,
	pdc_cheque_leaf_link_query,
)
from erpnext_extensions.patches.post_model_sync.release_orphaned_pdc_cheque_leaf_reservations_v471 import (
	classify_orphan_leaf_candidate,
	repair_orphaned_pdc_cheque_leaf_reservations,
	release_orphaned_reserved_leaf,
)


def _uniq(prefix: str) -> str:
	return f"{prefix}-{int(time.time() * 1000)}"


class TestDraftPDCDeleteReleasesLeaf(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", "Post Dated Cheque"):
			raise unittest.SkipTest("Post Dated Cheque not installed")
		if not frappe.db.exists("DocType", "Cheque Leaf"):
			raise unittest.SkipTest("Cheque Leaf not installed")
		frappe.set_user("Administrator")

	def _company(self) -> str:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		if not company:
			self.skipTest("No Company")
		return company

	def _bank_account(self, company: str) -> str:
		ba = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
		if not ba:
			self.skipTest(f"No Bank Account for {company}")
		return ba

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

	def _account(self, company: str, parent: str, account_name: str) -> str:
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

	def _ensure_settings(self, company: str, pool: str) -> None:
		name = frappe.db.get_value("PDC Settings", {"company": company}, "name") or company
		if frappe.db.exists("PDC Settings", name):
			doc = frappe.get_doc("PDC Settings", name)
		else:
			doc = frappe.new_doc("PDC Settings")
			doc.company = company
			doc.name = name
		doc.default_payable_cheque_account = pool
		doc.default_protested_account = pool
		if not doc.get("default_cheques_in_hand_account"):
			doc.default_cheques_in_hand_account = pool
		if not doc.get("default_cheques_in_clearing_account"):
			doc.default_cheques_in_clearing_account = pool
		doc.require_sayad_registration = 0
		if doc.get("name") and frappe.db.exists("PDC Settings", doc.get("name")):
			doc.save(ignore_permissions=True)
		else:
			doc.insert(ignore_permissions=True)

	def _leaf(self, company: str, bank_account: str) -> str:
		start = (int(time.time() * 1000) % 900000) + 100000
		book = frappe.new_doc("Cheque Book")
		book.company = company
		book.bank_account = bank_account
		book.generation_mode = "prefix_plus_sequence"
		book.start_number = start
		book.end_number = start + 1
		book.number_width = 6
		book.insert(ignore_permissions=True)
		book.generate_leaves()
		leaf = frappe.db.get_value("Cheque Leaf", {"cheque_book": book.name, "status": "Available"}, "name")
		if not leaf:
			self.skipTest("Failed to generate Cheque Leaf")
		return leaf

	def _second_leaf(self, company: str, bank_account: str, exclude: str) -> str:
		start = (int(time.time() * 1000) % 900000) + 200000
		book = frappe.new_doc("Cheque Book")
		book.company = company
		book.bank_account = bank_account
		book.generation_mode = "prefix_plus_sequence"
		book.start_number = start
		book.end_number = start
		book.number_width = 6
		book.insert(ignore_permissions=True)
		book.generate_leaves()
		leaf = frappe.db.get_value(
			"Cheque Leaf",
			{"cheque_book": book.name, "status": "Available", "name": ["!=", exclude]},
			"name",
		)
		if not leaf:
			self.skipTest("Failed to generate second Cheque Leaf")
		return leaf

	def _supplier(self) -> str:
		name = _uniq("SUP-DEL")
		doc = frappe.new_doc("Supplier")
		doc.supplier_name = name
		doc.supplier_group = (
			frappe.db.get_value("Supplier Group", {"is_group": 0}, "name", order_by="lft asc")
			or "All Supplier Groups"
		)
		doc.insert(ignore_permissions=True)
		return doc.name

	def _make_draft_payable(self, *, leaf: str | None = None) -> tuple[str, str, str]:
		company = self._company()
		bank_account = self._bank_account(company)
		liability = self._group(company, "Liability")
		pool = self._account(company, liability, _uniq("PDC-POOL-DEL"))
		self._ensure_settings(company, pool)
		if not leaf:
			leaf = self._leaf(company, bank_account)
		supplier = self._supplier()
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
		doc.reload()
		self.assertEqual(cint_docstatus(doc.docstatus), 0)
		return doc.name, leaf, company

	def _leaf_fields(self, leaf: str) -> frappe._dict:
		return frappe.db.get_value(
			"Cheque Leaf",
			leaf,
			[
				"status",
				"reserved_by_pdc",
				"reserved_on",
				"linked_post_dated_cheque",
				"used_on",
				"linked_guarantee_document",
			],
			as_dict=True,
		)

	def test_primary_draft_delete_releases_owned_reserved_leaf(self):
		pdc_name, leaf, company = self._make_draft_payable()
		row = self._leaf_fields(leaf)
		self.assertEqual(row.status, "Reserved")
		self.assertEqual(row.reserved_by_pdc, pdc_name)

		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc_name))

		after = self._leaf_fields(leaf)
		self.assertEqual(after.status, "Available")
		self.assertFalse((after.reserved_by_pdc or "").strip())
		self.assertFalse(after.reserved_on)
		self.assertFalse((after.linked_post_dated_cheque or "").strip())
		self.assertFalse(after.used_on)

		# Leaf is selectable / reservable again by a new Draft PDC.
		bank_account = frappe.db.get_value("Cheque Leaf", leaf, "bank_account")
		rows = pdc_cheque_leaf_link_query(
			"Cheque Leaf",
			"",
			"name",
			0,
			20,
			{"company": company, "bank_account": bank_account},
		)
		names = {r[0] for r in rows}
		self.assertIn(leaf, names)

		pdc2, leaf2, _ = self._make_draft_payable(leaf=leaf)
		self.assertEqual(leaf2, leaf)
		self.assertEqual(self._leaf_fields(leaf).reserved_by_pdc, pdc2)
		frappe.delete_doc("Post Dated Cheque", pdc2, force=1, ignore_permissions=True)

	def test_draft_delete_without_leaf_succeeds(self):
		pdc_name, leaf, _ = self._make_draft_payable()
		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		doc.cheque_leaf = ""
		doc.save(ignore_permissions=True)
		self.assertEqual(self._leaf_fields(leaf).status, "Available")
		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Post Dated Cheque", pdc_name))

	def test_draft_clear_leaf_releases(self):
		pdc_name, leaf, _ = self._make_draft_payable()
		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		doc.cheque_leaf = ""
		doc.save(ignore_permissions=True)
		after = self._leaf_fields(leaf)
		self.assertEqual(after.status, "Available")
		self.assertFalse((after.reserved_by_pdc or "").strip())
		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)

	def test_draft_change_leaf_a_to_b(self):
		pdc_name, leaf_a, company = self._make_draft_payable()
		bank_account = frappe.db.get_value("Cheque Leaf", leaf_a, "bank_account")
		leaf_b = self._second_leaf(company, bank_account, leaf_a)
		doc = frappe.get_doc("Post Dated Cheque", pdc_name)
		doc.cheque_leaf = leaf_b
		doc.cheque_no = frappe.db.get_value("Cheque Leaf", leaf_b, "cheque_number") or "2"
		doc.save(ignore_permissions=True)
		self.assertEqual(self._leaf_fields(leaf_a).status, "Available")
		self.assertFalse((self._leaf_fields(leaf_a).reserved_by_pdc or "").strip())
		self.assertEqual(self._leaf_fields(leaf_b).status, "Reserved")
		self.assertEqual(self._leaf_fields(leaf_b).reserved_by_pdc, pdc_name)
		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)
		self.assertEqual(self._leaf_fields(leaf_b).status, "Available")

	def test_delete_fails_closed_when_reserved_by_another_pdc(self):
		owner, leaf, _ = self._make_draft_payable()
		intruder, _, _ = self._make_draft_payable()
		# Point intruder at owner's reserved leaf without going through normal reserve path.
		frappe.db.set_value("Post Dated Cheque", intruder, "cheque_leaf", leaf, update_modified=False)
		with self.assertRaises(frappe.ValidationError):
			frappe.delete_doc("Post Dated Cheque", intruder, force=1, ignore_permissions=True)
		self.assertTrue(frappe.db.exists("Post Dated Cheque", intruder))
		self.assertEqual(self._leaf_fields(leaf).reserved_by_pdc, owner)
		frappe.delete_doc("Post Dated Cheque", owner, force=1, ignore_permissions=True)
		frappe.db.set_value("Post Dated Cheque", intruder, "cheque_leaf", "", update_modified=False)
		frappe.delete_doc("Post Dated Cheque", intruder, force=1, ignore_permissions=True)

	def test_delete_fails_closed_for_used_void_guarantee(self):
		pdc_name, leaf, _ = self._make_draft_payable()

		def _force_and_expect_block(status: str, extra: dict | None = None):
			values = {
				"status": status,
				"reserved_by_pdc": None,
				"reserved_on": None,
				"linked_post_dated_cheque": "OTHER-PDC" if status == "Used" else None,
				"used_on": now_datetime() if status == "Used" else None,
			}
			if extra:
				values.update(extra)
			# Bypass leaf validators for fixture shaping.
			frappe.db.set_value("Cheque Leaf", leaf, values, update_modified=False)
			frappe.db.set_value("Post Dated Cheque", pdc_name, "cheque_leaf", leaf, update_modified=False)
			with self.assertRaises(frappe.ValidationError):
				_pdc_assert_and_release_leaf_on_draft_trash(leaf, frappe.get_doc("Post Dated Cheque", pdc_name))

		_force_and_expect_block("Used")
		_force_and_expect_block("Void")
		if frappe.db.has_column("Cheque Leaf", "linked_guarantee_document"):
			_force_and_expect_block(
				"Used for Guarantee",
				{"linked_guarantee_document": "GD-TEST", "linked_post_dated_cheque": None},
			)
			_force_and_expect_block(
				"Available",
				{"linked_guarantee_document": "GD-TEST", "reserved_by_pdc": pdc_name},
			)

		# Restore leaf so teardown delete of PDC can succeed or clear leaf first.
		frappe.db.set_value(
			"Cheque Leaf",
			leaf,
			{
				"status": "Reserved",
				"reserved_by_pdc": pdc_name,
				"reserved_on": now_datetime(),
				"linked_post_dated_cheque": None,
				"used_on": None,
				**(
					{"linked_guarantee_document": None}
					if frappe.db.has_column("Cheque Leaf", "linked_guarantee_document")
					else {}
				),
			},
			update_modified=False,
		)
		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)

	def test_rollback_to_draft_keeps_reserved_then_delete_makes_available(self):
		from frappe.model.workflow import apply_workflow

		from erpnext_extensions.cheque_management.pdc_workflow_rollback import rollback_workflow_state

		pdc_name, leaf, _ = self._make_draft_payable()
		doc = apply_workflow(frappe.get_doc("Post Dated Cheque", pdc_name), "Register Cheque")
		doc.reload()
		self.assertEqual(doc.workflow_state, "Registered")
		self.assertEqual(self._leaf_fields(leaf).status, "Used")

		out = rollback_workflow_state(pdc_name, "Draft", "v4.7.1 leaf delete after rollback")
		self.assertEqual(out["workflow_state"], "Draft")
		row = self._leaf_fields(leaf)
		self.assertEqual(row.status, "Reserved")
		self.assertEqual(row.reserved_by_pdc, pdc_name)

		frappe.delete_doc("Post Dated Cheque", pdc_name, force=1, ignore_permissions=True)
		after = self._leaf_fields(leaf)
		self.assertEqual(after.status, "Available")
		self.assertFalse((after.reserved_by_pdc or "").strip())
		self.assertFalse(after.reserved_on)
		self.assertFalse((after.linked_post_dated_cheque or "").strip())
		self.assertFalse(after.used_on)

	def test_receivable_delete_unaffected(self):
		company = self._company()
		bank_account = self._bank_account(company)
		assets = self._group(company, "Asset")
		cih = self._account(company, assets, _uniq("PDC-CIH-DEL"))
		self._ensure_settings(company, cih)
		# Minimal receivable draft without leaf.
		customer = _uniq("CUS-DEL")
		if not frappe.db.exists("Customer", customer):
			c = frappe.new_doc("Customer")
			c.customer_name = customer
			c.customer_type = "Individual"
			c.customer_group = (
				frappe.db.get_value("Customer Group", {"is_group": 0}, "name", order_by="lft asc")
				or "All Customer Groups"
			)
			c.territory = (
				frappe.db.get_value("Territory", {"is_group": 0}, "name", order_by="lft asc")
				or "All Territories"
			)
			c.insert(ignore_permissions=True)
		doc = frappe.new_doc("Post Dated Cheque")
		doc.cheque_direction = "Receivable"
		doc.company = company
		doc.bank_account = bank_account
		doc.cheque_no = _uniq("RNO")
		doc.cheque_amount = 500
		doc.cheque_due_date = date.today()
		doc.received_date = date.today()
		doc.party_type = "Customer"
		doc.party = customer
		doc.drawer_bank_name = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
		if not doc.drawer_bank_name:
			self.skipTest("No Bank")
		doc.account_paid_to = cih
		doc.allocation_mode = "direct_settlement"
		doc.insert(ignore_permissions=True)
		name = doc.name
		frappe.delete_doc("Post Dated Cheque", name, force=1, ignore_permissions=True)
		self.assertFalse(frappe.db.exists("Post Dated Cheque", name))


class TestOrphanLeafRepairPatchV471(FrappeTestCase):
	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		if not frappe.db.exists("DocType", "Cheque Leaf"):
			raise unittest.SkipTest("Cheque Leaf not installed")
		frappe.set_user("Administrator")

	def _temp_leaf(self) -> str:
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		ba = frappe.db.get_value("Bank Account", {"company": company}, "name", order_by="creation asc")
		if not company or not ba:
			self.skipTest("Missing company/bank account")
		start = (int(time.time() * 1000) % 900000) + 300000
		book = frappe.new_doc("Cheque Book")
		book.company = company
		book.bank_account = ba
		book.generation_mode = "prefix_plus_sequence"
		book.start_number = start
		book.end_number = start
		book.number_width = 6
		book.insert(ignore_permissions=True)
		book.generate_leaves()
		return frappe.db.get_value("Cheque Leaf", {"cheque_book": book.name}, "name")

	def test_classify_and_release_safe_orphan(self):
		leaf = self._temp_leaf()
		missing_pdc = _uniq("PDC-MISSING")
		frappe.db.set_value(
			"Cheque Leaf",
			leaf,
			{
				"status": "Reserved",
				"reserved_by_pdc": missing_pdc,
				"reserved_on": now_datetime(),
				"linked_post_dated_cheque": None,
				"used_on": None,
			},
			update_modified=False,
		)
		action, reason = classify_orphan_leaf_candidate(
			{
				"status": "Reserved",
				"reserved_by_pdc": missing_pdc,
				"linked_post_dated_cheque": None,
				"linked_guarantee_document": None,
			}
		)
		self.assertEqual(action, "release")
		self.assertEqual(reason, "missing_pdc_owner")
		result = release_orphaned_reserved_leaf(leaf)
		self.assertEqual(result["action"], "release")
		row = frappe.db.get_value("Cheque Leaf", leaf, ["status", "reserved_by_pdc", "reserved_on"], as_dict=True)
		self.assertEqual(row.status, "Available")
		self.assertFalse((row.reserved_by_pdc or "").strip())
		self.assertFalse(row.reserved_on)
		# Idempotent
		again = release_orphaned_reserved_leaf(leaf)
		self.assertEqual(again["action"], "skip")

	def test_patch_skips_existing_pdc_and_guarantee_and_used(self):
		leaf = self._temp_leaf()
		# Existing PDC reservation smell — skip.
		existing = frappe.db.get_value("Post Dated Cheque", {}, "name", order_by="creation desc")
		if existing:
			row = {
				"status": "Reserved",
				"reserved_by_pdc": existing,
				"linked_post_dated_cheque": None,
				"linked_guarantee_document": None,
			}
			self.assertEqual(classify_orphan_leaf_candidate(row)[0], "skip")
			self.assertEqual(classify_orphan_leaf_candidate(row)[1], "pdc_still_exists")

		self.assertEqual(
			classify_orphan_leaf_candidate(
				{
					"status": "Reserved",
					"reserved_by_pdc": _uniq("PDC-X"),
					"linked_post_dated_cheque": "PDC-OTHER",
					"linked_guarantee_document": None,
				}
			)[0],
			"skip",
		)
		self.assertEqual(
			classify_orphan_leaf_candidate(
				{
					"status": "Reserved",
					"reserved_by_pdc": _uniq("PDC-X"),
					"linked_post_dated_cheque": None,
					"linked_guarantee_document": "GD-1",
				}
			)[0],
			"skip",
		)
		self.assertEqual(
			classify_orphan_leaf_candidate(
				{
					"status": "Used",
					"reserved_by_pdc": _uniq("PDC-X"),
					"linked_post_dated_cheque": None,
					"linked_guarantee_document": None,
				}
			)[0],
			"skip",
		)
		self.assertEqual(
			classify_orphan_leaf_candidate(
				{
					"status": "Void",
					"reserved_by_pdc": _uniq("PDC-X"),
					"linked_post_dated_cheque": None,
					"linked_guarantee_document": None,
				}
			)[0],
			"skip",
		)

		# Ensure repair runner does not touch existing-PDC reservations.
		if existing:
			frappe.db.set_value(
				"Cheque Leaf",
				leaf,
				{
					"status": "Reserved",
					"reserved_by_pdc": existing,
					"reserved_on": now_datetime(),
					"linked_post_dated_cheque": None,
				},
				update_modified=False,
			)
			before = frappe.db.get_value("Cheque Leaf", leaf, ["status", "reserved_by_pdc"], as_dict=True)
			repair_orphaned_pdc_cheque_leaf_reservations()
			after = frappe.db.get_value("Cheque Leaf", leaf, ["status", "reserved_by_pdc"], as_dict=True)
			self.assertEqual(after.status, before.status)
			self.assertEqual(after.reserved_by_pdc, before.reserved_by_pdc)
			# Cleanup fixture leaf so it does not linger Reserved against a live PDC.
			frappe.db.set_value(
				"Cheque Leaf",
				leaf,
				{"status": "Available", "reserved_by_pdc": None, "reserved_on": None},
				update_modified=False,
			)

	def test_row_lock_helper_used_on_trash_path(self):
		with patch(
			"erpnext_extensions.cheque_management.doctype.post_dated_cheque.post_dated_cheque._pdc_get_cheque_leaf_row_for_update",
			return_value=None,
		) as locked:
			pdc = frappe._dict(name="PDC-X", cheque_leaf="LEAF-X")
			with self.assertRaises(frappe.ValidationError):
				_pdc_assert_and_release_leaf_on_draft_trash("LEAF-X", pdc)
			locked.assert_called()


def cint_docstatus(value) -> int:
	return int(value or 0)
