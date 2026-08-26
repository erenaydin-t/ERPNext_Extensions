# Release 4.6.8 — PM Request Cancel & Delete Eligibility

## Summary

Submitted PM Requests may be cancelled only when funding is zero and no
blocking Clearance exists. Cancelled (and clean Draft) Requests may be deleted
only when no Payment Entry or Clearance history remains.

## Cancel

- Authoritative funding: `sum_submitted_pe_amount` (not `payment_entry` pointer).
- Block draft PEs and non-terminal Clearances (Rejected/Cancelled Clearance OK).
- After eligibility, Request cancel ignores linked `PM Clearance` for Frappe
  back-link checks (Rejected Clearance keeps submitted child Link rows).
- On cancel: business `status=Cancelled`; `workflow_state` / approvers unchanged.

## Delete

- Cancelled: blocked if any PE (including cancelled) or any Clearance allocation.
- Draft: allowed only for mistaken cleanup with zero PE / Clearance.
- Submitted: never deletable (core + validator).

## Explicitly out of scope

- Auto-cancel of PE / Clearance
- Workflow / reservation / funding formula changes
- v4.6.7 PE Desk cancel behavior
