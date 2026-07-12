# Copyright (c) 2026, Farbod Siyahpoosh and contributors

from __future__ import annotations

import json
import unittest

import frappe

from erpnext_extensions.iran_accounting.account_explorer import saved_views
from erpnext_extensions.iran_accounting.tests.test_account_explorer_fixtures import (
	current_fiscal_year,
	default_document_scope,
	enable_saved_views,
	enable_wave2a_analysis,
	require_site,
)


def _sample_view_payload(company, fiscal_year, from_date, to_date, view_name="Monthly Review"):
	document_scope = default_document_scope(company, fiscal_year, from_date, to_date)
	document_scope["voucher"] = {"voucher_type": "Journal Entry", "voucher_no": "JV-0001"}
	return {
		"view_name": view_name,
		"company": company,
		"document_scope": document_scope,
		"analysis_context": {
			"view_axis": "account_level",
			"level_sequence": 1,
			"sort_field": "display_code",
			"sort_order": "asc",
			"page_size": 50,
		},
		"presentation": {
			"schema_version": 1,
			"visible_columns": ["display_code", "display_title"],
			"sort_field": "display_code",
			"sort_order": "asc",
			"page_size": 50,
			"show_optional_full_voucher_columns": 0,
		},
	}


class TestAccountExplorerSavedViews(unittest.TestCase):
	def setUp(self):
		self.company = require_site(self)
		enable_wave2a_analysis()
		enable_saved_views()
		frappe.set_user("Administrator")
		fy = current_fiscal_year(self.company)
		if not fy:
			self.skipTest("No fiscal year")
		self.fiscal_year, self.from_date, self.to_date = fy
		self.created_views: list[str] = []

	def tearDown(self):
		frappe.set_user("Administrator")
		for name in self.created_views:
			if frappe.db.exists("Account Explorer Saved View", name):
				frappe.delete_doc("Account Explorer Saved View", name, force=1)
		frappe.db.commit()

	def test_save_list_get_delete_saved_view(self):
		payload = _sample_view_payload(
			self.company, self.fiscal_year, self.from_date, self.to_date, "Monthly Review"
		)
		saved = saved_views.save_saved_view(json.dumps(payload))
		self.created_views.append(saved["name"])
		self.assertEqual(saved["view_name"], "Monthly Review")
		self.assertEqual(saved["company"], self.company)

		views = saved_views.list_saved_views(company=self.company)
		self.assertTrue(any(row["name"] == saved["name"] for row in views))

		loaded = saved_views.get_saved_view(saved["name"])
		self.assertEqual(loaded["document_scope"]["company"], self.company)
		self.assertEqual(loaded["analysis_context"]["view_axis"], "account_level")
		self.assertEqual(loaded["presentation"]["sort_field"], "display_code")

		result = saved_views.delete_saved_view(saved["name"])
		self.assertTrue(result["ok"])
		self.created_views.remove(saved["name"])

	def test_save_updates_existing_view_name_for_owner(self):
		payload = _sample_view_payload(
			self.company, self.fiscal_year, self.from_date, self.to_date, "Supplier Review"
		)
		first = saved_views.save_saved_view(json.dumps(payload))
		self.created_views.append(first["name"])

		payload["analysis_context"]["view_axis"] = "party"
		second = saved_views.save_saved_view(json.dumps(payload))
		self.assertEqual(first["name"], second["name"])
		self.assertEqual(second["analysis_context"]["view_axis"], "party")

	def test_rejects_calculated_data_in_configuration(self):
		payload = _sample_view_payload(
			self.company, self.fiscal_year, self.from_date, self.to_date, "Invalid View"
		)
		payload["document_scope"]["rows"] = [{"display_code": "1001"}]
		with self.assertRaises(frappe.ValidationError):
			saved_views.save_saved_view(json.dumps(payload))

	def test_other_user_cannot_read_owner_view(self):
		payload = _sample_view_payload(
			self.company, self.fiscal_year, self.from_date, self.to_date, "Private View"
		)
		saved = saved_views.save_saved_view(json.dumps(payload))
		self.created_views.append(saved["name"])

		other_user = self._ensure_other_user()
		frappe.set_user(other_user)
		with self.assertRaises(frappe.PermissionError):
			saved_views.get_saved_view(saved["name"])

	def test_saved_views_disabled_blocks_save(self):
		settings = frappe.get_single("Iran Accounting Settings")
		settings.saved_views_enabled = 0
		settings.flags.ignore_permissions = True
		settings.save()
		frappe.db.commit()

		payload = _sample_view_payload(
			self.company, self.fiscal_year, self.from_date, self.to_date, "Disabled View"
		)
		with self.assertRaises(frappe.ValidationError):
			saved_views.save_saved_view(json.dumps(payload))

		enable_saved_views()

	def _ensure_other_user(self) -> str:
		email = "ae_saved_view_other@example.com"
		if not frappe.db.exists("User", email):
			user = frappe.new_doc("User")
			user.email = email
			user.first_name = "AE"
			user.last_name = "Other"
			user.send_welcome_email = 0
			user.add_roles("Accounts User")
			user.flags.ignore_permissions = True
			user.insert()
		return email
