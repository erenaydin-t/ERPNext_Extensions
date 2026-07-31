# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN


def prepare_receipt_rates(doc, settings=None) -> None:
	"""Force manual rates on consignment receipt rows."""
	if not cint(doc.get(F_IS_RECEIPT)):
		return
	allow_zero = 0
	if settings is not None:
		allow_zero = cint(settings.allow_zero_receipt_rate)
	else:
		from erpnext_extensions.consignment_stock.accounting import get_consignment_settings

		allow_zero = cint(get_consignment_settings(doc.company).allow_zero_receipt_rate)

	for row in doc.get("items") or []:
		row.set_basic_rate_manually = 1
		if row.get("allow_zero_valuation_rate") and not allow_zero:
			row.allow_zero_valuation_rate = 0
		rate = flt(row.basic_rate)
		if rate < 0:
			frappe.throw(_("Row {0}: Valuation rate cannot be negative.").format(row.idx))
		if rate == 0 and not allow_zero:
			frappe.throw(
				_("Row {0}: Consignment Receipt requires a valuation rate greater than zero.").format(
					row.idx
				)
			)


def lock_return_outgoing_rates(doc) -> None:
	"""Outgoing rates come from warehouse valuation; clear manual overrides."""
	if not cint(doc.get(F_IS_RETURN)):
		return
	for row in doc.get("items") or []:
		# Let ERPNext set_rate_for_outgoing_items populate basic_rate from stock.
		row.set_basic_rate_manually = 0
		row.allow_zero_valuation_rate = 0
