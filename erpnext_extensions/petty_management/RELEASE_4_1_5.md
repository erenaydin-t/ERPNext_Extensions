# Petty Management 4.1.5 — Draft Purchase Invoice on PM Clearance

## Summary

Holders may select **Draft** Purchase Invoices (`docstatus=0`) on PM Clearance through
Save, initial Submit, Manager Approval, and Pending Finance Review.

**Finance Approval**, **Preview Settlement**, and **Settle / Journal Entry** remain blocked
until **every** referenced Purchase Invoice is submitted (`docstatus=1`).

Cancelled PIs (`docstatus=2`) are never allowed.

## Locked rules

| Stage | Draft PI | Submitted PI | Cancelled |
|--|--|--|--|
| Lookup / Save / Submit / Manager | Allowed | Allowed | Blocked |
| Finance Approval | Blocked | Required for all lines | Blocked |
| Preview / Settle / JE | Blocked | Required | Blocked |

- No new workflow state (stays `Pending Finance Review` + `Pending Approval` while waiting).
- Failed Finance Approval leaves Finance Assignment / ToDo open.
- Draft allocation ceiling = PI `grand_total`.
- Finance/Settle re-read PI from DB; never silently rewrite `allocated_amount`.
- Block if allocated > final outstanding, or supplier/company drift.
- Submitted PI with zero outstanding excluded from lookup.
- Purchase Order / Supplier Advance remains submitted-only (out of scope).

## Approval bypass (hardening)

`approve_pm_clearance_for_reservation` / whitelisted `approve_pm_clearance_for_settlement`
must call `validate_purchase_invoices_for_finance_approval` before writing
`workflow_state` / `status = Approved` (same gate as Desk Finance Approve).
Draft PI cannot activate funding reservation via this helper.

## Domain service

`petty_management/services/purchase_invoice_readiness.py` — single source of truth for:

- `get_purchase_invoice_readiness`
- `validate_purchase_invoices_for_prepare`
- `validate_purchase_invoices_for_finance_approval`
- `validate_purchase_invoices_for_settlement`

## Tests / E2E results (ship gate)

| Suite | Result |
|--|--|
| `tests/test_pm_clearance_draft_pi` (16) | OK |
| `tests/test_pm_clearance` (updated Draft allow/include) | OK |
| `tests/test_pm_clearance_settlement_query` | OK |
| `smoke/run_pm_regression.sh` | **exit=0** (all RESULT OK) |
| Playwright `playwright_pm_clearance_draft_pi_e2e.mjs` | **ok: true** |

Playwright covered: Finance warning + blocked approve (exact PI in message) + ToDo remains Open → submit PI → Finance Approve → Settle → JE references submitted PI. Screenshots/trace under `e2e/screenshots|traces/pm_clearance_draft_pi_e2e*`. Holder Save/Submit and Manager Approve for the fixture are exercised in prep + unit/integration lifecycle (`test_full_lifecycle_draft_then_submit_then_settle`).
