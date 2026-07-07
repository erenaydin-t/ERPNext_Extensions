"""Block direct cancellation of Post Dated Cheque (use Rollback Workflow State).

Architecture
------------

PDC lifecycle reversals must go through **Rollback Workflow State** (workflow +
accounting rollback). Standard Frappe **Cancel** (``doc.cancel()``) bypasses that
pipeline and can leave ``workflow_state``, cheque leaf, and journals inconsistent.

Three layers (defense in depth; only ``before_cancel`` is authoritative):

1. **``can_cancel_document`` (whitelisted override via ``hooks.py``)**  
   Frappe's workflow toolbar (``frappe/public/js/frappe/form/toolbar.js``) calls
   ``frappe.model.workflow.can_cancel_document(doctype)`` for every
   workflow-enabled DocType. Frappe provides **no per-doctype hook** for this API.

   This module's ``can_cancel_document`` therefore **registers globally** but
   returns ``False`` only for **Post Dated Cheque** and **immediately delegates**
   every other doctype to ``frappe.model.workflow.can_cancel_document`` (native
   implementation imported from the module, not via ``frappe.call``, so no
   recursion).

2. **``PostDatedCheque.before_cancel``**  
   Enforces the business rule on **all** server paths: desk, ``frappe.client.cancel``,
   REST, bench console, background jobs. Internal utilities may set an approved
   ``frappe.flags`` bypass (see below) inside a tight ``pdc_internal_direct_cancel``
   context.

3. **``hide_standard_cancel_for_pdc`` in ``post_dated_cheque.js``**  
   UX only: hides the secondary **Cancel** button if the toolbar paints it before
   the async ``can_cancel_document`` response or after a rebuild. **Not** a security
   control; server ``before_cancel`` remains authoritative.

Internal bypass flags (``frappe.flags``, request-scoped; never set from desk JS):

- ``in_pdc_workflow_rollback`` — Reserved for rollback execution code paths if a
  submitted PDC ever needs ``doc.cancel()`` during rollback (not used for normal
  rollback today; rollback reverses workflow without cancelling the document).

- ``in_cheque_opening_import_delete`` — **Delete Imported PDC** cleanup only
  (``utils/pdc_import_cleanup.py``): cancel submitted import PDC before delete after
  COI unlink. Administrator-only UI; flag set in ``finally``-scoped context manager.

- ``allow_pdc_direct_cancel`` — **Controlled server fixtures only** (e.g. E2E legacy
  Cancelled PDC with ``docstatus=2``). Not for desk users or public APIs.

See also ``cheque_management/DEVELOPER.md`` — "Direct cancel vs workflow rollback".
"""

from __future__ import annotations

from contextlib import contextmanager

import frappe
from frappe import _

PDC_DIRECT_CANCEL_BLOCKED_MSG = _(
	"Direct cancellation of Post Dated Cheque is not allowed. Use Rollback Workflow State."
)

_INTERNAL_CANCEL_FLAGS = (
	"in_pdc_workflow_rollback",
	"in_cheque_opening_import_delete",
	"allow_pdc_direct_cancel",
)


def pdc_direct_cancel_permitted() -> bool:
	return any(getattr(frappe.flags, name, None) for name in _INTERNAL_CANCEL_FLAGS)


def validate_pdc_direct_cancel_allowed() -> None:
	"""Raise if direct PDC cancel is not covered by an approved internal flag."""
	if pdc_direct_cancel_permitted():
		return
	frappe.throw(PDC_DIRECT_CANCEL_BLOCKED_MSG, title=_("Not Allowed"))


@contextmanager
def pdc_internal_direct_cancel(*, flag: str):
	"""Set an approved internal flag for the duration of ``doc.cancel()`` on a PDC."""
	if flag not in _INTERNAL_CANCEL_FLAGS:
		frappe.throw(_("Invalid internal PDC cancel flag: {0}").format(flag))
	prev = getattr(frappe.flags, flag, None)
	setattr(frappe.flags, flag, True)
	try:
		yield
	finally:
		if prev is None:
			if hasattr(frappe.flags, flag):
				delattr(frappe.flags, flag)
		else:
			setattr(frappe.flags, flag, prev)


@frappe.whitelist()
def can_cancel_document(doctype):
	"""Desk workflow toolbar: hide standard Cancel for PDC; delegate all other doctypes.

	See module docstring for why this is a global whitelisted override.
	"""
	if doctype == "Post Dated Cheque":
		return False
	from frappe.model.workflow import can_cancel_document as _frappe_can_cancel_document

	return _frappe_can_cancel_document(doctype)
