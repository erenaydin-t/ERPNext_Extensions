from __future__ import annotations

"""PM Clearance lifecycle, action matrix, and accounting lock (single source of truth)."""

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint

# Business lifecycle values stored on ``PM Clearance.status``.
LIFECYCLE_DRAFT = "Draft"
LIFECYCLE_PENDING_REVIEW = "Pending Finance Review"
LIFECYCLE_APPROVED = "Approved"
LIFECYCLE_PENDING_JE = "Pending Journal Entry Submission"
LIFECYCLE_SETTLED = "Settled"
LIFECYCLE_REJECTED = "Rejected"
LIFECYCLE_CANCELLED = "Cancelled"

TERMINAL_LIFECYCLE = frozenset({LIFECYCLE_REJECTED, LIFECYCLE_CANCELLED})


def workflow_state_title(ws_link: str | None) -> str:
	if not ws_link:
		return ""
	return (frappe.db.get_value("Workflow State", ws_link, "workflow_state_name") or ws_link or "").strip()


def journal_entry_docstatus(journal_entry: str | None) -> int | None:
	if not journal_entry or not frappe.db.exists("Journal Entry", journal_entry):
		return None
	return cint(frappe.db.get_value("Journal Entry", journal_entry, "docstatus"))


def is_accounting_locked(doc: Document | str) -> bool:
	"""Submitted settlement JE exists — workflow reject/rollback and clearance cancel are blocked."""
	if isinstance(doc, str):
		doc = frappe.get_doc("PM Clearance", doc)
	je = (getattr(doc, "journal_entry", None) or "").strip()
	return journal_entry_docstatus(je) == 1


def has_active_settlement_je(doc: Document) -> bool:
	"""Any linked JE that is not cancelled (draft or submitted)."""
	je = (getattr(doc, "journal_entry", None) or "").strip()
	ds = journal_entry_docstatus(je)
	return ds is not None and ds in (0, 1)


def ensure_workflow_state_record(lifecycle: str) -> str | None:
	"""Ensure a Workflow State row exists for lifecycle title; return link name."""
	title = (lifecycle or "").strip()
	if not title:
		return None
	name = frappe.db.get_value("Workflow State", {"workflow_state_name": title}, "name")
	if name:
		return name
	if frappe.db.exists("Workflow State", title):
		return title
	doc = frappe.new_doc("Workflow State")
	doc.workflow_state_name = title
	doc.insert(ignore_permissions=True)
	return doc.name


def workflow_state_link_for_lifecycle(lifecycle: str) -> str | None:
	return ensure_workflow_state_record(lifecycle)


def lifecycle_from_workflow(doc: Document) -> str:
	ws = (getattr(doc, "workflow_state", None) or "").strip()
	if not ws:
		return LIFECYCLE_DRAFT
	title = workflow_state_title(ws)
	mapping = {
		"Draft": LIFECYCLE_DRAFT,
		"Pending Finance Review": LIFECYCLE_PENDING_REVIEW,
		"Approved": LIFECYCLE_APPROVED,
		"Rejected": LIFECYCLE_REJECTED,
		"Pending Journal Entry Submission": LIFECYCLE_PENDING_JE,
		"Settled": LIFECYCLE_SETTLED,
		"Cancelled": LIFECYCLE_CANCELLED,
	}
	return mapping.get(title, title or LIFECYCLE_DRAFT)


