# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Migration / schema verification for Asset Request v4.4.0 (idempotent)."""

from __future__ import annotations

import unittest

import frappe

from erpnext_extensions.asset_usage_depreciation.constants import (
	ASSET_REQUEST_ALLOCATION_DOCTYPE,
	ASSET_REQUEST_DOCTYPE,
	ASSET_REQUEST_ITEM_DOCTYPE,
	ASSET_REQUEST_SETTINGS_DOCTYPE,
	COMPANY_FIELD_AR_CEO_MIN_QTY,
	COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION,
	COMPANY_FIELD_AR_POOL_LOCATION,
	COMPANY_FIELD_AR_REQUIRE_CEO,
	COMPANY_FIELD_AR_REQUIRE_PLANNING,
	ROLE_AR_EXECUTIVE,
	ROLE_AR_MANAGER,
	ROLE_AR_PLANNER,
	ROLE_ASSET_MANAGER,
	WF_ASSET_REQUEST,
)
from erpnext_extensions.asset_usage_depreciation.custom_fields import ensure_custom_fields
from erpnext_extensions.asset_usage_depreciation.workflow import ensure_asset_request_workflow


def _count(doctype: str, filters: dict) -> int:
	return len(frappe.get_all(doctype, filters=filters, pluck="name"))


class TestAssetRequestMigration(unittest.TestCase):
	@classmethod
	def setUpClass(cls):
		frappe.set_user("Administrator")

	def test_doctypes_exist(self):
		for dt in (
			ASSET_REQUEST_DOCTYPE,
			ASSET_REQUEST_ITEM_DOCTYPE,
			ASSET_REQUEST_ALLOCATION_DOCTYPE,
			ASSET_REQUEST_SETTINGS_DOCTYPE,
		):
			self.assertTrue(frappe.db.exists("DocType", dt), dt)

	def test_company_and_material_request_custom_fields(self):
		for field in (
			COMPANY_FIELD_AR_REQUIRE_PLANNING,
			COMPANY_FIELD_AR_REQUIRE_CEO,
			COMPANY_FIELD_AR_CEO_MIN_QTY,
			COMPANY_FIELD_AR_POOL_LOCATION,
			COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION,
		):
			self.assertTrue(frappe.db.has_column("Company", field), field)
		self.assertTrue(frappe.db.has_column("Material Request", "custom_asset_request"))
		self.assertTrue(frappe.db.has_column("Material Request", "custom_created_from_asset_request"))
		self.assertTrue(frappe.db.has_column("Material Request Item", "custom_asset_request_item"))

	def test_roles_and_workflow(self):
		for role in (ROLE_AR_MANAGER, ROLE_AR_PLANNER, ROLE_AR_EXECUTIVE, ROLE_ASSET_MANAGER):
			self.assertTrue(frappe.db.exists("Role", role), role)
		self.assertTrue(frappe.db.exists("Workflow", WF_ASSET_REQUEST))
		wf = frappe.get_doc("Workflow", WF_ASSET_REQUEST)
		self.assertEqual(wf.document_type, ASSET_REQUEST_DOCTYPE)
		self.assertEqual(cint_active(wf), 1)
		states = {s.state for s in wf.states}
		self.assertIn("Pending Manager Approval", states)
		self.assertIn("Approved", states)
		self.assertFalse(frappe.get_meta(ASSET_REQUEST_DOCTYPE).has_field("request_type"))

	def test_asset_manager_has_fulfillment_permlevel(self):
		meta = frappe.get_meta(ASSET_REQUEST_DOCTYPE)
		pl1 = [p for p in meta.permissions if p.role == ROLE_ASSET_MANAGER and int(p.permlevel or 0) == 1]
		self.assertTrue(pl1, "Asset Manager must have permlevel 1 write for fulfillment")
		self.assertTrue(any(int(p.read) and int(p.write) for p in pl1))

	def test_ensure_hooks_are_idempotent(self):
		before_cf = _count("Custom Field", {"fieldname": "custom_asset_request"})
		before_wf = _count("Workflow", {"workflow_name": WF_ASSET_REQUEST})
		before_roles = {r: _count("Role", {"role_name": r}) for r in (ROLE_AR_MANAGER, ROLE_ASSET_MANAGER)}
		ensure_custom_fields()
		ensure_asset_request_workflow()
		ensure_custom_fields()
		ensure_asset_request_workflow()
		self.assertEqual(_count("Custom Field", {"fieldname": "custom_asset_request"}), before_cf)
		self.assertEqual(_count("Workflow", {"workflow_name": WF_ASSET_REQUEST}), before_wf)
		for role, n in before_roles.items():
			self.assertEqual(_count("Role", {"role_name": role}), n, role)
		self.assertEqual(before_wf, 1)
		self.assertEqual(before_cf, 1)


def cint_active(wf) -> int:
	from frappe.utils import cint

	return cint(wf.is_active)
