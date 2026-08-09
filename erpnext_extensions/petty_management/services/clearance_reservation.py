"""SQL predicates for PM Clearance funding reservation (shared, no service cycles)."""

from __future__ import annotations

from erpnext_extensions.petty_management.services.constants import (
	FUNDING_SOURCE_OPENING_ADVANCE,
	FUNDING_SOURCE_PM_REQUEST,
)


def clearance_reserves_pm_request_balance_sql(table_alias: str = "p") -> str:
	"""SQL predicate for clearances whose allocation rows reserve funding.

	v4.0.2: business ``status`` is authoritative (workflow no longer carries Settled).
	"""
	p = table_alias
	return f"""
		{p}.docstatus = 1
		AND IFNULL({p}.status, '') NOT IN ('Cancelled', 'Rejected', 'Draft', 'Pending Approval', 'Pending Finance Review')
		AND IFNULL({p}.status, '') IN ('Approved', 'Pending Journal Entry Submission', 'Settled')
	"""


def pm_request_allocation_sql_filter(table_alias: str = "c") -> str:
	a = table_alias
	return f"""
		(
			IFNULL({a}.funding_source_type, '') IN ('', '{FUNDING_SOURCE_PM_REQUEST}')
			AND IFNULL({a}.pm_request, '') != ''
		)
	"""


def opening_allocation_sql_filter(table_alias: str = "c") -> str:
	a = table_alias
	return f"""
		IFNULL({a}.funding_source_type, '') = '{FUNDING_SOURCE_OPENING_ADVANCE}'
		AND IFNULL({a}.pm_opening_advance, '') != ''
	"""
