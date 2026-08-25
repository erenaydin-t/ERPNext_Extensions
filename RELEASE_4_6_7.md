# Release 4.6.7 — PM Request Payment Entry Desk Cancellation

## Summary

Desk Cancel on a funding Payment Entry no longer asks users to cancel the linked
**PM Request**. Cancelling a PE only recalculates Request funding; Request
docstatus, workflow, and approvers stay unchanged.

## Behavior

- Payment Entry form appends `"PM Request"` to `ignore_doctypes_on_cancel_all`
  (additive; ERPNext SI/PI/JE ignore entries remain).
- Server `before_cancel` / `on_cancel` funding and reservation guard logic
  unchanged.
- When cancel is blocked by insufficient remaining funding, the error message
  now includes PE, PM Request, funded-after amount, reserved amount, and
  blocking Clearances.

## Explicitly out of scope

- Auto-cancel / close of PM Request
- Workflow or permission changes
- Reservation formula / funding model changes
- Link field type changes
