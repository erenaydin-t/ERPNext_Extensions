"""Execute a RollbackPlan (dry-run enriches only; live run mutates DB)."""

from __future__ import annotations

from typing import Any

from erpnext_extensions.cheque_management.accounting_rollback.models import RollbackPlan
from erpnext_extensions.cheque_management.accounting_rollback.transitions import get_handler


def execute_rollback_plan(
	plan: RollbackPlan,
	pdc,
	*,
	dry_run: bool,
	apply_instrument_fn,
) -> dict[str, Any]:
	"""Run transition rollbacks newest-first, then apply workflow/leaf/audit."""
	outstanding_updates: list[dict] = []
	removed: list[dict] = []

	for step in plan.steps:
		handler = get_handler(step)
		handler.enrich_impact(step, pdc)
		if dry_run:
			continue
		updates = handler.rollback(step, pdc, dry_run=False)
		outstanding_updates.extend(updates)
		if step.journal_entry:
			removed.append(
				{
					"doctype": "Journal Entry",
					"name": step.journal_entry,
					"action": "cancelled",
					"transition": f"{step.from_state} → {step.to_state}",
					"transition_key": step.transition_key,
				}
			)

	if dry_run:
		return plan.to_api_dict()

	result = apply_instrument_fn(pdc, plan, removed, outstanding_updates)
	payload = plan.to_api_dict()
	payload.update(result)
	payload["outstanding_updates"] = outstanding_updates
	payload["removed_documents"] = removed
	return payload
