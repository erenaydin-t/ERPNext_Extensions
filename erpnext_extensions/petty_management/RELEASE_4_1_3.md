# Petty Management 4.1.3 — Fix PM list permissions for restricted users

## Summary

PM Request / PM Clearance List View failed for normal Petty Management users with:

```text
MySQLdb.OperationalError: (1054, "Unknown column 'employee' in 'SELECT'")
```

Administrator was unaffected.

## Root cause

`permissions._user_employee` selected `User.employee`, but this site (standard HRMS)
has **no** `tabUser.employee` column. Employee linkage is `Employee.user_id`.

Restricted Petty Management Users hit `permission_query_conditions` → `_user_employee`
→ invalid SELECT. Administrator short-circuits `_petty_user_restricted` and never calls
that path.

## Fix (same release)

1. Resolve employee via `Employee.user_id`, with optional `User.employee` only when the
   column exists.
2. Restricted-user row scope is now:

   - own `employee`, **or**
   - stamped `manager_approver` / `finance_approver` (and `ceo_approver` on PM Request)

   so named Manager / Finance approvers with only **Petty Management User** can open
   assigned documents without elevating them to see all rows.
3. Users with no Employee link and not stamped as approver remain fail-closed (empty list /
   deny form) **without** SQL errors.

## Coverage

- PM Request list/form (restricted holder, named manager, no-employee)
- PM Clearance list/form/ReportView (restricted holder, named manager/finance, elevated roles)
- Playwright Desk: `playwright_pm_request_list_permission.mjs`,
  `playwright_pm_clearance_list_permission.mjs`
