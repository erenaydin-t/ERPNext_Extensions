# Copyright (c) 2026, ERPNext Extensions contributors
# License: MIT

from __future__ import annotations

from typing import Any, Callable

import frappe
from frappe import _
from frappe.utils import add_months, cint, flt, get_last_day, getdate, is_last_day_of_the_month

from erpnext_extensions.asset_usage_depreciation.constants import MAX_MODE_A_EXTENSION_PERIODS
from erpnext_extensions.asset_usage_depreciation.services.accounting_amounts import (
	sum_unposted_amounts,
	to_depr_amount,
)
from erpnext_extensions.asset_usage_depreciation.services.usage_timeline import (
	factor_on_date,
	has_future_positive_factor,
)


def apply_mode_a_extension(
	rows: list[dict[str, Any]],
	remaining_depreciable: float,
	timeline: list[dict[str, Any]],
	*,
	frequency_of_depreciation: int,
	base_installment: float,
	precision: int | None = None,
	resolve_factor_for_date: Callable[[Any], float] | None = None,
	daily_prorata_based: int = 0,
) -> dict[str, Any]:
	"""Keep reduced amounts; append periods until salvage or suspension.

	All persisted amounts are whole numbers (Iran Accounting ROUND_HALF_UP).
	"""
	resolve_factor = resolve_factor_for_date or (lambda d: factor_on_date(timeline, d))

	# Normalize existing unposted amounts; drop zero rows
	kept: list[dict[str, Any]] = []
	for row in rows:
		if row.get("journal_entry"):
			kept.append(row)
			continue
		amount = to_depr_amount(row.get("depreciation_amount"))
		row["depreciation_amount"] = amount
		if amount > 0:
			kept.append(row)
	rows.clear()
	rows.extend(kept)

	target = to_depr_amount(remaining_depreciable)
	outstanding = target - sum_unposted_amounts(rows)

	meta = {"suspended": False, "message": None}
	if outstanding <= 0:
		return meta

	freq = cint(frequency_of_depreciation) or 1
	base = to_depr_amount(base_installment) if flt(base_installment) > 0 else outstanding
	if base <= 0:
		base = outstanding

	if not rows:
		probe = timeline[0]["from_date"] if timeline else getdate()
		if not has_future_positive_factor(timeline, probe):
			meta["suspended"] = True
			meta["message"] = _(
				"Depreciation extension suspended: remaining depreciable value is outstanding, "
				"but the usage timeline has no future period with a factor greater than zero. "
				"Submit a Normal or Percentage Asset Usage Period to resume depreciation."
			)
			return meta
		frappe.throw(_("Cannot extend depreciation schedule: no schedule rows available as a base."))

	last_date = getdate(rows[-1]["schedule_date"])
	should_get_last_day = is_last_day_of_the_month(last_date)

	for _guard in range(MAX_MODE_A_EXTENSION_PERIODS):
		if outstanding <= 0:
			break

		next_date = add_months(last_date, freq)
		if should_get_last_day:
			next_date = get_last_day(next_date)
		next_date = getdate(next_date)

		if not has_future_positive_factor(timeline, next_date):
			meta["suspended"] = True
			meta["message"] = _(
				"Depreciation extension suspended: remaining depreciable value is outstanding, "
				"but the usage timeline has no future period with a factor greater than zero. "
				"Submit a Normal or Percentage Asset Usage Period to resume depreciation."
			)
			break

		factor = flt(resolve_factor(next_date))
		if factor <= 0:
			last_date = next_date
			continue

		amount = to_depr_amount(min(base * factor, outstanding))
		if amount <= 0:
			last_date = next_date
			continue

		rows.append(
			{
				"schedule_date": next_date,
				"depreciation_amount": amount,
				"journal_entry": None,
				"usage_factor": factor,
				"shift": None,
			}
		)
		outstanding -= amount
		last_date = next_date
	else:
		frappe.throw(
			_(
				"Mode A extension exceeded the safety limit of {0} periods. "
				"Check the usage timeline and depreciation configuration."
			).format(MAX_MODE_A_EXTENSION_PERIODS)
		)

	# Absorb whole-number residue on last positive unposted row when complete
	if not meta["suspended"] and outstanding != 0 and rows:
		for row in reversed(rows):
			if row.get("journal_entry"):
				continue
			row["depreciation_amount"] = to_depr_amount(row["depreciation_amount"] + outstanding)
			break

	return meta


__all__ = ["apply_mode_a_extension", "has_future_positive_factor"]
