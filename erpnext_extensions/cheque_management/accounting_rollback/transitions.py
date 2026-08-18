"""Transition handler registry — one handler per edge pattern."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from erpnext_extensions.cheque_management.accounting_rollback import erpnext_accounting

if TYPE_CHECKING:
	from erpnext_extensions.cheque_management.accounting_rollback.models import RollbackTransitionStep


class PDCTransition(ABC):
	"""One workflow edge rollback handler (apply/rollback/preview hooks for future workflows)."""

	@abstractmethod
	def preview(self, step: "RollbackTransitionStep", pdc) -> None:
		self.enrich_impact(step, pdc)

	@abstractmethod
	def enrich_impact(self, step: "RollbackTransitionStep", pdc) -> None: ...

	@abstractmethod
	def rollback(self, step: "RollbackTransitionStep", pdc, *, dry_run: bool) -> list[dict]: ...


class TransitionRollbackHandler(PDCTransition):
	def preview(self, step, pdc) -> None:
		"""Impact already populated in enrich_impact during dry-run."""
		return


class JournalEntryTransitionHandler(TransitionRollbackHandler):
	"""Undo a posted transition Journal Entry (reference row removed before cancel)."""

	def enrich_impact(self, step, pdc) -> None:
		if not step.journal_entry:
			step.impact = {"has_accounting": False}
			return
		step.impact = erpnext_accounting.journal_entry_impact_snapshot(step.journal_entry)
		step.impact["has_accounting"] = True

	def rollback(self, step, pdc, *, dry_run: bool) -> list[dict]:
		return self.rollback_accounting(step, pdc, dry_run=dry_run)

	def rollback_accounting(self, step, pdc, *, dry_run: bool) -> list[dict]:
		if not step.journal_entry or dry_run:
			return []
		if step.journal_reference_row:
			erpnext_accounting.rollback_journal_reference_row(step.journal_reference_row)
		erpnext_accounting.cancel_journal_entry_voucher(step.journal_entry)
		return erpnext_accounting.refresh_outstanding_for_journal_entry(step.journal_entry)


class OperationalTransitionHandler(TransitionRollbackHandler):
	"""Workflow-only edge (no transition JE on PDC journal references)."""

	def enrich_impact(self, step, pdc) -> None:
		step.impact = {
			"has_accounting": False,
			"note": "Operational transition — no Journal Entry on PDC journal references.",
		}

	def rollback(self, step, pdc, *, dry_run: bool) -> list[dict]:
		return self.rollback_accounting(step, pdc, dry_run=dry_run)

	def rollback_accounting(self, step, pdc, *, dry_run: bool) -> list[dict]:
		return []


_DEFAULT_JE = JournalEntryTransitionHandler()
_DEFAULT_OP = OperationalTransitionHandler()


def get_handler(step: "RollbackTransitionStep") -> TransitionRollbackHandler:
	from erpnext_extensions.cheque_management.pdc_lifecycle_events import EVENT_TYPE_WORKFLOW_ONLY

	if (step.event_type or "").strip() == EVENT_TYPE_WORKFLOW_ONLY:
		return _DEFAULT_OP
	if step.journal_entry or step.journal_reference_row or step.has_accounting:
		return _DEFAULT_JE
	return _DEFAULT_OP
