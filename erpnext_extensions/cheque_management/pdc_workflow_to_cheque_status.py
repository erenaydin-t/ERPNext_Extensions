# Copyright (c) 2025, Farbod Siyahpoosh and contributors
# For license information, please see license.txt

"""Derive **operational** ``cheque_status`` from **control** ``workflow_state`` (+ direction).

Why two fields: ``workflow_state`` is the shared ERPNext workflow vocabulary (same eleven states for
both directions). ``cheque_status`` is what accountants and reports expect (“In Hand”, “In Clearing”,
“Returned to Customer”, …) and can differ for the same workflow label by ``cheque_direction``.

**Alignment with journal-centric rules** (design intent; GL posting is implemented in the cheque engine,
not here):

* **Receivable:** **Registered** maps to **In Hand** — the workflow step where **party (AR) is settled**
  for the instrument; later stages describe physical/bank position; **Cleared** is bank vs pool on
  **Journal Entry** only, without Payment Entry in the target design.
* **Payable:** **Registered** is the accounting settlement step (Draft → Registered); **Issued** is operational.
  **Cleared** is bank ↔ pool movement via **Journal Entry** only in the target design.
* **Allocation** (invoices / advances / payment requests) is validated and summarized in
  ``pdc_allocation`` — not in this mapping module.

Output strings are **exact** options from DocType **Post Dated Cheque.cheque_status** (``post_dated_cheque.json``).
**Post Dated Cheque** keeps ``cheque_status`` in sync by calling :func:`map_workflow_state_to_cheque_status`
from ``PostDatedCheque._sync_cheque_status_from_workflow_state`` (``post_dated_cheque.py``):

* ``before_save`` (draft saves — runs after ``validate`` in Frappe’s pipeline)
* ``validate`` (draft + submit + ``before_update_after_submit`` on submitted docs)
* ``before_submit`` (submit only; Frappe does **not** run ``before_save`` on submit)

Debug log (when mapping resolves): ``Mapping workflow_state %s to cheque_status %s`` — Python
:class:`logging.Logger` name ``erpnext_extensions.cheque_management`` (no Frappe site required; safe in tests).

**Receivable** — :data:`RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS`

* Draft → Draft
* Registered → In Hand
* Sent to Bank → In Clearing
* Cleared → Cleared
* Bounced → Bounced
* Returned → Returned to Customer
* Endorsed → Endorsed
* Replaced → Replaced
* Under Legal Action → Under Legal Action
* Cancelled → Cancelled

**Payable** — :data:`PAYABLE_WORKFLOW_TO_CHEQUE_STATUS`

* Draft → Draft
* Registered → Draft *(process step “registered” but instrument not yet issued — still operational Draft)*
* Issued → Issued
* Cleared → Cleared
* Returned → Returned from Payee
* Replaced → Replaced
* Cancelled → Cancelled

Workflow states that are invalid for a direction (e.g. **Issued** on Receivable) have no map row:
:func:`map_workflow_state_to_cheque_status` returns ``None`` and **Post Dated Cheque** blocks save.

See: ``pdc_workflow_state_machine.py``, ``DEVELOPER.md``.
"""

from __future__ import annotations

import logging
from typing import Final, Protocol

from erpnext_extensions.cheque_management.pdc_workflow_state_machine import (
	CHEQUE_DIRECTION_PAYABLE,
	CHEQUE_DIRECTION_RECEIVABLE,
	WORKFLOW_BOUNCED,
	WORKFLOW_CANCELLED,
	WORKFLOW_CLEARED,
	WORKFLOW_DRAFT,
	WORKFLOW_ENDORSED,
	WORKFLOW_ISSUED,
	WORKFLOW_REGISTERED,
	WORKFLOW_REPLACED,
	WORKFLOW_RETURNED,
	WORKFLOW_SENT_TO_BANK,
	WORKFLOW_UNDER_LEGAL_ACTION,
	normalize_workflow_state_value,
)

# --- DocType `cheque_status` Select values used in mappings ---

CHEQUE_STATUS_DRAFT: Final = "Draft"
CHEQUE_STATUS_IN_HAND: Final = "In Hand"
CHEQUE_STATUS_IN_CLEARING: Final = "In Clearing"
CHEQUE_STATUS_CLEARED: Final = "Cleared"
CHEQUE_STATUS_BOUNCED: Final = "Bounced"
CHEQUE_STATUS_RETURNED_TO_CUSTOMER: Final = "Returned to Customer"
CHEQUE_STATUS_RETURNED_FROM_PAYEE: Final = "Returned from Payee"
CHEQUE_STATUS_ENDORSED: Final = "Endorsed"
CHEQUE_STATUS_REPLACED: Final = "Replaced"
CHEQUE_STATUS_UNDER_LEGAL_ACTION: Final = "Under Legal Action"
CHEQUE_STATUS_CANCELLED: Final = "Cancelled"
CHEQUE_STATUS_ISSUED: Final = "Issued"

