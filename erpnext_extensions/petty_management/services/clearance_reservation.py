"""SQL predicates for PM Clearance funding reservation (shared, no service cycles)."""

from __future__ import annotations

from erpnext_extensions.petty_management.services.constants import (
	FUNDING_SOURCE_OPENING_ADVANCE,
	FUNDING_SOURCE_PM_REQUEST,
)


def clearance_reserves_pm_request_balance_sql(table_alias: str = "p") -> str:
	"""SQL predicate for clearances whose allocation rows reserve funding."""
	p = table_alias
	return f"""
		{p}.docstatus = 1
		AND IFNULL({p}.status, '') NOT IN ('Cancelled', 'Rejected', 'Draft')
		AND NOT EXISTS (
			SELECT 1 FROM `tabWorkflow State` ws
			WHERE ws.name = {p}.workflow_state
			AND IFNULL(ws.workflow_state_name, '') IN ('Cancelled', 'Rejected')
		)
		AND (
			IFNULL({p}.status, '') IN ('Approved', 'Pending Journal Entry Submission', 'Settled')
			OR EXISTS (
				SELECT 1 FROM `tabWorkflow State` ws
				WHERE ws.name = {p}.workflow_state
				AND IFNULL(ws.workflow_state_name, '') = 'Approved'
			)
		)
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
