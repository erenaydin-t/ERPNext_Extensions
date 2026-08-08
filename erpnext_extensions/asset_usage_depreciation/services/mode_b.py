# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from frappe.utils import flt

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import to_depr_amount


def redistribute_unposted_amounts(
	rows: list[dict],
	remaining_depreciable: float,
	precision: int | None = None,
) -> None:
	"""Mode B: weight unposted rows by usage factor; preserve dates/count.

	Internal allocation uses full float precision; persisted amounts are
	whole numbers (Iran Accounting ROUND_HALF_UP). The last eligible row
	absorbs integer residue so ``sum(unposted) == remaining`` exactly.
	"""
	unposted = [r for r in rows if not r.get("journal_entry")]
	weights = [flt(r.get("usage_factor")) for r in unposted]
	weight_sum = flt(sum(weights))

	if weight_sum <= 0:
		import frappe
		from frappe import _

		frappe.throw(
			_(
				"Cannot redistribute remaining depreciable value: all remaining usage factors are zero. "
				"Add a future Normal or Percentage Asset Usage Period, or change the Company setting "
				"'Reduced Depreciation Handling' to 'Extend Depreciation Schedule'."
			)
		)

	target = to_depr_amount(remaining_depreciable)
	allocated = 0
	for idx, row in enumerate(unposted):
		if idx == len(unposted) - 1:
			amount = target - allocated
		else:
			raw = target * flt(row.get("usage_factor")) / weight_sum
			amount = to_depr_amount(raw)
			allocated += amount
		if amount < 0:
			import frappe
			from frappe import _

			frappe.throw(_("Mode B produced a negative depreciation amount."))
		row["depreciation_amount"] = amount
