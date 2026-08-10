# Petty Management 4.1.4 — Role collapse + consecutive auto-skip

## Summary

1. **Functional roles reduced to two:** Petty Management User, Petty Management Accountant.
2. **Workflow Allowed Roles** no longer use Manager for Manager/CEO stages; stamp conditions remain mandatory. Never Allowed Role = All.
3. **Consecutive same-user Approve auto-skip** (loop): after Approve, while the session user is the stamped next approver *and* holds the next transition’s Allowed Role, auto-apply Approve with full audit trail.
4. **Assignment Rules** refresh after each hop (close prior ToDos, create next).
5. **DocPerm / reports** migrated off Admin / Manager / Auditor.
6. Legacy roles **kept installed (deprecated)** for one release for Has Role backward compatibility.

## Architecture (unchanged domain split)

| Layer | Responsibility |
|--|--|
| Workflow | Approval only → terminal **Finance Approved** |
| Business `status` | Operational lifecycle (Waiting for Payment / Paid / Closed…) |
| `payment_status` | Funding lifecycle |
| `is_closed` | Operational freeze |
| Payment Entry | Never writes `workflow_state` / never `apply_workflow` |

## Role model

| Role | Responsibility |
|--|--|
| Petty Management User | Create/submit requests & clearances; Manager/CEO Approve+Reject when stamped |
| Petty Management Accountant | Finance Approve+Reject when stamped; Opening Advance submit/cancel/delete; Settings write; Holder write |
| System Manager | Break-glass cancel/delete/amend where Admin previously held exclusive rights |
| Manager / Admin / Auditor | **Deprecated** — no unique DocPerm; may still be selected as Operational Visibility Role |

## Permission migration map

| From (deprecated) | To | What moved |
|--|--|--|
| Petty Management Admin (PM Request/Clearance cancel/delete/amend) | System Manager + Accountant (cancel/amend); System Manager (delete) | Admin-only destructive rights |
| Petty Management Manager (create/submit on Request/Clearance) | Petty Management User (already had) | Workflow Allowed Role → User |
| Petty Management Auditor (read-only) | User / Accountant (already can read) | Report roles dropped Auditor |
| Opening Advance Admin/Manager cancel/delete/submit | System Manager (full) + Accountant (create/submit/cancel/amend/delete) | Opening Advance operable without Admin |
| PM Settings Admin write | System Manager (+ Accountant write retained) | Settings adminship |

## Auto-skip

- Only Approve actions (`PM Manager Approve`, `PM CEO Approve`, `PM Finance Approve`, Clearance `PM Approve`).
- Never Reject / funding / Close / Payment Entry.
- Each hop: normal `apply_workflow` → Workflow Action / Version / Timeline.
- After each hop: Assignment Rule `apply` (no orphan ToDos).

## Migration

Patch: `migrate_pm_roles_autoskip_v414` (idempotent)

- Rebuilds PM Request + Clearance workflows
- Reseeds Assignment Rules
- Syncs DocPerm + report roles
- Does **not** mutate payment amounts / PE / `payment_status`

## Tests

- `test_pm_auto_skip_approvals` — Manager-only, CEO-only, Manager=CEO, Manager=CEO=Finance, distinct chain, action visibility, reject no-skip, clearance auto-skip, Opening Advance DocPerm
