# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, cint, flt, getdate

from erpnext_extensions.asset_usage_depreciation.constants import (
	MODE_NO_DEPRECIATION,
	MODE_NORMAL,
	MODE_PERCENTAGE,
)
from erpnext_extensions.asset_usage_depreciation.services.locks import lock_asset
from erpnext_extensions.asset_usage_depreciation.services.replan_service import (
	replan_asset_usage_depreciation,
)
from erpnext_extensions.asset_usage_depreciation.services.transition_service import (
	auto_close_previous_open_period,
	is_usage_transition_in_progress,
)
from erpnext_extensions.asset_usage_depreciation.services.usage_timeline import (
	load_submitted_usage_periods,
	mode_to_factor,
	validate_timeline_consistency,
)


class AssetUsagePeriod(Document):
	def validate(self):
		self._set_company()
		self._normalize_mode()
		self._validate_dates()
		self._validate_asset()
		self._validate_percentage()
		if getattr(self, "_action", None) == "submit":
			# Real amend-close before final timeline validation
			lock_asset(self.asset)
			auto_close_previous_open_period(self)
			self._validate_overlap_and_open_ended(preview_auto_close=False)
		else:
			# Draft save: preview closing any earlier open so insert is not blocked
			self._validate_overlap_and_open_ended(preview_auto_close=True)

	def before_submit(self):
		lock_asset(self.asset)
		self._validate_asset()
		# Auto-close already done in validate on submit; re-validate under lock
		self._validate_overlap_and_open_ended(preview_auto_close=False)

	def on_submit(self):
		if is_usage_transition_in_progress():
			return
		replan_asset_usage_depreciation(self.asset, trigger_doc=self)

	def on_cancel(self):
		if is_usage_transition_in_progress():
			return
		lock_asset(self.asset)
		replan_asset_usage_depreciation(self.asset, trigger_doc=self)

	def _set_company(self):
		if self.asset and not self.company:
			self.company = frappe.db.get_value("Asset", self.asset, "company")

	def _normalize_mode(self):
		if self.depreciation_mode == MODE_PERCENTAGE and flt(self.depreciation_percentage) == 100:
			self.depreciation_mode = MODE_NORMAL
			self.depreciation_percentage = None
			frappe.msgprint(_("100% was normalized to Normal mode."), alert=True)

	def _validate_percentage(self):
		if self.depreciation_mode == MODE_PERCENTAGE:
			pct = flt(self.depreciation_percentage)
			if pct <= 0:
				frappe.throw(_("Use mode 'No Depreciation' instead of Percentage 0%."))
			if pct >= 100:
				frappe.throw(_("Percentage must be greater than 0 and less than 100."))
			mode_to_factor(MODE_PERCENTAGE, pct)
		elif self.depreciation_mode in (MODE_NORMAL, MODE_NO_DEPRECIATION):
			self.depreciation_percentage = None
		else:
			frappe.throw(_("Invalid depreciation mode: {0}").format(self.depreciation_mode))

	def _validate_dates(self):
		if not self.from_date:
			frappe.throw(_("From Date is required."))
		if self.to_date and getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be on or before To Date."))

	def _validate_asset(self):
		if not self.asset:
			frappe.throw(_("Asset is required."))
		asset = frappe.db.get_value(
			"Asset",
			self.asset,
			["docstatus", "calculate_depreciation", "status", "company"],
			as_dict=True,
		)
		if not asset:
			frappe.throw(_("Asset {0} not found.").format(self.asset))
		if asset.docstatus != 1:
			frappe.throw(_("Asset {0} must be submitted.").format(self.asset))
		if not cint(asset.calculate_depreciation):
			frappe.throw(_("Asset {0} does not calculate depreciation.").format(self.asset))
		if asset.status in ("Sold", "Scrapped"):
			frappe.throw(
				_("Cannot create Asset Usage Period for Asset {0} with status {1}.").format(
					self.asset, asset.status
				)
			)
		self.company = asset.company

	def _preview_auto_close_periods(self, periods: list[dict]) -> list[dict]:
		"""Treat earlier open periods as closed at from_date-1 for draft validation only."""
		if not self.from_date:
			return periods
		new_from = getdate(self.from_date)
		previewed = []
		for period in periods:
			if period.get("to_date") is None and period["from_date"] < new_from:
				closed = dict(period)
				closed["to_date"] = add_days(new_from, -1)
				previewed.append(closed)
			else:
				previewed.append(period)
		return previewed

	def _validate_overlap_and_open_ended(self, preview_auto_close: bool = False):
		periods = load_submitted_usage_periods(self.asset, exclude=self.name if self.name else None)
		if preview_auto_close:
			periods = self._preview_auto_close_periods(periods)

		current = {
			"name": self.name or "__current__",
			"from_date": getdate(self.from_date),
			"to_date": getdate(self.to_date) if self.to_date else None,
			"depreciation_mode": self.depreciation_mode,
			"depreciation_percentage": self.depreciation_percentage,
			"factor": mode_to_factor(
				self.depreciation_mode,
				self.depreciation_percentage if self.depreciation_mode == MODE_PERCENTAGE else None,
			),
		}
		combined = periods + [current]
		combined.sort(key=lambda p: (p["from_date"], p["name"]))
		validate_timeline_consistency(combined)
