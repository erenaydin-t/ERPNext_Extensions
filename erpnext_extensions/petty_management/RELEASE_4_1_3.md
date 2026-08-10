# Petty Management 4.1.3 — List permissions + Finance Approved domain model

## Summary

1. Fixed restricted-user list crash (`User.employee` missing column).
2. Named approvers can open stamped docs without elevated roles.
3. **Configurable operational unrestricted visibility role** via PM Settings
   (`Operational PM Visibility Role`), default **Petty Management Accountant**.
4. **Option A domain model:** PM Request workflow is approval-only. Terminal workflow
   state renamed **Waiting for Payment → Finance Approved**. Payment lifecycle is
   exclusively `status` / `payment_status` / `is_closed`. Payment Entry never writes
   `workflow_state` and never calls `apply_workflow`.
5. **Close PM Request** synchronizes `status=Closed` immediately when `is_closed=1`.

## Workflow (approval only)

Draft → Pending Manager Approval → Pending CEO Approval → Pending Finance Approval → **Finance Approved** | Rejected

## Business status (user-facing lifecycle)

Includes Waiting for Payment, Partially Paid, Paid, Closed (and pending approval stages).

## Payment status

Not Paid | Partially Paid | Paid

## Migration

Patch: `migrate_pm_request_finance_approved_v413` (idempotent)

- Rebuilds PM Request workflow + Assignment Rule close conditions
- Remaps document `workflow_state` Waiting for Payment / Approved → Finance Approved
- Does **not** change payment amounts, Payment Entries, or `payment_status` values beyond status sync

Helper `request_is_finance_cleared()` accepts **Finance Approved** and legacy **Waiting for Payment**.

## Visibility model

| Actor | PM Request / Clearance visibility |
|--|--|
| Administrator / System Manager | Unrestricted |
| Role in PM Settings → Operational PM Visibility Role | Unrestricted (default: Accountant) |
| Petty Management User (holder) | Own employee only |
| Named manager / CEO / finance approver | Stamped docs only |

## Tests / E2E

- `test_pm_request_funding_status_ux` (Finance Approved + status lifecycle)
- Playwright: `playwright_pm_request_multi_approval.mjs`, `playwright_pm_request_funding_status_ux.mjs`
