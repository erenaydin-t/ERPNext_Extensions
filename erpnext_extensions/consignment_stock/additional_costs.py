# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import cint, flt

from erpnext_extensions.consignment_stock.constants import F_IS_RECEIPT, F_IS_RETURN


def validate_no_additional_costs(doc) -> None:
	is_consignment = cint(doc.get(F_IS_RECEIPT)) or cint(doc.get(F_IS_RETURN))
	if not is_consignment:
		return
	costs = doc.get("additional_costs") or []
	if len(costs) > 0:
		frappe.throw(_("Additional Costs are not allowed on Consignment Stock Entries."))
	for row in doc.get("items") or []:
		if flt(row.get("additional_cost")):
			frappe.throw(
				_("Row {0}: Additional Cost is not allowed on Consignment Stock Entries.").format(
					row.idx
				)
			)
