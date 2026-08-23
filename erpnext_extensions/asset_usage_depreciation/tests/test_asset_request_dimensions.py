# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Unit tests: Asset Request dynamic Accounting Dimensions (v4.5.1)."""

from __future__ import annotations

import unittest

import frappe
from frappe.utils import random_string

from erpnext_extensions.asset_usage_depreciation.services.dimension_service import (
	apply_header_defaults_to_items,
	get_dimension_fieldnames,
	provision_asset_request_accounting_dimensions,
	resolve_item_dimensions,
)
from erpnext_extensions.asset_usage_depreciation.tests import test_helpers as h


class TestAssetRequestDimensions(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")
		cls.skip = h.skip_if_unready()
		if cls.skip:
			return
		h.ensure_settings(
			prevent_duplicate_active_requests=0,
			require_named_manager_approver=0,
			auto_create_material_request=1,
			auto_create_asset_movement=1,
		)
		cls.company = h.company()
		cls.employee = h.make_employee(company_name=cls.company)
		cls.cost_center = h.company_cost_center(cls.company)
		cls.project = h.ensure_project(cls.company)
		cls.dim = h.ensure_test_dimension("AR QA Region")
		cls.fieldname = cls.dim["fieldname"]
		cls.tehran = h.make_dimension_value(cls.dim["doctype"], "AR-QA-Tehran", company=cls.company)
		cls.shiraz = h.make_dimension_value(cls.dim["doctype"], "AR-QA-Shiraz", company=cls.company)

	def _ready(self):
		if getattr(self, "skip", None):
			self.skipTest(self.skip)
		if not self.cost_center:
			self.skipTest("No Cost Center for company")
		if not frappe.get_meta("Asset Request").has_field(self.fieldname):
			self.skipTest(f"Dimension field {self.fieldname} missing on Asset Request")
		if not frappe.get_meta("Asset Request Item").has_field(self.fieldname):
			self.skipTest(f"Dimension field {self.fieldname} missing on Asset Request Item")

	def test_no_hardcoded_dimension_names(self):
		from pathlib import Path

		root = Path(__file__).resolve().parents[1]
		banned = ("business_unit", "division", "territory", "profit_center")
		hits = []
		for path in root.rglob("*"):
			if path.suffix not in {".py", ".js", ".json"}:
				continue
			if "test_asset_request_dimension" in path.name or path.name == "test_helpers.py":
				continue
			text = path.read_text(errors="ignore").lower()
			# Generic metadata helpers may mention the words in comments; flag assignments / if branch.
			if "if branch" in text or "if business_unit" in text:
				hits.append(str(path))
			for token in banned:
				if f'"{token}"' in text or f"'{token}'" in text:
					hits.append(f"{path}:{token}")
		self.assertFalse(hits, f"Hard-coded dimension names: {hits}")

	def test_header_dimension_default_and_new_item_inherits(self):
		self._ready()
		item = h.make_fixed_asset_item()
		header = {self.fieldname: self.tehran, "cost_center": self.cost_center, "project": self.project}
		doc = h.make_request(company_name=self.company, employee=self.employee, item_code=item, **header)
		doc.reload()
		row = doc.items[0]
		self.assertEqual(row.get(self.fieldname), self.tehran)
		self.assertEqual(row.cost_center, self.cost_center)
		self.assertEqual(row.project, self.project)

	def test_empty_item_inherits_header(self):
		self._ready()
		item = h.make_fixed_asset_item()
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			**{self.fieldname: self.tehran, "cost_center": self.cost_center},
		)
		doc.items[0].set(self.fieldname, None)
		doc.items[0].cost_center = None
		apply_header_defaults_to_items(doc, only_empty=True)
		self.assertEqual(doc.items[0].get(self.fieldname), self.tehran)
		self.assertEqual(doc.items[0].cost_center, self.cost_center)

	def test_item_override_wins(self):
		self._ready()
		item = h.make_fixed_asset_item()
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			extra_item={self.fieldname: self.shiraz, "cost_center": self.cost_center},
			**{self.fieldname: self.tehran, "cost_center": self.cost_center},
		)
		doc.reload()
		self.assertEqual(doc.get(self.fieldname), self.tehran)
		self.assertEqual(doc.items[0].get(self.fieldname), self.shiraz)
		resolved = resolve_item_dimensions(doc, doc.items[0])
		self.assertEqual(resolved.get(self.fieldname), self.shiraz)

	def test_header_change_does_not_overwrite_item_override(self):
		self._ready()
		item = h.make_fixed_asset_item()
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			extra_item={self.fieldname: self.shiraz},
			**{self.fieldname: self.tehran},
		)
		doc.set(self.fieldname, self.tehran)
		apply_header_defaults_to_items(doc, only_empty=True)
		self.assertEqual(doc.items[0].get(self.fieldname), self.shiraz)
		doc.set(self.fieldname, self.tehran)
		doc.save(ignore_permissions=True)
		doc.reload()
		self.assertEqual(doc.items[0].get(self.fieldname), self.shiraz)

	def test_generic_dynamic_dimension_support(self):
		self._ready()
		self.assertIn(self.fieldname, get_dimension_fieldnames())
		self.assertTrue(frappe.get_meta("Asset Request").has_field("accounting_dimensions_section"))
		self.assertTrue(frappe.get_meta("Asset Request Item").has_field("accounting_dimensions_section"))

	def test_wrong_company_dimension_rejected(self):
		self._ready()
		other = h.other_company(self.company)
		if not other:
			self.skipTest("Need a second Company for cross-company validation")
		other_cc = h.company_cost_center(other)
		if not other_cc:
			self.skipTest("No Cost Center on second company")
		item = h.make_fixed_asset_item()
		with self.assertRaises(frappe.ValidationError):
			h.make_request(
				company_name=self.company,
				employee=self.employee,
				item_code=item,
				cost_center=other_cc,
			)

	def test_disabled_dimension_handled_like_native(self):
		self._ready()
		disabled = h.make_dimension_value(
			self.dim["doctype"], "AR-QA-Disabled", company=self.company, disabled=1
		)
		item = h.make_fixed_asset_item()
		# Native Material Request does not extra-reject disabled values on save.
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			**{self.fieldname: disabled},
		)
		self.assertEqual(doc.get(self.fieldname), disabled)

	def test_cost_center_and_project_company_validation(self):
		self._ready()
		item = h.make_fixed_asset_item()
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=item,
			cost_center=self.cost_center,
			project=self.project,
		)
		self.assertEqual(doc.cost_center, self.cost_center)
		self.assertEqual(doc.items[0].cost_center, self.cost_center)
		self.assertEqual(doc.items[0].project, self.project)

	def test_mandatory_for_pl_bs_does_not_block_asset_request(self):
		self._ready()
		dim = frappe.get_doc("Accounting Dimension", {"document_type": self.dim["doctype"]})
		created_default = False
		prev_pl = prev_bs = None
		if not dim.dimension_defaults:
			dim.append(
				"dimension_defaults",
				{"company": self.company, "mandatory_for_pl": 1, "mandatory_for_bs": 1},
			)
			created_default = True
		else:
			prev_pl = dim.dimension_defaults[0].mandatory_for_pl
			prev_bs = dim.dimension_defaults[0].mandatory_for_bs
			dim.dimension_defaults[0].mandatory_for_pl = 1
			dim.dimension_defaults[0].mandatory_for_bs = 1
		dim.save()
		try:
			item = h.make_fixed_asset_item()
			doc = h.make_request(company_name=self.company, employee=self.employee, item_code=item)
			# Empty dynamic dimension must not block save or approval.
			h.submit_and_approve(doc)
			doc.reload()
			self.assertEqual(int(doc.docstatus or 0), 1)
		finally:
			dim.reload()
			if created_default and dim.dimension_defaults:
				dim.dimension_defaults = []
			elif dim.dimension_defaults:
				dim.dimension_defaults[0].mandatory_for_pl = prev_pl or 0
				dim.dimension_defaults[0].mandatory_for_bs = prev_bs or 0
			dim.save()

	def test_substitution_preserves_line_dimensions(self):
		self._ready()
		tag = random_string(6)
		samsung = h.make_fixed_asset_item(code=f"AUD-AR-DIM-S-{tag}", title="Samsung Dim")
		lg = h.make_fixed_asset_item(code=f"AUD-AR-DIM-L-{tag}", title="LG Dim")
		doc = h.make_request(
			company_name=self.company,
			employee=self.employee,
			item_code=samsung,
			fulfilled_item_code=lg,
			substitution_reason="Standardized on LG",
			extra_item={self.fieldname: self.tehran, "cost_center": self.cost_center},
			**{self.fieldname: self.shiraz, "cost_center": self.cost_center},
		)
		doc.reload()
		self.assertEqual(doc.items[0].requested_item_code, samsung)
		self.assertEqual(doc.items[0].fulfilled_item_code, lg)
		self.assertEqual(doc.items[0].get(self.fieldname), self.tehran)
		self.assertEqual(doc.items[0].cost_center, self.cost_center)

	def test_provision_is_idempotent(self):
		self._ready()
		before = frappe.db.count("Custom Field", {"dt": ["in", ["Asset Request", "Asset Request Item"]]})
		provision_asset_request_accounting_dimensions()
		provision_asset_request_accounting_dimensions()
		after = frappe.db.count("Custom Field", {"dt": ["in", ["Asset Request", "Asset Request Item"]]})
		self.assertGreaterEqual(after, before)
		# Same fieldname must not duplicate.
		rows = frappe.get_all(
			"Custom Field",
			filters={"dt": "Asset Request", "fieldname": self.fieldname},
			pluck="name",
		)
		self.assertEqual(len(rows), 1, rows)
