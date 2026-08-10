# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

"""Fixed-end depreciation policy: factor each unposted row, balance on final row.

LOCKED RULE (Adjust Final Depreciation Installment):

1. Start from the standard ERPNext unposted schedule baseline every replan
   (never from a previously inflated final installment).
2. Apply usage factors to every eligible unposted row *except* the final
   schedule row.
3. Set the final row once as the balancing amount so
   sum(unposted) == remaining depreciable value (→ salvage exactly).

Do NOT use weighted redistribution (remaining × weight / Σweights).
"""

from __future__ import annotations

from typing import Any, Callable

import frappe
from frappe import _
from frappe.utils import flt

from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import (
	sum_unposted_amounts,
	to_depr_amount,
)


def apply_fixed_end_usage_adjustment(
	rows: list[dict[str, Any]],
	remaining_depreciable: float,
	*,
	resolve_amount_and_factor: Callable[[int, dict[str, Any]], tuple[float, float]],
) -> None:
	"""Apply usage factors to non-final unposted rows; balance on the final row.

	``resolve_amount_and_factor(idx, row)`` must return
	``(standard_erpnext_amount, usage_factor)`` for that row index using the
	fresh ERPNext baseline amount (not a previously balanced final amount).
	"""
	if not rows:
		frappe.throw(_("Cannot adjust final installment: depreciation schedule is empty."))

	# Final balancing row = last row of the original schedule when it is unposted.
	# If the original final row is already posted, use the last unposted row instead.
	if not rows[-1].get("journal_entry"):
		final_idx = len(rows) - 1
	else:
		unposted_indices = [i for i, r in enumerate(rows) if not r.get("journal_entry")]
		if not unposted_indices:
			frappe.throw(
				_("No unposted depreciation rows remain to apply usage factors or balance salvage.")
			)
		final_idx = unposted_indices[-1]
		frappe.msgprint(
			_(
				"The original final depreciation installment is already posted. "
				"The last unposted installment will absorb the usage balancing amount."
			),
			alert=True,
			indicator="orange",
		)

	target = to_depr_amount(remaining_depreciable)

	for idx, row in enumerate(rows):
		if row.get("journal_entry"):
			continue
		if idx == final_idx:
			continue
		standard, factor = resolve_amount_and_factor(idx, row)
		row["usage_factor"] = factor
		row["depreciation_amount"] = to_depr_amount(flt(standard) * flt(factor))

	prior = 0
	for idx, row in enumerate(rows):
		if row.get("journal_entry") or idx == final_idx:
			continue
		prior += to_depr_amount(row["depreciation_amount"])

	final_amount = target - prior
	if final_amount < 0:
		frappe.throw(
			_(
				"Fixed-end usage adjustment would make the final depreciation installment negative "
				"({0}). Check usage factors and posted depreciation."
			).format(final_amount)
		)

	rows[final_idx]["depreciation_amount"] = final_amount
	rows[final_idx]["usage_factor"] = None  # balancing row — not a factored installment
	rows[final_idx]["is_balancing_row"] = True

	if sum_unposted_amounts(rows) != target:
		frappe.throw(
			_("Fixed-end usage adjustment failed salvage invariant (unposted {0} != remaining {1}).").format(
				sum_unposted_amounts(rows), target
			)
		)


def redistribute_unposted_amounts(
	rows: list[dict],
	remaining_depreciable: float,
	precision: int | None = None,
) -> None:
	"""Backward-compatible wrapper around ``apply_fixed_end_usage_adjustment``.

	Expects each unposted row to carry a standard ERPNext ``depreciation_amount``
	(or ``_standard_amount``) and a ``usage_factor``. The final unposted row is
	set as the balancing amount; it is not multiplied by its factor.
	"""

	for row in rows:
		if row.get("journal_entry"):
			continue
		if "_standard_amount" not in row:
			row["_standard_amount"] = flt(row.get("depreciation_amount"))
		if "usage_factor" not in row:
			row["usage_factor"] = 1.0

	def resolve(idx, row):
		return flt(row.get("_standard_amount", row["depreciation_amount"])), flt(row.get("usage_factor", 1.0))

	apply_fixed_end_usage_adjustment(
		rows,
		remaining_depreciable,
		resolve_amount_and_factor=resolve,
	)
