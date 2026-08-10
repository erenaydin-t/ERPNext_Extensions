# Petty Management 4.1.4 — Role collapse + consecutive auto-skip

## Summary

1. **Functional roles reduced to two:** Petty Management User, Petty Management Accountant.
2. **Workflow Allowed Roles** no longer use Manager for Manager/CEO stages; stamp conditions remain mandatory. Never Allowed Role = All.
3. **Consecutive same-user Approve auto-skip** (loop): after Approve, while the session user is the stamped next approver *and* Frappe exposes that Approve transition, auto-apply Approve with full audit trail.
4. **Assignment Rules** refresh after each hop; after the skip loop only the real pending approver keeps an Open ToDo.
5. **DocPerm / reports** migrated off Admin / Manager / Auditor. **Accountant never has delete** on transactional PM doctypes (System Manager break-glass only).
6. **Legacy Manager → User grant:** enabled users holding Petty Management Manager also receive Petty Management User (idempotent). Legacy role assignments are not removed.

## Deprecated roles (v4.1.4)

These Role masters remain installed for compatibility (Has Role / visibility-role picker):

- Petty Management Manager
- Petty Management Admin
- Petty Management Auditor

They have **no unique functional DocPerm or Workflow Allowed Role** after migration.

Operational permissions now use:

- **Petty Management User**
- **Petty Management Accountant**
- **System Manager** for break-glass administration (including delete)

Admin/Auditor are **not** auto-mapped to Accountant (would broaden rights). Sites should reassign those users intentionally.

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
| Petty Management Accountant | Finance Approve+Reject when stamped; Opening Advance create/submit/cancel/amend (**not delete**); Settings write; Holder write (**not delete**) |
| System Manager | Break-glass cancel/delete/amend |
| Manager / Admin / Auditor | **Deprecated** — no unique DocPerm |

## Permission migration map

| From (deprecated) | To | What moved |
|--|--|--|
| Petty Management Admin (PM Request/Clearance cancel/delete/amend) | System Manager (delete + cancel/amend); Accountant (cancel/amend only) | Admin destructive rights |
| Petty Management Manager (workflow Allowed Role) | Petty Management User + stamp | Manager/CEO Approve |
| Petty Management Auditor (read-only) | User / Accountant (already can read) | Report roles dropped Auditor |
| Opening Advance Admin/Manager | System Manager (full including delete) + Accountant (create/submit/cancel/amend, **no delete**) | Opening Advance without Admin |
| PM Settings Admin write | System Manager (+ Accountant write retained) | Settings adminship |

## Auto-skip

- Primary gate: `session.user == stamped_approver` for that exact stage; then Frappe `get_transitions` must expose the Approve.
- Only Approve actions (`PM Manager Approve`, `PM CEO Approve`, `PM Finance Approve`, Clearance `PM Approve`).
- Never Reject / funding / Close / Payment Entry / `db_set workflow_state`.
- Each hop: normal `apply_workflow` → Workflow Action / Version / Timeline.
- After loop: close non-current Open ToDos; re-apply Assignment Rules; dedupe Open ToDos for the pending assignee.
- **Emails:** no custom PM email layer. Core Frappe Workflow / Assignment Rule emails (if site-configured) are not suppressed — invasive core overrides were avoided.

## Migration

Patches (idempotent):

- `migrate_pm_roles_autoskip_v414`
- `reapply_pm_roles_autoskip_v414` (re-runs the same execute for sites that already applied the first patch)

Does **not** mutate payment amounts / PE / `payment_status`.

## Tests

- `test_pm_auto_skip_approvals` — skip scenarios, ToDos, DocPerm delete=false
- `test_pm_roles_autoskip_migration_v414` — Manager→User grant + idempotency + DocPerm
