# Copyright (c) 2026, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Payment Request path hint: Mode of Payment vs PDC Settings (UI / future validation only).

This module does not perform settlement, allocation, or accounting checks.
"""

from __future__ import annotations

import frappe


def get_payment_request_pdc_mode_of_payment(company: str | None) -> str | None:
	"""Return the Mode of Payment name configured as the PDC path for ``company``, or None.

	Reads :class:`PDC Settings` (``payment_request_pdc_mode_of_payment``). If settings row is missing
	or the field is empty, returns None — callers should treat that as “not PDC path”.
	"""
	co = (company or "").strip()
	if not co:
		return None
	val = frappe.db.get_value(
		"PDC Settings",
		{"company": co},
		"payment_request_pdc_mode_of_payment",
	)
	if not val:
		return None
	s = str(val).strip()
	return s or None


def is_payment_request_pdc_flow(company: str | None, mode_of_payment: str | None) -> bool:
	"""True when ``mode_of_payment`` matches the company's configured PDC Mode of Payment in PDC Settings."""
	expected = get_payment_request_pdc_mode_of_payment(company)
	if not expected:
		return False
	mop = (mode_of_payment or "").strip()
	if not mop:
		return False
	return mop == expected


@frappe.whitelist()
def get_payment_request_pdc_path_info(company: str | None = None, mode_of_payment: str | None = None) -> dict:
	"""Desk helper: classify Payment Request for PDC vs normal Payment Entry guidance.

	Returns:
		dict with keys:
		- ``is_pdc_flow`` (bool)
		- ``configured_pdc_mode_of_payment`` (str | None) — value from PDC Settings, for display/debug
	"""
	configured = get_payment_request_pdc_mode_of_payment(company)
	is_pdc = is_payment_request_pdc_flow(company, mode_of_payment)
	return {
		"is_pdc_flow": bool(is_pdc),
		"configured_pdc_mode_of_payment": configured,
	}


__all__ = [
	"get_payment_request_pdc_mode_of_payment",
	"get_payment_request_pdc_path_info",
	"is_payment_request_pdc_flow",
]
