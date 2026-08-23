# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Fulfill an approved Asset Request from pool stock and/or purchase."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, get_link_to_form, now_datetime, today

from erpnext_extensions.asset_usage_depreciation.constants import (
	ALLOC_ISSUED,
	ALLOC_MOVEMENT_DRAFT,
	ALLOC_MR_DRAFT,
	ALLOC_MR_SUBMITTED,
	ALLOC_RECEIVED,
	ALLOC_RESERVED,
	ALLOC_CANCELLED,
	COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION,
	METHOD_ISSUE,
	METHOD_PURCHASE,
)
from erpnext_extensions.asset_usage_depreciation.services.availability import (
	get_available_assets,
	get_settings,
)
from erpnext_extensions.asset_usage_depreciation.services.locks import lock_asset
from erpnext_extensions.asset_usage_depreciation.services.request_service import refresh_header_fulfillment

AUTO_SUBSTITUTION_REASON = "Allocated from available pool (same Asset Category)"


def _persist_generated_doc(doc, *, ignore_permissions: bool = True, auto_submit: int = 0) -> None:
	"""Insert (and optionally submit) a system-generated AM/MR.

	Approvers such as Planner/CEO often lack Item/Asset read permission.
	``insert(ignore_permissions=True)`` does not skip Item.check_permission()
	inside ERPNext get_item_details, so run as Administrator when asked to
	ignore permissions.
	"""
	current_user = frappe.session.user
	switch = bool(ignore_permissions) and current_user not in (None, "Administrator")
	try:
		if switch:
			frappe.set_user("Administrator")
		doc.insert(ignore_permissions=ignore_permissions)
		if auto_submit:
			doc.submit()
	finally:
		if switch:
			frappe.set_user(current_user)


def evaluate_and_fulfill(doc, *, create_documents: bool = True) -> None:
	"""Reserve pool assets and/or stage purchase rows, then optionally create AM/MR."""
	if frappe.flags.get("asset_request_fulfillment_in_progress"):
		return
	frappe.flags.asset_request_fulfillment_in_progress = True
	try:
		_evaluate_allocations(doc)
		if create_documents:
			_create_documents(doc)
		refresh_header_fulfillment(doc)
	finally:
		frappe.flags.asset_request_fulfillment_in_progress = False


def _existing_open_allocs(doc, item_row_name: str) -> list:
	return [
		a
		for a in (doc.get("allocations") or [])
		if a.asset_request_item == item_row_name and a.fulfillment_status != ALLOC_CANCELLED
	]


def _evaluate_allocations(doc) -> None:
	settings = get_settings()
	reserve = cint(settings.get("reserve_available_assets", 1))
	used_assets: set[str] = {
		a.allocated_asset for a in (doc.get("allocations") or []) if a.allocated_asset
	}

	for row in doc.items:
		existing = _existing_open_allocs(doc, row.name)
		already = len(existing)
		need = cint(row.qty) - already
		if need <= 0:
			continue

		candidates = get_available_assets(
			doc.company,
			requested_item_code=row.requested_item_code,
			requested_asset_category=row.requested_asset_category,
			fulfilled_item_code=row.fulfilled_item_code
			if row.fulfilled_item_code != row.requested_item_code
			else None,
			exclude_request=doc.name,
		)
		# Prefer exact fulfilled/requested item, then category substitutes.
		preferred_item = row.fulfilled_item_code or row.requested_item_code
		candidates = [c for c in candidates if c.name not in used_assets]
		candidates.sort(key=lambda a: (0 if a.item_code == preferred_item else 1, a.creation if hasattr(a, "creation") else a.name))

		if row.preferred_asset:
			preferred = [c for c in candidates if c.name == row.preferred_asset]
			rest = [c for c in candidates if c.name != row.preferred_asset]
			candidates = preferred + rest

		issue_take = candidates[:need] if reserve else []
		for asset in issue_take:
			lock_asset(asset.name)
			used_assets.add(asset.name)
			reason = row.substitution_reason
			if asset.item_code != row.requested_item_code:
				reason = reason or AUTO_SUBSTITUTION_REASON
				if not row.fulfilled_item_code or row.fulfilled_item_code == row.requested_item_code:
					row.fulfilled_item_code = asset.item_code
					row.fulfilled_item_name = asset.asset_name
					row.substitution_reason = reason
			doc.append(
				"allocations",
				{
					"asset_request_item": row.name,
					"requested_item_code": row.requested_item_code,
					"fulfilled_item_code": asset.item_code,
					"fulfilled_purchase_item": row.fulfilled_purchase_item or asset.item_code,
					"method": METHOD_ISSUE,
					"fulfillment_status": ALLOC_RESERVED,
					"allocated_asset": asset.name,
					"substitution_reason": reason,
				},
			)

		shortage = need - len(issue_take)
		purchase_item = row.fulfilled_purchase_item or row.fulfilled_item_code or row.requested_item_code
		for _ in range(shortage):
			reason = row.substitution_reason
			if purchase_item != row.requested_item_code:
				reason = reason or _("Purchase substitute for requested item {0}").format(
					row.requested_item_code
				)
				row.substitution_reason = row.substitution_reason or reason
			doc.append(
				"allocations",
				{
					"asset_request_item": row.name,
					"requested_item_code": row.requested_item_code,
					"fulfilled_item_code": purchase_item,
					"fulfilled_purchase_item": purchase_item,
					"method": METHOD_PURCHASE,
					"fulfillment_status": ALLOC_RESERVED,
					"substitution_reason": reason,
				},
			)

	doc.available_asset_count = sum(
		1 for a in (doc.get("allocations") or []) if a.method == METHOD_ISSUE and a.allocated_asset
	)


