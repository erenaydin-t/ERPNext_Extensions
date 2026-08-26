# Release 4.6.8 — PM Request Cancel & Delete Eligibility

## Summary

Cancel asks: does this Request have any **open financial process**?
Delete asks: does **accounting history** remain? The two lifecycles stay independent.

## Cancel (open financial process)

- **Payment Entry:** Draft or Submitted blocks; Cancelled does not.
  Authoritative PE list (`list_payment_entries_for_pm_request`) — not `payment_entry` pointer.
- **PM Clearance:** Draft, Pending Approval, Pending Finance Review, Approved,
  Pending Journal Entry Submission, Settled block. Rejected / Cancelled do not.
  Based on Clearance business/workflow state — **not** reservation SQL.
- **Request-level submitted Journal Entry** blocks when present.
- On success: only Request `docstatus` + business `status=Cancelled`.
  Workflow / approvers / PE / Clearance / Versions unchanged.
- After eligibility, Request cancel ignores linked `PM Clearance` for Frappe
  back-link checks (Rejected Clearance keeps submitted child Link rows).

## Delete (history-based — unchanged principle)

- Cancelled: blocked if any PE (including cancelled) or any Clearance allocation.
- Draft: allowed only for mistaken cleanup with zero PE / Clearance.
- Submitted: never deletable (core + validator).

## Explicitly out of scope

- Auto-cancel of PE / Clearance
- Workflow / reservation / funding formula changes
- v4.6.7 PE Desk cancel behavior
