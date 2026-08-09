# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Repeated usage status transitions — auto-close previous open period via amend."""

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, getdate

# Suppress ADS replan while cancel/amend of previous open period runs inside a
# new Usage Period submit. Cleared in try/finally; new period on_submit replans once.
FLAG_USAGE_TRANSITION_IN_PROGRESS = "usage_transition_in_progress"


def is_usage_transition_in_progress() -> bool:
	return bool(frappe.flags.get(FLAG_USAGE_TRANSITION_IN_PROGRESS))


def find_submitted_open_period(asset_name: str, exclude: str | None = None) -> dict | None:
	"""Return the single submitted open-ended Usage Period for an Asset, if any."""
	filters: dict = {"asset": asset_name, "docstatus": 1}
	if exclude:
		filters["name"] = ["!=", exclude]

	rows = frappe.get_all(
		"Asset Usage Period",
		filters=filters,
		fields=["name", "from_date", "to_date", "depreciation_mode", "depreciation_percentage"],
		order_by="from_date asc",
	)
	opens = [r for r in rows if not r.to_date]
	if len(opens) > 1:
		frappe.throw(
			_("Asset {0} has multiple open-ended submitted Usage Periods. Fix the timeline before continuing.").format(
				asset_name
			)
		)
	return opens[0] if opens else None


def auto_close_previous_open_period(new_period) -> str | None:
	"""If an open Usage Period exists, amend-close it to the day before ``new_period.from_date``.

	Uses cancel + amended replacement (not ``db_set`` on submitted docs).
	Returns the amended document name, or None if nothing was closed.

	Must run only during submit of ``new_period`` (before overlap validation).
	"""
	if not new_period.asset or not new_period.from_date:
		return None

	# Do not recurse when submitting the amended closed period itself
	if is_usage_transition_in_progress():
		return None

	previous = find_submitted_open_period(
		new_period.asset,
		exclude=new_period.name if new_period.name else None,
	)
	if not previous:
		return None

	new_from = getdate(new_period.from_date)
	prev_from = getdate(previous.from_date)

	if new_from <= prev_from:
		frappe.throw(
			_(
				"Cannot start a new Asset Usage status on or before the current open period "
				"From Date ({0}). Choose a later From Date, or cancel/amend the open period manually."
			).format(prev_from)
		)

	close_to = add_days(new_from, -1)
	if close_to < prev_from:
		frappe.throw(
			_("Cannot close open Usage Period {0}: resulting To Date {1} is before From Date {2}.").format(
				previous.name, close_to, prev_from
			)
		)

	frappe.flags[FLAG_USAGE_TRANSITION_IN_PROGRESS] = True
	try:
		old = frappe.get_doc("Asset Usage Period", previous.name)
		old.flags.ignore_permissions = bool(getattr(new_period.flags, "ignore_permissions", False))
		old.cancel()

		amended = frappe.copy_doc(old)
		amended.name = None
		amended.docstatus = 0
		amended.amended_from = old.name
		amended.to_date = close_to
		amended.set("replan_log", [])
		amended.flags.ignore_permissions = old.flags.ignore_permissions
		# Ensure child rows are draft as well
		for row in amended.get("replan_log") or []:
			row.docstatus = 0
		amended.insert()
		amended.submit()
		frappe.msgprint(
			_("Previous open Usage Period {0} was closed on {1} (amended as {2}).").format(
				old.name, frappe.format(close_to, {"fieldtype": "Date"}), amended.name
			),
			alert=True,
			indicator="blue",
		)
		return amended.name
	finally:
		frappe.flags[FLAG_USAGE_TRANSITION_IN_PROGRESS] = False
