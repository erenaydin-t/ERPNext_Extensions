# Petty Management 4.1.3 — List permissions + single unrestricted operator role

## Summary

1. Fixed restricted-user list crash (`User.employee` missing column).
2. Named approvers can open stamped docs without elevated roles.
3. **Single operational unrestricted visibility role:** `Petty Management Accountant`.

## Visibility model

| Actor | PM Request / Clearance visibility |
|--|--|
| Administrator / System Manager | Unrestricted |
| **Petty Management Accountant** | Unrestricted (operational operator) |
| Petty Management User (holder) | Own employee only |
| Named manager / CEO / finance approver | Stamped docs only |
| Petty Management Manager / Admin / Auditor (alone) | Scoped (not global) |
| No Employee + not stamped | Fail-closed empty list |

Visibility bypass does **not** bypass Workflow transition conditions or DocPerm.

## Role rationalization

- **Accountant** — day-to-day finance/petty operator; finance workflow transitions; global PM visibility.
- **Manager** — workflow manager/CEO approve transitions only; visibility via stamps / own employee.
- **User** — holders; submit + own docs.
- **Admin** — DocPerm cancel/settings; not a visibility bypass (pair with Accountant if support needs all docs).
- **Auditor** — DocPerm read; not a visibility bypass (pair with Accountant for full audit visibility).

## Tests / E2E

- `test_pm_visibility_roles`, list permission modules
- Playwright request + clearance list (holder, manager, finance, accountant, admin)
