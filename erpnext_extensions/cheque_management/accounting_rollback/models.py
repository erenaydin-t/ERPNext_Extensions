from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class RollbackTransitionStep:
	"""One workflow edge to undo, anchored on PDC Journal Reference when present."""

	from_state: str
	to_state: str
	transition_key: str | None = None
	journal_entry: str | None = None
	journal_reference_row: str | None = None
	purpose: str | None = None
	has_accounting: bool = False
	# Enriched at plan time (dry-run and execute share this)
	impact: dict[str, Any] = field(default_factory=dict)


@dataclass
class RollbackPlan:
	"""Ordered rollback steps (newest transition first) + instrument/workflow consequences."""

	source_doctype: str
	source_name: str
	current_workflow_state: str
	target_workflow_state: str
	reason: str = ""
	steps: list[RollbackTransitionStep] = field(default_factory=list)
	workflow_changes: dict[str, Any] = field(default_factory=dict)
	leaf_changes: dict[str, Any] = field(default_factory=dict)
	blockers: list[str] = field(default_factory=list)

	def to_api_dict(self) -> dict[str, Any]:
		"""API payload for preview + execute response (backward compatible keys included)."""
		docs: list[dict[str, Any]] = []
		for step in self.steps:
			if step.journal_entry:
				docs.append(
					{
						"doctype": "Journal Entry",
						"name": step.journal_entry,
						"transition": f"{step.from_state} → {step.to_state}",
						"purpose": step.purpose,
						"transition_key": step.transition_key,
						"impact": step.impact,
					}
				)
		return {
			"current_state": self.current_workflow_state,
			"target_state": self.target_workflow_state,
			"business_impact": {
				"workflow": self.workflow_changes,
				"cheque_leaf": self.leaf_changes,
				"accounting_steps": len([s for s in self.steps if s.has_accounting or s.journal_entry]),
				"operational_steps": len([s for s in self.steps if not s.journal_entry and not s.has_accounting]),
			},
			"steps": [
				{
					"from_state": s.from_state,
					"to_state": s.to_state,
					"transition_key": s.transition_key,
					"journal_entry": s.journal_entry,
					"journal_reference_row": s.journal_reference_row,
					"purpose": s.purpose,
					"has_accounting": s.has_accounting,
					"impact": s.impact,
				}
				for s in self.steps
			],
			"transitions_to_undo": [{"from": s.from_state, "to": s.to_state} for s in self.steps],
			"documents_to_remove": docs,
			"workflow_changes": self.workflow_changes,
			"leaf_changes": self.leaf_changes,
			"blockers": self.blockers,
		}