# Keys = Workflow State names; values = Cheque Status Select labels (must exist on DocType).
RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS: Final[dict[str, str]] = {
	WORKFLOW_DRAFT: CHEQUE_STATUS_DRAFT,
	WORKFLOW_REGISTERED: CHEQUE_STATUS_IN_HAND,
	WORKFLOW_SENT_TO_BANK: CHEQUE_STATUS_IN_CLEARING,
	WORKFLOW_CLEARED: CHEQUE_STATUS_CLEARED,
	WORKFLOW_BOUNCED: CHEQUE_STATUS_BOUNCED,
	WORKFLOW_RETURNED: CHEQUE_STATUS_RETURNED_TO_CUSTOMER,
	WORKFLOW_ENDORSED: CHEQUE_STATUS_ENDORSED,
	WORKFLOW_REPLACED: CHEQUE_STATUS_REPLACED,
	WORKFLOW_UNDER_LEGAL_ACTION: CHEQUE_STATUS_UNDER_LEGAL_ACTION,
	WORKFLOW_CANCELLED: CHEQUE_STATUS_CANCELLED,
}

PAYABLE_WORKFLOW_TO_CHEQUE_STATUS: Final[dict[str, str]] = {
	WORKFLOW_DRAFT: CHEQUE_STATUS_DRAFT,
	# Registered: workflow step taken; physical cheque not "Issued" yet — keep operational label Draft.
	WORKFLOW_REGISTERED: CHEQUE_STATUS_DRAFT,
	WORKFLOW_ISSUED: CHEQUE_STATUS_ISSUED,
	WORKFLOW_CLEARED: CHEQUE_STATUS_CLEARED,
	WORKFLOW_RETURNED: CHEQUE_STATUS_RETURNED_FROM_PAYEE,
	WORKFLOW_REPLACED: CHEQUE_STATUS_REPLACED,
	WORKFLOW_CANCELLED: CHEQUE_STATUS_CANCELLED,
}

_STATUS_MAP_BY_DIRECTION: Final[dict[str, dict[str, str]]] = {
	CHEQUE_DIRECTION_RECEIVABLE: RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS,
	CHEQUE_DIRECTION_PAYABLE: PAYABLE_WORKFLOW_TO_CHEQUE_STATUS,
}

_cheque_status_map_logger = logging.getLogger("erpnext_extensions.cheque_management")


class PDCWorkflowChequeStatusSource(Protocol):
	"""Minimal shape for :func:`get_cheque_status_from_workflow` (Frappe Document or test double)."""

	cheque_direction: str | None
	workflow_state: str | None


def map_workflow_state_to_cheque_status(
	cheque_direction: str,
	workflow_state: str | None,
) -> str | None:
	"""Return ``cheque_status`` for a Post Dated Cheque from ``workflow_state``.

	``cheque_direction`` must be **Receivable** or **Payable** (DocType field). Uses
	:data:`RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS` or :data:`PAYABLE_WORKFLOW_TO_CHEQUE_STATUS`
	(module docstring lists the full tables).

	``workflow_state`` is normalized with :func:`~pdc_workflow_state_machine.normalize_workflow_state_value`
	(blank/None → Draft).

	Returns:
		The mapped ``cheque_status`` label (must exist on the DocType Select), or ``None`` if
		``cheque_direction`` is unknown or there is no mapping for that workflow state on this
		direction (e.g. **Issued** on Receivable).
	"""
	if cheque_direction not in _STATUS_MAP_BY_DIRECTION:
		return None
	ws = normalize_workflow_state_value(workflow_state)
	status = _STATUS_MAP_BY_DIRECTION[cheque_direction].get(ws)
	if status is not None:
		_cheque_status_map_logger.debug(
			"Mapping workflow_state %s to cheque_status %s",
			ws,
			status,
		)
	return status


def get_cheque_status_from_workflow(doc: PDCWorkflowChequeStatusSource) -> str | None:
	"""Return mapped ``cheque_status`` from a PDC-shaped object.

	Reads ``cheque_direction`` and ``workflow_state``; delegates to
	:func:`map_workflow_state_to_cheque_status`. For unit tests without a document, call
	:func:`map_workflow_state_to_cheque_status` with primitives.
	"""
	return map_workflow_state_to_cheque_status(
		getattr(doc, "cheque_direction", None),
		getattr(doc, "workflow_state", None),
	)


# Backward-compatible alias (same as older docs / modules)
get_cheque_status_for_workflow_state = map_workflow_state_to_cheque_status

__all__ = [
	"CHEQUE_STATUS_BOUNCED",
	"CHEQUE_STATUS_CANCELLED",
	"CHEQUE_STATUS_CLEARED",
	"CHEQUE_STATUS_DRAFT",
	"CHEQUE_STATUS_ENDORSED",
	"CHEQUE_STATUS_IN_CLEARING",
	"CHEQUE_STATUS_IN_HAND",
	"CHEQUE_STATUS_ISSUED",
	"CHEQUE_STATUS_REPLACED",
	"CHEQUE_STATUS_RETURNED_FROM_PAYEE",
	"CHEQUE_STATUS_RETURNED_TO_CUSTOMER",
	"CHEQUE_STATUS_UNDER_LEGAL_ACTION",
	"PDCWorkflowChequeStatusSource",
	"PAYABLE_WORKFLOW_TO_CHEQUE_STATUS",
	"RECEIVABLE_WORKFLOW_TO_CHEQUE_STATUS",
	"get_cheque_status_for_workflow_state",
	"get_cheque_status_from_workflow",
	"map_workflow_state_to_cheque_status",
]
