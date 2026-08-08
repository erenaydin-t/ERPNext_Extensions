# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from frappe.utils import flt


def redistribute_unposted_amounts(
	rows: list[dict],
	remaining_depreciable: float,
	precision: int,
) -> None:
	"""Mode B: weight unposted rows by usage factor; preserve dates/count.

	``rows`` items are dicts with keys:
	- journal_entry (truthy => posted, skipped)
	- usage_factor
	- depreciation_amount (mutated)
	"""
	unposted = [r for r in rows if not r.get("journal_entry")]
	weights = [flt(r.get("usage_factor")) for r in unposted]
	weight_sum = flt(sum(weights), precision)

	if weight_sum <= 0:
		from frappe import _

		import frappe

		frappe.throw(
			_(
				"Cannot redistribute remaining depreciable value: all remaining usage factors are zero. "
				"Add a future Normal or Percentage Asset Usage Period, or change the Company setting "
				"'Reduced Depreciation Handling' to 'Extend Depreciation Schedule'."
			)
		)

	target = flt(remaining_depreciable, precision)
	allocated = 0.0
	for idx, row in enumerate(unposted):
		if idx == len(unposted) - 1:
			amount = flt(target - allocated, precision)
		else:
			amount = flt(target * flt(row.get("usage_factor")) / weight_sum, precision)
			allocated = flt(allocated + amount, precision)
		row["depreciation_amount"] = amount
