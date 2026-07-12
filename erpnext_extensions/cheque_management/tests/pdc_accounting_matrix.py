"""PDC workflow transition accounting matrix (derived from implementation)."""

from __future__ import annotations

from erpnext_extensions.cheque_management.pdc_accounting_idempotency import (
	build_pdc_accounting_transition_key,
)
from erpnext_extensions.cheque_management.pdc_journal_entry_service import _purpose_for_transition
from erpnext_extensions.cheque_management.pdc_transition_accounting_registry import (
	PDC_ACCOUNTING_TRANSITION_REGISTRY,
)
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	PDC_ACCOUNTING_JOURNAL_ENTRY,
	PDC_ACCOUNTING_NO_DOCUMENT,
	get_pdc_accounting_decision,
)

# User-requested edges (direction, from, to)
USER_MATRIX: list[tuple[str, str, str]] = [
	(CHEQUE_DIRECTION_RECEIVABLE, "Draft", "Registered"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Registered", "Sent to Bank"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Sent to Bank", "Cleared"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Sent to Bank", "Bounced"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Registered", "Returned"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Returned", "Replaced"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Bounced", "Replaced"),
	(CHEQUE_DIRECTION_RECEIVABLE, "Registered", "Endorsed"),
	(CHEQUE_DIRECTION_PAYABLE, "Draft", "Registered"),
	(CHEQUE_DIRECTION_PAYABLE, "Registered", "Issued"),
	(CHEQUE_DIRECTION_PAYABLE, "Issued", "Cleared"),
	(CHEQUE_DIRECTION_PAYABLE, "Issued", "Returned"),
	(CHEQUE_DIRECTION_PAYABLE, "Issued", "Cancelled"),
	(CHEQUE_DIRECTION_PAYABLE, "Returned", "Replaced"),
]


def _should_post_je(direction: str, fr: str, to: str) -> str:
	dec = get_pdc_accounting_decision(direction, fr, to)
	if dec == PDC_ACCOUNTING_JOURNAL_ENTRY:
		return "yes"
	if dec == PDC_ACCOUNTING_NO_DOCUMENT:
		return "no"
	return "no (no policy row)"


def print_pdc_accounting_matrix(pdc_name: str = "PDC-EXAMPLE") -> list[dict]:
	rows = []
	for direction, fr, to in USER_MATRIX:
		dec = get_pdc_accounting_decision(direction, fr, to)
		spec = PDC_ACCOUNTING_TRANSITION_REGISTRY.get((direction, fr, to))
		purpose = _purpose_for_transition(direction, fr, to) if dec == PDC_ACCOUNTING_JOURNAL_ENTRY else ""
		key = build_pdc_accounting_transition_key(pdc_name, direction, fr, to)
		ref_delta = "+1" if dec == PDC_ACCOUNTING_JOURNAL_ENTRY else "0"
		row = {
			"transition": f"{direction}: {fr} → {to}",
			"should_post_je": _should_post_je(direction, fr, to),
			"policy": dec or "missing",
			"purpose": purpose,
			"registry_summary": (spec.summary if spec else ""),
			"idempotency_key": key if dec == PDC_ACCOUNTING_JOURNAL_ENTRY else "—",
			"reference_count_delta": ref_delta,
		}
		rows.append(row)
	return rows


def bench_print_matrix():
	import json

	return json.dumps(print_pdc_accounting_matrix(), indent=2)