def _create_documents(doc) -> None:
	settings = get_settings()
	if cint(settings.get("auto_create_asset_movement", 1)):
		create_asset_movement(doc, auto_submit=cint(settings.get("auto_submit_asset_movement")))
	if cint(settings.get("auto_create_material_request", 1)):
		create_material_request(doc, auto_submit=cint(settings.get("auto_submit_material_request")))


def create_asset_movement(doc, *, auto_submit: int = 0, ignore_permissions: bool = True):
	"""Create one Issue (or Transfer and Issue) movement for reserved pool assets."""
	pending = [
		a
		for a in (doc.get("allocations") or [])
		if a.method == METHOD_ISSUE
		and a.allocated_asset
		and not a.asset_movement
		and a.fulfillment_status != ALLOC_CANCELLED
	]
	if not pending:
		return None

	settings = get_settings()
	purpose = settings.get("default_movement_purpose") or "Issue"
	target_location = doc.target_location or frappe.db.get_value(
		"Company", doc.company, COMPANY_FIELD_AR_DEFAULT_TARGET_LOCATION
	)

	assets_rows = []
	use_transfer = False
	for alloc in pending:
		src_location = frappe.db.get_value("Asset", alloc.allocated_asset, "location")
		row = {
			"asset": alloc.allocated_asset,
			"source_location": src_location,
			"to_employee": doc.employee,
			"company": doc.company,
		}
		if target_location and src_location and target_location != src_location:
			row["target_location"] = target_location
			use_transfer = True
		elif purpose == "Transfer and Issue" and target_location:
			row["target_location"] = target_location
			use_transfer = True
		assets_rows.append(row)

	if purpose == "Transfer and Issue" or use_transfer:
		# Only when location actually changes — still acquisition Issue, not a Transfer Request.
		if any(r.get("target_location") for r in assets_rows):
			movement_purpose = "Transfer and Issue"
			for r in assets_rows:
				if not r.get("target_location"):
					r["target_location"] = r.get("source_location")
					# Core forbids same source/target; fall back to Issue for the whole doc if mixed.
					movement_purpose = "Issue"
					break
			# If any row lacks a distinct target, use Issue for all.
			if any(
				r.get("target_location") and r.get("source_location") == r.get("target_location")
				for r in assets_rows
			):
				movement_purpose = "Issue"
				for r in assets_rows:
					r.pop("target_location", None)
			else:
				movement_purpose = "Transfer and Issue"
		else:
			movement_purpose = "Issue"
	else:
		movement_purpose = "Issue"

	am = frappe.get_doc(
		{
			"doctype": "Asset Movement",
			"company": doc.company,
			"purpose": movement_purpose,
			"transaction_date": now_datetime(),
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"assets": assets_rows,
		}
	)
	_persist_generated_doc(am, ignore_permissions=ignore_permissions, auto_submit=auto_submit)

	status = ALLOC_ISSUED if auto_submit else ALLOC_MOVEMENT_DRAFT
	for alloc in pending:
		alloc.asset_movement = am.name
		alloc.fulfillment_status = status
	return am


