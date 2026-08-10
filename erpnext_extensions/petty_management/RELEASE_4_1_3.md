# Petty Management 4.1.3 — List permissions + configurable unrestricted operator role

## Summary

1. Fixed restricted-user list crash (`User.employee` missing column).
2. Named approvers can open stamped docs without elevated roles.
3. **Configurable operational unrestricted visibility role** via PM Settings
   (`Operational PM Visibility Role`), default **Petty Management Accountant**.
4. **PM Request funding UX:** after finance approval, Desk shows a clear business/funding
   status (Waiting for Payment / Partially Paid / Paid — Fully Funded / Closed) via the form
   dashboard headline + intro. The Frappe workflow remains approval-only and intentionally
   stays at **Waiting for Payment** after finance approval; payment lifecycle is represented
   by PM business/payment status — not a workflow change.
5. **Close PM Request** now synchronizes `status=Closed` immediately when `is_closed=1`
   (no extra funding sync required).

## Visibility model

| Actor | PM Request / Clearance visibility |
|--|--|
| Administrator / System Manager | Unrestricted |
| Role in PM Settings → Operational PM Visibility Role | Unrestricted (default: Accountant) |
| Petty Management User (holder) | Own employee only |
| Named manager / CEO / finance approver | Stamped docs only |
| Other PM roles without configured role / stamp / employee | Scoped / fail-closed |

Visibility bypass does **not** bypass Workflow transition conditions or DocPerm.

Empty PM Settings value falls back to `Petty Management Accountant`.

## Role rationalization (defaults)

- **Accountant** — default operational visibility role; finance workflow transitions.
- **Manager** — workflow manager/CEO approve; visibility via stamps unless configured as ops role.
- **User** — holders; submit + own docs.
- **Admin** / **Auditor** — DocPerm / settings / read; not automatic visibility bypass.

## Tests / E2E

- `test_pm_visibility_roles`, `test_pm_visibility_role_setting`, list permission modules
- `test_pm_request_funding_status_ux` (full / multi-PE / cancel / close sync)
- Playwright: request + clearance list; `playwright_pm_visibility_role_setting.mjs`;
  `playwright_pm_request_funding_status_ux.mjs`
