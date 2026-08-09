# Petty Management 4.0.2 — Multi-level approval with native Assignment Rules

## Summary

Approval routing and business lifecycle are separated. Workflow owns approval only;
`status` / `payment_status` / Journal Entry own business state. Accounting events
never write `workflow_state`.

## Highlights

- **Manager → CEO → Finance** approval chain on PM Request
- **Manager → Finance** approval chain on PM Clearance
- **Native Frappe Assignment Rule** routing (no custom ToDo / `assign_to` approval engine)
- Approver stamp service resolves and stamps User fields on Submit only
- Workflow transition conditions bind actions to stamped approvers
- Clearance workflow no longer uses Settled / Pending JE as workflow states
- JE submit/cancel updates clearance **status** only; workflow stays Approved
- Idempotent migration patch `migrate_pm_workflow_v402`
- Unit, integration, smoke, and Playwright multi-approval coverage

## Workflow states

### PM Request

Draft → Pending Manager Approval → Pending CEO Approval → Pending Finance Approval → Waiting for Payment | Rejected

### PM Clearance

Draft → Pending Manager Approval → Pending Finance Review → Approved | Rejected

Business-only clearance statuses: Pending Journal Entry Submission, Settled (driven by JE).

## Migration

Patch: `erpnext_extensions.patches.post_model_sync.migrate_pm_workflow_v402`

- Remaps legacy Pending Approval / Approved request states
- Rewinds clearance Settled / Pending JE workflow titles to Approved
- Seeds Assignment Rules for each approval stage
- Idempotent; safe for production re-run

## Settings

PM Settings: `ceo_approver`, `finance_manager`, `finance_supervisor`, `require_named_manager_approver`

## Tests

- `test_approver_stamp_service`, `test_pm_business_status`, `test_pm_assignment_rules`
- `test_pm_multi_approval_integration`
- Smoke: `pm_lifecycle_e2e`, `pm_multi_pe_e2e`, `final_acceptance_opening_clearance`
- Playwright: `playwright_pm_request_multi_approval.mjs`, `playwright_pm_clearance_multi_approval.mjs`