def create_material_request(doc, *, auto_submit: int = 0, ignore_permissions: bool = True):
	"""Create one Purchase Material Request from purchase allocations (fulfilled item)."""
	pending = [
		a
		for a in (doc.get("allocations") or [])
		if a.method == METHOD_PURCHASE
		and not a.material_request
		and a.fulfillment_status != ALLOC_CANCELLED
	]
	if not pending:
		return None

	from erpnext_extensions.asset_usage_depreciation.services.dimension_service import (
		apply_dimensions_to_target,
		dimension_fingerprint,
		resolve_item_dimensions,
	)

	# Group by fulfilled purchase item PLUS resolved dimension fingerprint so the
	# same SKU with different Branch / Cost Center / etc. stays as separate MR lines.
	item_by_name = {row.name: row for row in (doc.get("items") or [])}
	by_key: dict[tuple, list] = {}
	dims_by_key: dict[tuple, dict] = {}
	for alloc in pending:
		purchase_item = alloc.fulfilled_purchase_item or alloc.fulfilled_item_code
		ar_item = item_by_name.get(alloc.asset_request_item)
		dims = resolve_item_dimensions(doc, ar_item)
		key = (purchase_item, dimension_fingerprint(dims))
		by_key.setdefault(key, []).append(alloc)
		dims_by_key.setdefault(key, dims)

	mr = frappe.new_doc("Material Request")
	mr.material_request_type = "Purchase"
	mr.company = doc.company
	mr.transaction_date = today()
	mr.schedule_date = doc.required_date or today()
	if hasattr(mr, "custom_asset_request"):
		mr.custom_asset_request = doc.name
	if hasattr(mr, "custom_created_from_asset_request"):
		mr.custom_created_from_asset_request = 1

	for key, allocs in by_key.items():
		item_code = key[0]
		item = frappe.db.get_value(
			"Item", item_code, ["item_name", "description", "stock_uom", "item_group"], as_dict=True
		) or {}
		row = mr.append(
			"items",
			{
				"item_code": item_code,
				"item_name": item.get("item_name"),
				"description": item.get("description"),
				"schedule_date": doc.required_date or today(),
				"qty": len(allocs),
				"uom": item.get("stock_uom"),
				"stock_uom": item.get("stock_uom"),
				"conversion_factor": 1,
				"item_group": item.get("item_group"),
			},
		)
		apply_dimensions_to_target(row, dims_by_key[key])
		if hasattr(row, "custom_asset_request_item"):
			row.custom_asset_request_item = allocs[0].asset_request_item

	_persist_generated_doc(mr, ignore_permissions=ignore_permissions, auto_submit=auto_submit)

	status = ALLOC_MR_SUBMITTED if auto_submit else ALLOC_MR_DRAFT
	for alloc in pending:
		alloc.material_request = mr.name
		alloc.fulfillment_status = status
	doc.material_request = mr.name
	return mr


def link_purchased_asset(asset_doc) -> None:
	"""After a purchased Asset is submitted, attach it to a matching purchase allocation and issue."""
	if frappe.flags.get("asset_request_fulfillment_in_progress"):
		return
	item_code = asset_doc.item_code
	company = asset_doc.company
	if not item_code or not company:
		return

	parents = frappe.get_all(
		"Asset Request Allocation",
		filters={
			"method": METHOD_PURCHASE,
			"allocated_asset": ("in", ["", None]),
			"fulfillment_status": ("in", [ALLOC_RESERVED, ALLOC_MR_DRAFT, ALLOC_MR_SUBMITTED, ALLOC_RECEIVED, "Ordered"]),
			"fulfilled_item_code": item_code,
		},
		fields=["name", "parent"],
		order_by="creation asc",
		limit=1,
	)
	# Also match on fulfilled_purchase_item
	if not parents:
		parents = frappe.get_all(
			"Asset Request Allocation",
			filters={
				"method": METHOD_PURCHASE,
				"allocated_asset": ("in", ["", None]),
				"fulfilled_purchase_item": item_code,
			},
			fields=["name", "parent"],
			order_by="creation asc",
			limit=1,
		)
	if not parents:
		return

	ar_name = parents[0].parent
	if frappe.db.get_value("Asset Request", ar_name, "company") != company:
		return
	if cint(frappe.db.get_value("Asset Request", ar_name, "docstatus")) != 1:
		return

	ar = frappe.get_doc("Asset Request", ar_name)
	alloc = next((a for a in ar.allocations if a.name == parents[0].name), None)
	if not alloc:
		return

	alloc.allocated_asset = asset_doc.name
	if asset_doc.purchase_receipt:
		alloc.purchase_receipt = asset_doc.purchase_receipt
	alloc.fulfillment_status = ALLOC_RECEIVED
	ar.flags.ignore_validate_update_after_submit = True
	settings = get_settings()
	if cint(settings.get("auto_create_asset_movement", 1)):
		# Create a dedicated movement for this newly capitalized asset.
		_issue_single_allocation(ar, alloc, auto_submit=cint(settings.get("auto_submit_asset_movement")))
	refresh_header_fulfillment(ar)
	ar.save(ignore_permissions=True)


