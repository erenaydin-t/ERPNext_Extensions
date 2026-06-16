# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest
from unittest import mock

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_settings_doc import (
	apply_facility_settings_defaults,
	get_facility_settings_defaults_payload,
)


class TestApplyFacilitySettingsDefaultsUnit(unittest.TestCase):
	def test_fills_empty_fields_only(self):
		class Settings:
			def get(self, k):
				return {
					"default_bank_account": "BANK-GL",
					"default_loan_payable_account": "LOAN-GL",
				}.get(k)

		class Doc:
			company = "C1"

			def __init__(self):
				self._data = {"loan_payable_account": "USER-LOAN"}

			def get(self, k):
				if k == "company":
					return self.company
				return self._data.get(k)

			def set(self, k, v):
				self._data[k] = v

		doc = Doc()
		with mock.patch(
			"erpnext_extensions.facility_management.facility_settings_doc.get_facility_settings_doc",
			return_value=Settings(),
		):
			result = apply_facility_settings_defaults(doc, overwrite=False)
		self.assertIn("bank_account", result["applied"])
		self.assertNotIn("loan_payable_account", result["applied"])
		self.assertEqual(doc.get("bank_account"), "BANK-GL")
		self.assertEqual(doc.get("loan_payable_account"), "USER-LOAN")

	def test_no_settings_no_crash(self):
		class Doc:
			company = "Missing Co"

			def get(self, k):
				if k == "company":
					return self.company
				return None

			def set(self, k, v):
				pass

		with mock.patch(
			"erpnext_extensions.facility_management.facility_settings_doc.get_facility_settings_doc",
			return_value=None,
		):
			result = apply_facility_settings_defaults(Doc(), overwrite=False)
		self.assertTrue(result["missing_settings"])
		self.assertEqual(result["applied"], [])

	def test_payload_when_missing(self):
		payload = get_facility_settings_defaults_payload("__no_such_company__")
		self.assertFalse(payload["found"])
		self.assertIn("message", payload)


class TestFacilityDefaultsIntegration(unittest.TestCase):
	def test_validate_fills_missing_from_settings(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		self.assertTrue(company)
		fs_name = frappe.db.get_value("Facility Settings", {"company": company}, "name")
		self.assertTrue(fs_name, "Facility Settings required for integration test")
		fs = frappe.get_doc("Facility Settings", fs_name)
		bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")

		doc = frappe.new_doc("Facility")
		doc.facility_name = f"Defaults Test {random_string(5)}"
		doc.company = company
		doc.bank = bank
		doc.contract_date = today()
		doc.principal_amount = 1000
		doc.profit_amount = 100
		doc.is_opening_facility = 1
		for method in (
			"_validate_accounts",
			"_validate_installment_count",
			"_validate_opening_amounts",
			"_validate_status_rules",
			"_sync_balance_fields",
		):
			setattr(doc, method, lambda *args, **kwargs: None)
		doc.validate()

		self.assertEqual(doc.bank_account, fs.default_bank_account)
		self.assertEqual(doc.loan_payable_account, fs.default_loan_payable_account)

	def test_validate_does_not_overwrite_user_values(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		fs_name = frappe.db.get_value("Facility Settings", {"company": company}, "name")
		fs = frappe.get_doc("Facility Settings", fs_name)
		bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
		override_bank = frappe.db.get_value(
			"Account",
			{"company": company, "account_type": "Bank", "is_group": 0, "name": ("!=", fs.default_bank_account)},
			"name",
		) or fs.default_bank_account

		doc = frappe.new_doc("Facility")
		doc.facility_name = f"Override Test {random_string(5)}"
		doc.company = company
		doc.bank = bank
		doc.contract_date = today()
		doc.principal_amount = 1000
		doc.profit_amount = 100
		doc.is_opening_facility = 1
		doc.bank_account = override_bank
		for method in (
			"_validate_accounts",
			"_validate_installment_count",
			"_validate_opening_amounts",
			"_validate_status_rules",
			"_sync_balance_fields",
		):
			setattr(doc, method, lambda *args, **kwargs: None)
		doc.validate()
		self.assertEqual(doc.bank_account, override_bank)
		if fs.default_loan_payable_account:
			self.assertEqual(doc.loan_payable_account, fs.default_loan_payable_account)

	def test_company_change_leaves_filled_fields(self):
		class Doc:
			company = "C1"

			def __init__(self):
				self._data = {"bank_account": "KEPT"}

			def get(self, k):
				if k == "company":
					return self.company
				return self._data.get(k)

			def set(self, k, v):
				self._data[k] = v

		class Settings:
			def get(self, k):
				return {"default_bank_account": "NEW-DEFAULT"}.get(k)

		doc = Doc()
		with mock.patch(
			"erpnext_extensions.facility_management.facility_settings_doc.get_facility_settings_doc",
			return_value=Settings(),
		):
			apply_facility_settings_defaults(doc, overwrite=False)
		self.assertEqual(doc.get("bank_account"), "KEPT")
