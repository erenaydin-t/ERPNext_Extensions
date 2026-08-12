# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT. See LICENSE file for details.

"""Derived possession / expiry helpers for Guarantee Document.

Held By is presentation-only — never stored on the DocType.
"""

from __future__ import annotations

from datetime import date, timedelta

from frappe.utils import getdate


ACTIVE_STATUS = "Active"
CLOSED_STATUSES = frozenset({"Draft", "Returned", "Released", "Cancelled", "Expired", "Lost"})


def get_held_by_label(status: str | None, direction: str | None) -> str:
	"""Return Held By presentation label for list/report.

	Active + Received → Held by Us
	Active + Issued → Held by Others
	Otherwise → —
	"""
	st = (status or "").strip()
	direction = (direction or "").strip()
	if st != ACTIVE_STATUS:
		return "—"
	if direction == "Received":
		return "Held by Us"
	if direction == "Issued":
		return "Held by Others"
	return "—"


def is_held_by_us(status: str | None, direction: str | None) -> bool:
	return (status or "").strip() == ACTIVE_STATUS and (direction or "").strip() == "Received"


def is_held_by_others(status: str | None, direction: str | None) -> bool:
	return (status or "").strip() == ACTIVE_STATUS and (direction or "").strip() == "Issued"


def get_expiry_bucket(expiry_date, as_on_date) -> str:
	"""Return non-overlapping expiry bucket label relative to as_on_date."""
	as_on = getdate(as_on_date) if as_on_date else getdate()
	if not expiry_date:
		return "No Expiry Date"

	exp = getdate(expiry_date)
	if exp < as_on:
		return "Active but Expired"

	delta = (exp - as_on).days
	if delta <= 7:
		return "Due 0–7 Days"
	if delta <= 30:
		return "Due 8–30 Days"
	if delta <= 60:
		return "Due 31–60 Days"
	if delta <= 90:
		return "Due 61–90 Days"
	return "Due 90+ Days"


def is_active_but_expired(status: str | None, expiry_date, as_on_date) -> bool:
	if (status or "").strip() != ACTIVE_STATUS:
		return False
	if not expiry_date:
		return False
	as_on = getdate(as_on_date) if as_on_date else getdate()
	return getdate(expiry_date) < as_on


def is_expiring_soon(status: str | None, expiry_date, as_on_date, days: int = 30) -> bool:
	"""Inclusive window: as_on <= expiry_date <= as_on + days."""
	if (status or "").strip() != ACTIVE_STATUS:
		return False
	if not expiry_date:
		return False
	as_on = getdate(as_on_date) if as_on_date else getdate()
	exp = getdate(expiry_date)
	end = as_on + timedelta(days=int(days))
	return as_on <= exp <= end


def add_days(d: date | str, days: int) -> date:
	return getdate(d) + timedelta(days=days)
