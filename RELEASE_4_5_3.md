# ERPNext Extensions v4.5.3

Petty Management — PM Clearance Finance Review Role Queue.

## Summary

PM Clearance Finance Review no longer depends on a named `finance_supervisor` /
pre-stamped `finance_approver`. Clearance Finance uses a **Role Queue** backed by
native Frappe Workflow Actions.

**PM Request is unchanged** (named `finance_manager` / stamped `finance_approver`).

## What changed

| Area | Behaviour |
|------|-----------|
| **Role Queue** | `PM Settings.clearance_finance_review_role` (default **Petty Management Clearance Reviewer**) |
| **New role** | `Petty Management Clearance Reviewer` — Desk DocPerm read/write/submit/report on PM Clearance |
| **Workflow** | Pending Finance Review transitions allowed for the configured Reviewer Role (no named-user condition) |
| **Workflow Action** | Native Open action per clearance/state; `permitted_roles` includes the Reviewer Role; both reviewers see the same queue item |
| **Assignment Rule** | **PM Clearance Finance Review** Based-on-Field rule is **disabled** (retired for Clearance finance) |
| **Stamp timing** | `finance_approver` stays blank through submit and Manager Approve; stamped **only after** successful Finance Approve/Reject with the **actual reviewer** |
| **Auto-skip** | Clearance Pending Finance Review is **excluded** from consecutive-same-user auto-skip |
| **Email** | Pending Finance Review `send_email = 0` (no role-wide Finance Review email) |
| **Draft PI** | v4.1.5 Finance PI readiness gate preserved exactly |
| **Manager path** | PM Clearance Manager Assignment Rule remains enabled |
| **PM Request** | Named finance architecture unchanged |

## Permission separation

| Role | Purpose |
|------|---------|
| **Petty Management Clearance Reviewer** | Shared Finance Review queue visibility + Workflow Action eligibility on Pending Finance Review |
| **Operational PM Visibility Role** (default Accountant) | Unrestricted list/form visibility for operations — **not** the Finance Review queue role |
| Restricted Petty User | Own employee / named stamps only — does **not** see others’ Pending Finance Review clearances |

## Migration (`migrate_pm_clearance_finance_role_queue_v453`)

Idempotent post-model-sync patch:

1. Ensure **Petty Management Clearance Reviewer** role exists
2. Add required PM Clearance DocPerm for that role (standard DocType permissions — not Custom DocPerm)
3. Default `PM Settings.clearance_finance_review_role`
4. Grant Reviewer role to enabled legacy `finance_supervisor` user (one-time migration grant)
5. Disable legacy **PM Clearance Finance Review** Assignment Rule
6. Hard-cutover in-flight **Pending Finance Review** clearances to Role Queue (clear pre-stamped blank queue eligibility; preserve historical `finance_approver` on already-acted docs)
7. Rebuild Clearance workflow transitions for role-based Finance actions
8. **Does not modify PM Request**

## Tests

| Suite | Result |
|-------|--------|
| `test_pm_clearance_finance_role_queue` (17) | OK |
| `test_pm_clearance_draft_pi` (17) | OK |
| `test_pm_auto_skip_approvals` (11) | OK |
| `test_pm_assignment_rules` (2) | OK |
| Approver stamp + clearance v4.5.3 | OK |
| Permissions / visibility | OK |
| Multi-PE / PE cancel v4.4.6 / Opening Advance / accounting parties | OK |
| PM Clearance settlement suite (45) | OK |
| Lifecycle smoke | OK |

Contract highlights in the 17-test Role Queue suite: dual-reviewer visibility, unrelated-user denial, post-act stamp, role-removal guard, Draft PI block, concurrent approve (exactly one success), Manager AR still enabled, Finance AR disabled, PM Request named finance preserved.

## Playwright / Desk acceptance

Suite: `playwright_pm_clearance_finance_role_queue.mjs` (+ prep helpers).

| Scenario | Result |
|----------|--------|
| Happy path Holder → Manager → Reviewer A/B shared queue → A approves → B blocked | Pass |
| Draft PI block → submit PI → Reviewer B approves | Pass |
| Parallel Finance Approve race (exactly one success) | Pass |
| Workflow Action Open → Completed / `completed_by` = actual reviewer | Pass |
| Finance Review email disabled | Pass |
| Full PM Playwright regression | Pass (form smoke OK on retry) |

Evidence (local only; not committed): `e2e/screenshots/pm_clearance_finance_role_queue_v453/`, `e2e/traces/pm_clearance_finance_role_queue_v453.zip`.

## Version

`erpnext_extensions.__version__` → **4.5.3**
