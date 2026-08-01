# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company
from erpnext_extensions.consignment_stock.tests.helpers import ensure_module_ready, ensure_settings
from erpnext_extensions.patches.post_model_sync.remove_obsolete_consignment_settings_fields import (
	OBSOLETE_SETTINGS_FIELDS,
	execute as run_cleanup_patch,
)


class TestConsignmentSettingsMigration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		cls.company = get_irr_company("ESPAD")
		cls.settings_name = ensure_settings(cls.company)

	def test_obsolete_fields_absent_from_meta(self):
		meta = frappe.get_meta("Consignment Stock Settings")
		fieldnames = {f.fieldname for f in meta.fields}
		for fn in OBSOLETE_SETTINGS_FIELDS:
			self.assertNotIn(fn, fieldnames)

	def test_settings_document_preserved(self):
		self.assertTrue(frappe.db.exists("Consignment Stock Settings", self.settings_name))
		doc = frappe.get_doc("Consignment Stock Settings", self.settings_name)
		self.assertEqual(doc.company, self.company)
		self.assertTrue(doc.consignment_temporary_clearing_account)
		self.assertTrue(doc.consignment_valuation_difference_account)

	def test_cleanup_patch_idempotent(self):
		run_cleanup_patch()
		run_cleanup_patch()
		self.assertTrue(frappe.db.exists("Consignment Stock Settings", self.settings_name))
		for fn in OBSOLETE_SETTINGS_FIELDS:
			self.assertFalse(
				frappe.db.exists(
					"Custom Field", {"dt": "Consignment Stock Settings", "fieldname": fn}
				)
			)
			self.assertFalse(
				frappe.db.exists("DocField", {"parent": "Consignment Stock Settings", "fieldname": fn})
			)
			self.assertFalse(frappe.db.has_column("Consignment Stock Settings", fn))
