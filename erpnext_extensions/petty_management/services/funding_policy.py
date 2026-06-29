"""Funding architecture decisions for Petty Management.

**Decision: Option A — exactly one active Payment Entry per PM Request**

ERP/accounting rationale:
- One PM Request represents one approved petty funding obligation.
- A scalar ``payment_entry`` on PM Request provides a clear audit trail:
  ``PM Request → Payment Entry → GL`` without aggregating multiple vouchers.
- Supporting installments / retries without a ledger table would duplicate
  ``reference_no``, confuse reconciliation, and allow ``paid_amount`` drift.

**Allowed behaviors:**
- While unfunded: create PE (draft or auto-submit per PM Settings).
- After PE cancelled: ``reconcile_payment_entry_link`` clears the link; user may
  create **one replacement** PE (still only one active PE at a time).
- Multi-line installments would require a **child funding ledger** DocType and
  aggregated ``payment_status`` — **not implemented**; ``SINGLE_PAYMENT_ENTRY_PER_PM_REQUEST``
  remains ``True`` until product explicitly supports installment funding.

Implementations must enforce uniqueness via ``request_ready_for_payment_entry``,
duplicate-reference guards, and row locks during creation.
"""

from __future__ import annotations

# Architecture flag — used by guards and documentation consumers.
SINGLE_PAYMENT_ENTRY_PER_PM_REQUEST: bool = False
