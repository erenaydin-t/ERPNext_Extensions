# Release 4.6.8 — PM Request Cancel & Delete Eligibility

## Summary

**Cancel** and **Delete** are independent lifecycles.

- **Cancel** asks: does this Request have any **open financial process**?
- **Delete** asks: does **accounting history** remain?

Cancel eligibility is **not** based on funding amount, reserved amount, payment status
fields, or historical relationships. Those remain out of scope for Cancel decisions.

## Cancel — open financial process only

### Final state matrix

| Linked document | State | Blocks Request cancel? |
| --- | --- | --- |
| **Payment Entry** | Draft | Yes |
| **Payment Entry** | Submitted | Yes |
| **Payment Entry** | Cancelled | No (historical for Cancel) |
| **PM Clearance** | Draft | Yes |
| **PM Clearance** | Pending Approval (Manager) | Yes |
| **PM Clearance** | Pending Finance Review | Yes |
| **PM Clearance** | Approved | Yes |
| **PM Clearance** | Pending Journal Entry Submission | Yes |
| **PM Clearance** | Settled | Yes |
| **PM Clearance** | Rejected | No (terminal) |
| **PM Clearance** | Cancelled | No (terminal) |
| **Request-level Journal Entry** | Submitted (`docstatus=1`) | Yes |
| **Request-level Journal Entry** | Cancelled / missing / draft | No for Cancel |

Authoritative PE list: `list_payment_entries_for_pm_request` — **not** the
`payment_entry` pointer. Clearance uses business/workflow status — **not**
reservation SQL.

### On successful Cancel

- Only Request `docstatus` + business `status=Cancelled`
- Workflow / approvers / PE / Clearance / Versions unchanged
- Linked `PM Clearance` ignored for Frappe back-link checks after eligibility
  (Rejected Clearance may still have submitted child Link rows)

## Delete — different lifecycle (history-based; unchanged principle)

Delete does **not** reuse Cancel’s open-process rule. It remains history-based:

- **Cancelled:** blocked if any PE (including cancelled), any Clearance allocation,
  or a still-existing Request-level Journal Entry link
- **Draft:** allowed only for mistaken cleanup with zero PE / Clearance / linked JE
- **Submitted:** never deletable (core + validator)

## Explicitly out of scope

- Auto-cancel of PE / Clearance / Journal Entry
- Workflow / reservation / funding formula changes
- Decisions driven by funding amount, reserved amount, or payment status fields
- v4.6.7 PE Desk cancel behavior
