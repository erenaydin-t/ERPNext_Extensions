# Copyright (c) 2026, ERPNext Extensions contributors
"""Opening-import workflow baseline for PDC rollback (import state is the floor)."""

from __future__ import annotations

from typing import Any

import frappe
from frappe.utils import cint

from erpnext_extensions.cheque_management.accounting_rollback.pdc.plan import index_journal_references
from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_SENT_TO_BANK,
	normalize_workflow_state_value,
)


def _workflow_rank(direction: str, state: str) -> int:
	order_payable = [WORKFLOW_DRAFT, WORKFLOW_REGISTERED, WORKFLOW_ISSUED, WORKFLOW_CLEARED]
	order_receivable = [
		WORKFLOW_DRAFT,
		WORKFLOW_REGISTERED,
		WORKFLOW_SENT_TO_BANK,
		WORKFLOW_CLEARED,
	]
	order = order_payable if direction == "Payable" else order_receivable
	state = normalize_workflow_state_value(state)
	try:
		return order.index(state)
	except ValueError:
		return 99


def resolve_opening_import_baseline_state(pdc) -> str | None:
	"""Baseline workflow state at opening import (rollback must not go earlier)."""
	if not cint(getattr(pdc, "is_opening_import", 0)):
		return None
	stored = (getattr(pdc, "opening_import_workflow_state", None) or "").strip()
	if stored:
		return normalize_workflow_state_value(stored)
	return _infer_opening_import_baseline_state(pdc)


def infer_opening_import_baseline_state(pdc) -> str:
	"""Best-effort baseline when field is empty (legacy rows)."""
	return _infer_opening_import_baseline_state(pdc)


def _infer_opening_import_baseline_state(pdc) -> str:
	"""Best-effort baseline when field is empty (legacy rows)."""
	direction = (pdc.cheque_direction or "").strip()
	current = normalize_workflow_state_value(pdc.workflow_state)
	refs = index_journal_references(pdc.name)
	if not refs:
		return current
	# Earliest transition edge by workflow rank (lowest from_state on the path).
	candidates: list[tuple[int, str]] = []
	for (from_s, _to_s) in refs.keys():
		candidates.append((_workflow_rank(direction, from_s), from_s))
	if not candidates:
		return current
	candidates.sort(key=lambda x: (x[0], x[1]))
	_, from_s = candidates[0]
	return normalize_workflow_state_value(from_s)


def opening_import_baseline_notice(baseline: str) -> str:
	return frappe._(
		"This cheque was imported at state {0}. Rollback before the import baseline is not available."
	).format(baseline)


def opening_import_no_history_notice(baseline: str) -> str:
	return frappe._(
		"This PDC was imported at its current workflow state ({0}) and has no rollback history before import."
	).format(baseline)
