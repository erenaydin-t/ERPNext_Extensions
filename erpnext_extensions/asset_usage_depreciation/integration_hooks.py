# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Thin hooks that re-apply usage factors after ERPNext rebuilds ADS."""

from __future__ import annotations

import frappe

from erpnext_extensions.asset_usage_depreciation.services.replan_service import (
	asset_has_submitted_usage_periods,
	replan_asset_usage_depreciation,
)


def _reapply_for_asset(asset_name: str, trigger_doc=None):
	if not asset_name:
		return
	if frappe.flags.get("usage_replan_in_progress"):
		return
	if not asset_has_submitted_usage_periods(asset_name):
		return
	replan_asset_usage_depreciation(
		asset_name,
		trigger_doc=trigger_doc,
		context={"skip_if_no_usage": True, "source": "erpnext_reschedule"},
	)


def on_asset_value_adjustment_submit(doc, method=None):
	_reapply_for_asset(doc.asset, trigger_doc=doc)


def on_asset_value_adjustment_cancel(doc, method=None):
	_reapply_for_asset(doc.asset, trigger_doc=doc)


def on_asset_repair_submit(doc, method=None):
	if not doc.asset:
		return
	if not (getattr(doc, "capitalize_repair_cost", 0) or getattr(doc, "increase_in_asset_life", 0)):
		return
	_reapply_for_asset(doc.asset, trigger_doc=doc)


def on_asset_repair_cancel(doc, method=None):
	if not doc.asset:
		return
	if not (getattr(doc, "capitalize_repair_cost", 0) or getattr(doc, "increase_in_asset_life", 0)):
		return
	_reapply_for_asset(doc.asset, trigger_doc=doc)


def on_sales_invoice_submit(doc, method=None):
	# Narrow: only invoices that dispose fixed assets
	for asset_name in _disposed_assets_on_sales_invoice(doc):
		_reapply_for_asset(asset_name, trigger_doc=doc)


def on_sales_invoice_cancel(doc, method=None):
	for asset_name in _disposed_assets_on_sales_invoice(doc):
		_reapply_for_asset(asset_name, trigger_doc=doc)


def _disposed_assets_on_sales_invoice(doc) -> list[str]:
	"""Return asset names only when SI items reference Asset (disposal path)."""
	names: list[str] = []
	for item in doc.get("items") or []:
		asset_name = getattr(item, "asset", None)
		if not asset_name:
			continue
		# is_fixed_asset on item is the ERPNext disposal signal when present
		if getattr(item, "is_fixed_asset", None) in (None, 1):
			names.append(asset_name)
	return names


@frappe.whitelist()
def scrap_asset(*args, **kwargs):
	"""Whitelist wrapper: run core scrap, then re-apply usage factors.

	Uses ``override_whitelisted_methods`` (same pattern as other modules in this
	app). Imports the original function from the ERPNext module object so this
	is not a monkey patch of the module attribute.
	"""
	from erpnext.assets.doctype.asset import depreciation as depr_mod

	result = depr_mod.scrap_asset(*args, **kwargs)
	asset_name = kwargs.get("asset_name") or (args[0] if args else None)
	_reapply_for_asset(asset_name)
	return result


@frappe.whitelist()
def restore_asset(*args, **kwargs):
	"""Whitelist wrapper: run core restore, then re-apply usage factors."""
	from erpnext.assets.doctype.asset import depreciation as depr_mod

	result = depr_mod.restore_asset(*args, **kwargs)
	asset_name = kwargs.get("asset_name") or (args[0] if args else None)
	_reapply_for_asset(asset_name)
	return result
