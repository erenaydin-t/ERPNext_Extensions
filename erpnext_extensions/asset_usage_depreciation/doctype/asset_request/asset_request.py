# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document

from erpnext_extensions.asset_usage_depreciation.constants import (
	STATUS_REJECTED,
	WF_STATE_APPROVED,
	WF_STATE_DRAFT,
	WF_STATE_REJECTED,
)
from erpnext_extensions.asset_usage_depreciation.services.fulfillment_service import evaluate_and_fulfill
from erpnext_extensions.asset_usage_depreciation.services.request_service import (
	mark_approved,
	stamp_policy_and_approvers,
	validate_cancel,
	validate_request,
)


class AssetRequest(Document):
	def validate(self):
		if not self.workflow_state:
			self.workflow_state = WF_STATE_DRAFT
		if self.workflow_state not in (WF_STATE_DRAFT, None, "") or self.docstatus == 1:
			stamp_policy_and_approvers(self)
		validate_request(self)
		if self.workflow_state == WF_STATE_REJECTED and not (self.rejection_reason or "").strip():
			if self.has_value_changed("workflow_state"):
				frappe.throw(_("Rejection Reason is required."))

	def before_submit(self):
		stamp_policy_and_approvers(self)
		if (self.workflow_state or WF_STATE_APPROVED) not in (WF_STATE_APPROVED,):
			# Direct submit without workflow: treat as Approved.
			self.workflow_state = WF_STATE_APPROVED
		mark_approved(self)

	def on_submit(self):
		evaluate_and_fulfill(self, create_documents=True)
		self.db_set(
			{
				"status": self.status,
				"fulfillment_status": self.fulfillment_status,
				"issued_qty": self.issued_qty,
				"purchase_qty": self.purchase_qty,
				"available_asset_count": self.available_asset_count,
				"material_request": self.material_request,
				"approved_on": self.approved_on,
				"approved_by": self.approved_by,
			},
			update_modified=False,
		)
		for row in self.get("items") or []:
			if row.name:
				row.db_update()
		for row in self.get("allocations") or []:
			row.parent = self.name
			row.parenttype = self.doctype
			row.parentfield = "allocations"
			if row.name and frappe.db.exists("Asset Request Allocation", row.name):
				row.db_update()
			else:
				row.db_insert()

	def before_cancel(self):
		validate_cancel(self)

	def on_cancel(self):
		self.db_set("status", "Cancelled")


@frappe.whitelist()
def get_available_asset_count(
	company: str,
	requested_item_code: str | None = None,
	requested_asset_category: str | None = None,
	fulfilled_item_code: str | None = None,
	exclude_request: str | None = None,
) -> int:
	from erpnext_extensions.asset_usage_depreciation.services.availability import (
		get_available_asset_count as _count,
	)

	return _count(
		company,
		requested_item_code=requested_item_code,
		requested_asset_category=requested_asset_category,
		fulfilled_item_code=fulfilled_item_code,
		exclude_request=exclude_request,
	)


@frappe.whitelist()
def get_available_assets(
	company: str,
	requested_item_code: str | None = None,
	requested_asset_category: str | None = None,
	fulfilled_item_code: str | None = None,
	exclude_request: str | None = None,
) -> list[dict]:
	from erpnext_extensions.asset_usage_depreciation.services.availability import (
		get_available_assets as _list,
	)

	return _list(
		company,
		requested_item_code=requested_item_code,
		requested_asset_category=requested_asset_category,
		fulfilled_item_code=fulfilled_item_code,
		exclude_request=exclude_request,
	)


def _assert_fulfillment_rpc_allowed(doc) -> None:
	"""Privileged AM/MR insert runs as Administrator; keep the RPC tightly gated.

	UI already requires a submitted request and Asset Manager. Enforce the same
	server-side so a user with only Asset Request write cannot mint fulfillment
	documents via RPC.
	"""
	doc.check_permission("write")
	if int(doc.docstatus or 0) != 1:
		frappe.throw(_("Fulfillment can only run on a submitted Asset Request."))
	roles = set(frappe.get_roles())
	if not roles.intersection({"Asset Manager", "System Manager"}):
		frappe.throw(_("Not permitted to create fulfillment documents."), frappe.PermissionError)


@frappe.whitelist()
def reevaluate_fulfillment(name: str) -> dict:
	doc = frappe.get_doc("Asset Request", name)
	_assert_fulfillment_rpc_allowed(doc)
	evaluate_and_fulfill(doc, create_documents=True)
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	return {"name": doc.name, "fulfillment_status": doc.fulfillment_status}


@frappe.whitelist()
def create_asset_movement(name: str) -> dict:
	from erpnext_extensions.asset_usage_depreciation.services.fulfillment_service import (
		create_asset_movement as _create,
	)

	doc = frappe.get_doc("Asset Request", name)
	_assert_fulfillment_rpc_allowed(doc)
	am = _create(doc, auto_submit=0)
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	return {"asset_movement": am.name if am else None}


@frappe.whitelist()
def create_material_request(name: str) -> dict:
	from erpnext_extensions.asset_usage_depreciation.services.fulfillment_service import (
		create_material_request as _create,
	)

	doc = frappe.get_doc("Asset Request", name)
	_assert_fulfillment_rpc_allowed(doc)
	mr = _create(doc, auto_submit=0)
	doc.flags.ignore_validate_update_after_submit = True
	doc.save()
	return {"material_request": mr.name if mr else None}