def compute_lifecycle_status(doc: Document) -> str:
	"""Derive business lifecycle from JE (accounting wins) then workflow."""
	if cint(getattr(doc, "docstatus", 0)) == 2:
		return LIFECYCLE_CANCELLED

	je = (getattr(doc, "journal_entry", None) or "").strip()
	je_ds = journal_entry_docstatus(je) if je else None
	if je_ds == 1:
		return LIFECYCLE_SETTLED
	if je_ds == 0:
		return LIFECYCLE_PENDING_JE

	lifecycle = lifecycle_from_workflow(doc)
	# Workflow row may still say Settled / Pending JE after JE cancel or unlink — not valid without JE.
	if lifecycle in (LIFECYCLE_SETTLED, LIFECYCLE_PENDING_JE):
		ws_title = workflow_state_title(getattr(doc, "workflow_state", None))
		if ws_title == "Pending Finance Review":
			return LIFECYCLE_PENDING_REVIEW
		if ws_title == "Rejected":
			return LIFECYCLE_REJECTED
		if ws_title == "Cancelled":
			return LIFECYCLE_CANCELLED
		if ws_title == "Draft" or not ws_title:
			return LIFECYCLE_DRAFT
		return LIFECYCLE_APPROVED

	return lifecycle


def sync_clearance_lifecycle(doc: Document, *, persist: bool = False) -> str:
	"""Set ``status`` and align ``workflow_state`` so list/form never contradict on lifecycle.

	Accounting states override approval workflow display. Returns computed lifecycle.
	"""
	lifecycle = compute_lifecycle_status(doc)
	doc.status = lifecycle

	ws_link = workflow_state_link_for_lifecycle(lifecycle)
	if ws_link:
		doc.workflow_state = ws_link

	if persist and getattr(doc, "name", None):
		values = {"status": lifecycle}
		if ws_link:
			values["workflow_state"] = ws_link
		frappe.db.set_value("PM Clearance", doc.name, values, update_modified=False)

	return lifecycle


def sync_clearance_lifecycle_if_stale(doc: Document) -> str:
	"""Persist lifecycle + workflow when DB row disagrees with accounting-derived state."""
	lifecycle = sync_clearance_lifecycle(doc, persist=False)
	if not getattr(doc, "name", None):
		return lifecycle
	# New documents: name is set in autoname but row is not inserted yet — never UPDATE here.
	if doc.get("__islocal") or getattr(getattr(doc, "flags", None), "in_insert", False):
		return lifecycle

	ws_link = workflow_state_link_for_lifecycle(lifecycle)
	stored_status = (frappe.db.get_value("PM Clearance", doc.name, "status") or "").strip()
	stored_ws = frappe.db.get_value("PM Clearance", doc.name, "workflow_state")
	if stored_status != lifecycle or (ws_link and stored_ws != ws_link):
		sync_clearance_lifecycle(doc, persist=True)
	return lifecycle


# Backward-compatible alias used across services/tests
def sync_clearance_status_from_workflow(doc: Document) -> None:
	sync_clearance_lifecycle(doc, persist=False)


def _pm_clearance_workflow_defines_reject(doc: Document) -> bool:
	"""True when PM Reject is defined from the clearance's current workflow state."""
	from erpnext_extensions.petty_management.services.workflow_utils import resolve_workflow_state_link

	ws = (getattr(doc, "workflow_state", None) or "").strip()
	if not ws:
		return False
	canonical_ws = resolve_workflow_state_link(ws) or ws
	ws_title = workflow_state_title(ws)

	wf_name = frappe.db.get_value("Workflow", {"document_type": "PM Clearance", "is_active": 1}, "name")
	if not wf_name:
		return False
	for row in frappe.get_all(
		"Workflow Transition",
		filters={"parent": wf_name, "action": "PM Reject"},
		fields=["state"],
	):
		state_link = (row.get("state") or "").strip()
		if not state_link:
			continue
		canonical_state = resolve_workflow_state_link(state_link) or state_link
		if canonical_state == canonical_ws or state_link == ws:
			return True
		if ws_title and workflow_state_title(state_link) == ws_title:
			return True
	return False


