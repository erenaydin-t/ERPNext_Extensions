# Petty Management 4.1.3 — Fix PM Request list for restricted users

## Summary

PM Request List View failed for normal Petty Management users with:

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

The ReportView fields `holder.employee_name as …` / `employee.employee_name as …` are
standard Frappe Link title enrichment; they were present in the failing request but were
not the source of the 1054 error.

## Fix

Resolve employee via `Employee.user_id`, with optional `User.employee` only when the
column exists. Preserve employee-scoped row filters for restricted users.

## Tests

- Unit/integration: `test_pm_request_list_permission`
- Playwright: `playwright_pm_request_list_permission.mjs` (non-Administrator Desk list)