def _issue_single_allocation(doc, alloc, *, auto_submit: int = 0) -> None:
	if alloc.asset_movement or not alloc.allocated_asset:
		return
	src_location = frappe.db.get_value("Asset", alloc.allocated_asset, "location")
	target_location = doc.target_location or src_location
	purpose = "Issue"
	row = {
		"asset": alloc.allocated_asset,
		"source_location": src_location,
		"to_employee": doc.employee,
		"company": doc.company,
	}
	if target_location and src_location and target_location != src_location:
		purpose = "Transfer and Issue"
		row["target_location"] = target_location

	am = frappe.get_doc(
		{
			"doctype": "Asset Movement",
			"company": doc.company,
			"purpose": purpose,
			"transaction_date": now_datetime(),
			"reference_doctype": doc.doctype,
			"reference_name": doc.name,
			"assets": [row],
		}
	)
	_persist_generated_doc(am, ignore_permissions=True, auto_submit=auto_submit)
	alloc.asset_movement = am.name
	alloc.fulfillment_status = ALLOC_ISSUED if auto_submit else ALLOC_MOVEMENT_DRAFT


def on_asset_movement_cancel(movement_doc) -> None:
	if movement_doc.reference_doctype != "Asset Request" or not movement_doc.reference_name:
		return
	if not frappe.db.exists("Asset Request", movement_doc.reference_name):
		return
	ar = frappe.get_doc("Asset Request", movement_doc.reference_name)
	changed = False
	for alloc in ar.allocations:
		if alloc.asset_movement == movement_doc.name:
			alloc.asset_movement = None
			alloc.fulfillment_status = ALLOC_RESERVED
			changed = True
	if changed:
		refresh_header_fulfillment(ar)
		ar.flags.ignore_validate_update_after_submit = True
		ar.save(ignore_permissions=True)


def on_material_request_cancel(mr_doc) -> None:
	ar_name = getattr(mr_doc, "custom_asset_request", None)
	if not ar_name or not frappe.db.exists("Asset Request", ar_name):
		return
	ar = frappe.get_doc("Asset Request", ar_name)
	changed = False
	for alloc in ar.allocations:
		if alloc.material_request == mr_doc.name:
			alloc.material_request = None
			alloc.material_request_item = None
			alloc.fulfillment_status = ALLOC_RESERVED
			changed = True
	if changed:
		if ar.material_request == mr_doc.name:
			ar.material_request = None
		refresh_header_fulfillment(ar)
		ar.flags.ignore_validate_update_after_submit = True
		ar.save(ignore_permissions=True)


def on_purchase_receipt_submit(pr_doc) -> None:
	"""Stamp purchase_receipt on matching purchase allocations (asset link happens on Asset submit)."""
	asset_items = [d.item_code for d in (pr_doc.get("items") or []) if cint(getattr(d, "is_fixed_asset", 0))]
	if not asset_items:
		return
	# Find MRs on this PR's items
	mr_names = list(
		{d.material_request for d in (pr_doc.get("items") or []) if getattr(d, "material_request", None)}
	)
	if not mr_names:
		return
	for mr_name in mr_names:
		ar_name = frappe.db.get_value("Material Request", mr_name, "custom_asset_request")
		if not ar_name:
			continue
		ar = frappe.get_doc("Asset Request", ar_name)
		changed = False
		for alloc in ar.allocations:
			if alloc.material_request == mr_name and alloc.method == METHOD_PURCHASE:
				alloc.purchase_receipt = pr_doc.name
				if alloc.fulfillment_status in (ALLOC_MR_DRAFT, ALLOC_MR_SUBMITTED, "Ordered"):
					alloc.fulfillment_status = ALLOC_RECEIVED
				changed = True
		if changed:
			refresh_header_fulfillment(ar)
			ar.flags.ignore_validate_update_after_submit = True
			ar.save(ignore_permissions=True)