def get_pm_clearance_action_flags(pm_clearance: str | Document) -> dict:
	doc = frappe.get_doc("PM Clearance", pm_clearance) if isinstance(pm_clearance, str) else pm_clearance
	if not frappe.has_permission("PM Clearance", "read", doc=doc):
		frappe.throw(_("Not permitted"), frappe.PermissionError)

	lifecycle = compute_lifecycle_status(doc)
	locked = is_accounting_locked(doc)
	je = (doc.journal_entry or "").strip()
	je_ds = journal_entry_docstatus(je)

	terminal = lifecycle in TERMINAL_LIFECYCLE or cint(doc.docstatus) == 2
	approved = lifecycle == LIFECYCLE_APPROVED or clearance_is_approved_for_actions(doc, lifecycle)
	submitted_doc = cint(doc.docstatus) == 1

	can_preview = bool(doc.name) and cint(doc.docstatus) in (0, 1) and not terminal
	can_settle = (
		submitted_doc
		and approved
		and not je
		and not terminal
		and lifecycle not in (LIFECYCLE_SETTLED, LIFECYCLE_PENDING_JE)
	)
	can_open_je = bool(je and frappe.db.exists("Journal Entry", je))
	can_reject = (
		submitted_doc
		and not locked
		and not has_active_settlement_je(doc)
		and lifecycle not in (LIFECYCLE_SETTLED, LIFECYCLE_PENDING_JE, LIFECYCLE_REJECTED, LIFECYCLE_CANCELLED)
	)
	from erpnext_extensions.petty_management.services.workflow_utils import get_allowed_workflow_actions

	wf_actions = [t.get("action") for t in get_allowed_workflow_actions(doc) if t.get("action")]
	has_reject_transition = (
		lifecycle == LIFECYCLE_APPROVED
		or "PM Reject" in wf_actions
		or _pm_clearance_workflow_defines_reject(doc)
	)
	if can_reject and not has_reject_transition:
		can_reject = False
	can_cancel = cint(doc.docstatus) == 1 and not locked and lifecycle != LIFECYCLE_CANCELLED

	expected_ws = workflow_state_link_for_lifecycle(lifecycle) or doc.workflow_state

	return {
		"can_preview": can_preview,
		"can_settle": can_settle,
		"can_reject": can_reject,
		"can_cancel": can_cancel,
		"can_open_je": can_open_je,
		"accounting_locked": locked,
		"lifecycle_state": lifecycle,
		"journal_entry": je,
		"journal_entry_docstatus": je_ds,
		"workflow_state": expected_ws,
		"workflow_state_title": lifecycle,
		"allowed_workflow_actions": wf_actions,
		"docstatus": cint(doc.docstatus),
	}


def clearance_is_approved_for_actions(doc: Document, lifecycle: str) -> bool:
	if lifecycle == LIFECYCLE_APPROVED:
		return True
	ws = (getattr(doc, "workflow_state", None) or "").strip()
	return workflow_state_title(ws) == "Approved"


def validate_pm_clearance_workflow_change(doc: Document) -> None:
	"""Block invalid workflow transitions (including API / Workflow Action)."""
	before = doc.get_doc_before_save() if hasattr(doc, "get_doc_before_save") else None
	if not before:
		return

	old_ws = before.get("workflow_state")
	new_ws = doc.get("workflow_state")
	if old_ws == new_ws:
		return

	new_title = workflow_state_title(new_ws)

	if is_accounting_locked(doc):
		frappe.throw(
			_(
				"Workflow cannot change while settlement Journal Entry {0} is submitted. "
				"Cancel the Journal Entry through accounting first."
			).format(doc.journal_entry),
			title=_("Accounting locked"),
		)

	if new_title == "Rejected" and has_active_settlement_je(doc):
		frappe.throw(
			_("Cannot reject PM Clearance while a settlement Journal Entry exists. Cancel the Journal Entry first."),
			title=_("Reject not allowed"),
		)


def validate_apply_workflow_action(doc: Document, action: str) -> None:
	"""Called before workflow action is applied (via hook)."""
	if (action or "").strip() == "PM Reject":
		if is_accounting_locked(doc):
			frappe.throw(
				_("Cannot reject after settlement Journal Entry is submitted."),
				title=_("Accounting locked"),
			)
		if has_active_settlement_je(doc):
			frappe.throw(
				_("Cannot reject while a settlement Journal Entry is linked. Cancel the Journal Entry first."),
				title=_("Reject not allowed"),
			)
