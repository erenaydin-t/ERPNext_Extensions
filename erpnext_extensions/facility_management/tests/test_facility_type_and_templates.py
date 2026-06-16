# Copyright (c) 2026, ERPNext Extensions contributors

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string, today

from erpnext_extensions.facility_management.facility_accounting import (
	build_receipt_je_plan,
	preview_receipt_journal_entry,
)
from erpnext_extensions.facility_management.facility_queries import facility_type_link_query
from erpnext_extensions.facility_management.facility_settings_doc import (
	DEFAULT_RECEIPT_BANK_ROW,
	FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS,
	migrate_facility_settings_templates_to_facility_name,
)
from erpnext_extensions.facility_management.facility_templates import (
	build_template_context,
	render_facility_template,
)
from erpnext_extensions.facility_management.facility_type_data import (
	DEFAULT_FACILITY_TYPES,
	ensure_default_facility_types,
	ensure_facility_type,
)


class TestFacilityTypeDocType(unittest.TestCase):
	def test_doctype_exists(self):
		meta = frappe.get_meta("Facility Type")
		self.assertEqual(meta.autoname, "field:facility_type_name")
		df = meta.get_field("facility_type_name")
		self.assertTrue(df.unique)
		self.assertTrue(df.reqd)

	def test_facility_link_field(self):
		df = frappe.get_meta("Facility").get_field("facility_type")
		self.assertEqual(df.fieldtype, "Link")
		self.assertEqual(df.options, "Facility Type")

	def test_default_types_created(self):
		frappe.set_user("Administrator")
		ensure_default_facility_types()
		for label in DEFAULT_FACILITY_TYPES:
			self.assertTrue(frappe.db.exists("Facility Type", label))

	def test_migrate_legacy_select_value(self):
		frappe.set_user("Administrator")
		label = f"نوع قدیمی {random_string(4)}"
		ensure_facility_type(label)
		self.assertTrue(frappe.db.exists("Facility Type", label))

	def test_disabled_excluded_from_link_query(self):
		frappe.set_user("Administrator")
		name = f"غیرفعال {random_string(4)}"
		doc = frappe.new_doc("Facility Type")
		doc.facility_type_name = name
		doc.disabled = 1
		doc.insert(ignore_permissions=True)
		frappe.db.commit()
		rows = facility_type_link_query("Facility Type", name[:4], "name", 0, 20, {})
		names = [r[0] for r in rows]
		self.assertNotIn(doc.name, names)


class TestTemplateFacilityName(unittest.TestCase):
	def test_defaults_use_facility_name_placeholder(self):
		for val in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.values():
			self.assertIn("{facility_name}", val)
			self.assertNotIn("{facility_number}", val)

	def test_legacy_defaults_migrate(self):
		doc = frappe._dict(
			{fn: LEGACY_FACILITY_SETTINGS_TEMPLATE_DEFAULTS[fn] for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS}
		)
		self.assertTrue(migrate_facility_settings_templates_to_facility_name(doc))
		for fn, new in FACILITY_SETTINGS_TEMPLATE_DEFAULTS.items():
			self.assertEqual(doc.get(fn), new)

	def test_custom_template_preserved(self):
		custom = "پرداخت وام شرکت فلان - {facility_number}"
		doc = frappe._dict({fn: FACILITY_SETTINGS_TEMPLATE_DEFAULTS[fn] for fn in FACILITY_SETTINGS_TEMPLATE_DEFAULTS})
		doc.default_repayment_remarks_template = custom
		self.assertFalse(migrate_facility_settings_templates_to_facility_name(doc))
		self.assertEqual(doc.default_repayment_remarks_template, custom)

	def test_renderer_uses_facility_name(self):
		class Fac:
			name = "FAC-001"
			facility_name = "وام سرمایه در گردش نمونه"
			company = "C"
			bank = "B"
			principal_amount = 100
			profit_amount = 0
			total_liability_amount = 100
			contract_date = today()
			receive_date = today()

			def get(self, k, default=None):
				return getattr(self, k, default)

		ctx = build_template_context(Fac())
		out = render_facility_template(DEFAULT_RECEIPT_BANK_ROW, ctx)
		self.assertIn("وام سرمایه در گردش نمونه", out)
		self.assertNotIn("FAC-001", out)

	def test_renderer_fallback_when_name_empty(self):
		class Fac:
			name = "FAC-002"
			facility_name = ""
			company = "C"
			bank = "B"
			principal_amount = 100
			profit_amount = 0
			total_liability_amount = 100
			contract_date = today()
			receive_date = today()

			def get(self, k, default=None):
				return getattr(self, k, default)

		ctx = build_template_context(Fac())
		out = render_facility_template(DEFAULT_RECEIPT_BANK_ROW, ctx)
		self.assertIn("FAC-002", out)

	def test_receipt_preview_row_descriptions_use_facility_name(self):
		frappe.set_user("Administrator")
		company = frappe.db.get_value("Company", {}, "name", order_by="creation asc")
		from erpnext_extensions.facility_management.facility_settings_doc import get_facility_settings_doc

		settings = get_facility_settings_doc(company)
		bank = frappe.db.get_value("Bank", {}, "name", order_by="creation asc")
		fac = frappe.new_doc("Facility")
		fac.facility_name = "وام سرمایه در گردش نمونه"
		fac.company = company
		fac.bank = bank
		fac.contract_date = today()
		fac.receive_date = today()
		fac.principal_amount = 8000
		fac.profit_amount = 1000
		for fn in (
			"default_bank_account",
			"default_loan_payable_account",
			"default_deferred_loan_interest_account",
		):
			if settings and settings.get(fn):
				fac.set(fn.replace("default_", ""), settings.get(fn))
		fac.insert(ignore_permissions=True)
		frappe.db.commit()
		prev = preview_receipt_journal_entry(fac)
		remarks = " ".join((r.get("user_remark") or "") for r in prev["rows"])
		self.assertIn("وام سرمایه در گردش نمونه", remarks)
		plan = build_receipt_je_plan(fac)
		self.assertTrue(plan)
