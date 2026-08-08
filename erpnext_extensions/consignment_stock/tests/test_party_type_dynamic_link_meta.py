# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import unittest

import frappe
from frappe.core.doctype.doctype.doctype import validate_fields_for_doctype
from frappe.custom.doctype.custom_field.custom_field import create_custom_field

from erpnext_extensions.consignment_stock.constants import (
	ALLOWED_PARTY_TYPES,
	F_PARTY,
	F_PARTY_TYPE,
)
from erpnext_extensions.consignment_stock.material_loan.constants import (
	ALLOWED_PARTY_TYPES as ML_ALLOWED_PARTY_TYPES,
)
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_PARTY as ML_PARTY,
)
from erpnext_extensions.consignment_stock.material_loan.constants import (
	F_PARTY_TYPE as ML_PARTY_TYPE,
)
from erpnext_extensions.consignment_stock.material_loan.party_account import validate_party_for_tracking
from erpnext_extensions.consignment_stock.party import validate_consignment_party
from erpnext_extensions.consignment_stock.party_type_meta import (
	STOCK_ENTRY_PARTY_TYPE_FIELDS,
	repair_stock_entry_party_type_link_options,
)
from erpnext_extensions.consignment_stock.tests.helpers import (
	ensure_customer,
	ensure_module_ready,
	ensure_settings,
	ensure_supplier,
)
from erpnext_extensions.consignment_stock.tests.material_loan_helpers import ensure_material_loan_ready
from erpnext_extensions.iran_accounting.e2e_bootstrap import get_irr_company


class TestStockEntryPartyTypeDynamicLinkMeta(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		ensure_module_ready()
		ensure_material_loan_ready()
		cls.company = get_irr_company("ESPAD")
		ensure_settings(cls.company)
		cls.supplier = ensure_supplier(cls.company)
		cls.customer = ensure_customer(cls.company)

	def test_validate_fields_for_stock_entry_passes(self):
		validate_fields_for_doctype("Stock Entry")

	def test_party_type_controllers_are_link_doctype(self):
		meta = frappe.get_meta("Stock Entry", cached=False)
		for fieldname in (F_PARTY_TYPE, ML_PARTY_TYPE):
			df = meta.get_field(fieldname)
			self.assertIsNotNone(df, fieldname)
			self.assertEqual(df.fieldtype, "Link", fieldname)
			self.assertEqual(df.options, "DocType", fieldname)

	def test_dynamic_link_controllers_valid(self):
		meta = frappe.get_meta("Stock Entry", cached=False)
		for party_field, type_field in ((F_PARTY, F_PARTY_TYPE), (ML_PARTY, ML_PARTY_TYPE)):
			df = meta.get_field(party_field)
			self.assertEqual(df.fieldtype, "Dynamic Link", party_field)
			self.assertEqual(df.options, type_field, party_field)
			controller = meta.get_field(type_field)
			self.assertEqual(controller.fieldtype, "Link")
			self.assertEqual(controller.options, "DocType")

	def test_consignment_customer_and_supplier_allowed(self):
		self.assertIn("Customer", ALLOWED_PARTY_TYPES)
		self.assertIn("Supplier", ALLOWED_PARTY_TYPES)
		validate_consignment_party("Customer", self.customer, self.company)
		validate_consignment_party("Supplier", self.supplier, self.company)

	def test_material_loan_customer_and_supplier_allowed(self):
		self.assertEqual(ML_ALLOWED_PARTY_TYPES, ("Customer", "Supplier"))
		validate_party_for_tracking("Customer", self.customer)
		validate_party_for_tracking("Supplier", self.supplier)

	def test_item_rejected_as_party_type(self):
		with self.assertRaises(frappe.ValidationError):
			validate_consignment_party("Item", "X", self.company)
		with self.assertRaises(frappe.ValidationError):
			validate_party_for_tracking("Item", "X")

	def test_warehouse_rejected_as_party_type(self):
		with self.assertRaises(frappe.ValidationError):
			validate_consignment_party("Warehouse", "X", self.company)
		with self.assertRaises(frappe.ValidationError):
			validate_party_for_tracking("Warehouse", "X")

	def test_unrelated_custom_field_can_be_saved(self):
		"""Simulate Customize Form / Custom Field save on Stock Entry."""
		fieldname = "custom_ee_dynlink_meta_probe"
		existing = frappe.db.get_value(
			"Custom Field", {"dt": "Stock Entry", "fieldname": fieldname}, "name"
		)
		if existing:
			frappe.delete_doc("Custom Field", existing, force=True)

		create_custom_field(
			"Stock Entry",
			{
				"fieldname": fieldname,
				"label": "EE Dynlink Meta Probe",
				"fieldtype": "Data",
				"insert_after": "remarks",
			},
			ignore_validate=False,
		)
		# on_update validates whole Stock Entry meta — must not raise Dynamic Link error
		validate_fields_for_doctype("Stock Entry")
		name = frappe.db.get_value(
			"Custom Field", {"dt": "Stock Entry", "fieldname": fieldname}, "name"
		)
		self.assertTrue(name)
		frappe.delete_doc("Custom Field", name, force=True)
		frappe.clear_cache(doctype="Stock Entry")

	def test_customize_form_validate_stock_entry(self):
		"""Original production failure mode: Customize Form validates Stock Entry meta."""
		validate_fields_for_doctype("Stock Entry")

	def test_repair_preserves_party_values_and_is_idempotent(self):
		# Snapshot existing document values (if any)
		before = frappe.db.sql(
			"""
			select name, custom_consignment_party_type, custom_material_loan_party_type
			from `tabStock Entry`
			where ifnull(custom_consignment_party_type, '') != ''
			   or ifnull(custom_material_loan_party_type, '') != ''
			order by name
			limit 20
			""",
			as_dict=True,
		)

		# Force invalid options, then repair twice
		for fieldname in STOCK_ENTRY_PARTY_TYPE_FIELDS:
			cf = frappe.db.get_value(
				"Custom Field", {"dt": "Stock Entry", "fieldname": fieldname}, "name"
			)
			self.assertTrue(cf, fieldname)
			frappe.db.set_value("Custom Field", cf, "options", "Party Type", update_modified=False)

		frappe.clear_cache(doctype="Stock Entry")
		self.assertTrue(repair_stock_entry_party_type_link_options())
		self.assertFalse(repair_stock_entry_party_type_link_options())

		for fieldname in STOCK_ENTRY_PARTY_TYPE_FIELDS:
			options = frappe.db.get_value(
				"Custom Field",
				{"dt": "Stock Entry", "fieldname": fieldname},
				"options",
			)
			self.assertEqual(options, "DocType", fieldname)

		after = frappe.db.sql(
			"""
			select name, custom_consignment_party_type, custom_material_loan_party_type
			from `tabStock Entry`
			where ifnull(custom_consignment_party_type, '') != ''
			   or ifnull(custom_material_loan_party_type, '') != ''
			order by name
			limit 20
			""",
			as_dict=True,
		)
		self.assertEqual(before, after)
		validate_fields_for_doctype("Stock Entry")
