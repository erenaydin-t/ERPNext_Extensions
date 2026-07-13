# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	create_test_unified_accounting_party,
	delete_test_unified_accounting_party,
	enable_wave2c_unified_party,
	require_site,
)


class TestUnifiedAccountingParty(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2c_unified_party()
		frappe.set_user("Administrator")
		self.created_uaps: list[str] = []

	def tearDown(self):
		for name in reversed(self.created_uaps):
			delete_test_unified_accounting_party(name)

	def _customer_with_gl(self) -> str | None:
		row = frappe.db.sql(
			"""
			select distinct party
			from `tabGL Entry`
			where company=%s and party_type='Customer' and party!='' and is_cancelled=0
			limit 1
			""",
			self.company,
		)
		return row[0][0] if row else None

	def test_create_global_uap(self):
		customer = self._customer_with_gl()
		if not customer:
			self.skipTest("No customer GL activity")
		name = create_test_unified_accounting_party([("Customer", customer)])
		self.created_uaps.append(name)
		doc = frappe.get_doc("Unified Accounting Party", name)
		self.assertEqual(doc.status, "Active")
		self.assertEqual(doc.member_count, 1)
		self.assertEqual(len(doc.members), 1)
		self.assertEqual(doc.members[0].party_type, "Customer")

	def test_duplicate_member_rejected(self):
		customers = frappe.db.sql(
			"""
			select distinct party
			from `tabGL Entry`
			where company=%s and party_type='Customer' and party!='' and is_cancelled=0
			limit 2
			""",
			self.company,
		)
		if len(customers) < 1:
			self.skipTest("No customer GL activity")
		customer = customers[0][0]
		first = create_test_unified_accounting_party([("Customer", customer)], unified_name="UAP A")
		self.created_uaps.append(first)
		doc = frappe.new_doc("Unified Accounting Party")
		doc.unified_name = "UAP B"
		doc.status = "Active"
		doc.append("members", {"party_type": "Customer", "party": customer, "is_primary": 1})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()

	def test_inactive_uap_allows_member_reuse(self):
		customer = self._customer_with_gl()
		if not customer:
			self.skipTest("No customer GL activity")
		first = create_test_unified_accounting_party([("Customer", customer)], unified_name="UAP Inactive")
		self.created_uaps.append(first)
		doc = frappe.get_doc("Unified Accounting Party", first)
		doc.status = "Inactive"
		doc.flags.ignore_permissions = True
		doc.save()
		frappe.db.commit()
		second = create_test_unified_accounting_party([("Customer", customer)], unified_name="UAP Reuse")
		self.created_uaps.append(second)

	def test_party_type_must_be_enabled_for_unified_party(self):
		customer = frappe.db.get_value("Customer", {}, "name")
		if not customer:
			self.skipTest("No customer")
		settings = frappe.get_single("Iran Accounting Settings")
		for row in settings.account_explorer_party_sources or []:
			if row.party_type == "Customer":
				row.show_in_unified_party = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()
		doc = frappe.new_doc("Unified Accounting Party")
		doc.unified_name = "Blocked Type"
		doc.status = "Active"
		doc.append("members", {"party_type": "Customer", "party": customer, "is_primary": 1})
		with self.assertRaises(frappe.ValidationError):
			doc.insert()
		enable_wave2c_unified_party()
