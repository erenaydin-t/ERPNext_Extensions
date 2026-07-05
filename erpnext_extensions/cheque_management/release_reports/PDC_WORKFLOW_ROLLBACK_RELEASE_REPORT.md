# PDC Workflow Rollback — Release Report

**Date:** 2026-07-04  
**Verdict:** **NOT production-ready** until Playwright A–K and manual UAT are green on your target site (see checklist below).

---

## 1. Architecture

| Layer | Responsibility |
|--------|----------------|
| `PDC Journal Reference` + transition keys | **Source of truth** for which JEs to cancel |
| `accounting_rollback/pdc/plan.py` | BFS path → ordered `RollbackTransitionStep` list |
| `accounting_rollback/engine.py` | Newest-first handlers; `dry_run` = enrich only |
| `accounting_rollback/transitions.py` | `PDCTransition` / JE vs operational handlers |
| `accounting_rollback/erpnext_accounting.py` | `Journal Entry.cancel()`, `update_voucher_outstanding()` |
| `pdc_workflow_rollback.py` | Whitelisted API, SQL verify helpers, immutability validation |
| `pdc_workflow_rollback_permission.py` | **Policy:** PDC Settings → `workflow_rollback_allowed_roles` |
| Audit | Insert-only `PDC Workflow Rollback Log` rows + Workflow timeline comment |

Preview and execute share `_run_pdc_rollback_plan(..., dry_run=…)`.

---

## 2. Tests (automated)

| Gate | Result | Command / notes |
|------|--------|-----------------|
| Unit (path, permission, preview guards) | **PASS** (31) | `bench --site <site> run-tests --app erpnext_extensions --module erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback` |
| Payable integration lifecycle | **PASS** | `bench --site <site> execute erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback_lifecycle_integration.run_payable_lifecycle_integration` |
| Receivable integration lifecycle | **PASS** | `…run_receivable_lifecycle_integration` |
| SQL evidence export (dedicated run) | **BLOCKED in shared dev DB** | `run_integration_sql_evidence` may hit Account nested-set lock if bench serve / parallel tests run; run alone on quiet DB |
| Playwright A–K | **FAIL (this environment)** | Login timeout at `http://127.0.0.1:8000/login` — use site URL + `Host` / `development.localhost` and ensure `bench serve` + `prepare_pdc_workflow_rollback_e2e` |

---

## 3. Browser E2E (Playwright A–K)

Script: `cheque_management/e2e/playwright_pdc_workflow_rollback.mjs`

| ID | Scenario | Expected |
|----|-----------|----------|
| A | Registered → Draft | Button, rollback, SQL clean |
| B | Issued → Registered | State + SQL |
| C/D | Cleared → … → Draft | Multi-step + SQL each step |
| E | Returned → Issued | |
| F | Cancelled → Issued | |
| G | Permission | No button + server reject for non-privileged user |
| H | Preview | Workflow + Accounting sections in HTML |
| I | History grid | ≥3 rollback log rows after C/D |
| J | Double rollback | Second call rejected |
| K | Forward after rollback | Register from Draft |

**Run (when site is up):**

```bash
cd /tmp/e2e-npm && npx playwright install chromium
export PLAYWRIGHT_BROWSERS_PATH=$HOME/.cache/ms-playwright
export FRAPPE_E2E_BASE_URL=http://development.localhost:8000   # or your desk URL
cd apps/erpnext_extensions/erpnext_extensions/cheque_management/e2e
node playwright_pdc_workflow_rollback.mjs
```

Screenshots: `e2e/screenshots/pdc_workflow_rollback/*.png`

---

## 4. SQL verification evidence

**Per rollback step**, `accounting_snapshot_for_pdc()` captures:

- Post Dated Cheque (workflow, docstatus, leaf)
- Journal Entry (+ docstatus)
- Journal Entry Account (count)
- GL Entry (count, active)
- Payment Ledger Entry (count, active)
- PDC Journal Reference (rows)
- Outstanding (from PDC Allocation → invoice outstanding)
- Cheque Leaf
- Rollback log count + workflow comment count

**Generate (quiet DB, no concurrent account creation):**

```bash
bench --site development.localhost console
>>> from erpnext_extensions.cheque_management.tests.test_pdc_workflow_rollback_lifecycle_integration import run_integration_sql_evidence
>>> import json; from pathlib import Path
>>> data = run_integration_sql_evidence()
>>> Path(frappe.get_app_path("erpnext_extensions"))/"cheque_management/release_reports/pdc_workflow_rollback_sql_evidence.json"
>>> # write json.dumps(data, indent=2, default=str)
```

Integration tests already assert JE docstatus=2, zero orphan GL/PLE, journal refs, leaf, rollback log fields after each step.

---

## 5. Manual UAT checklist

Perform on **Administrator** (or a user with a role listed in **PDC Settings → Roles Allowed to Rollback Workflow**):

- [ ] Open submitted PDC → **Rollback Workflow State** visible only when policy allows
- [ ] Change target → **Preview** shows Workflow, Cheque Leaf, Accounting (GL/PLE/outstanding)
- [ ] Confirm rollback → workflow + cheque status + outstanding refresh
- [ ] **Timeline** → Workflow comment with reason
- [ ] **Workflow Rollback Logs** → one row per undone edge (transition_key, JE, user, time); rows **not** editable on normal save
- [ ] Second rollback on same doc → **appends** new log rows (does not rewrite old)
- [ ] Multi-step rollback (Cleared → Draft)
- [ ] **Register Cheque** after rollback to Draft (scenario K)
- [ ] Non-privileged user: no button; API returns permission error (G)
- [ ] Hard refresh / new session: state and outstanding still correct

---

## 6. Screenshots

Captured automatically when Playwright passes:

`erpnext_extensions/cheque_management/e2e/screenshots/pdc_workflow_rollback/`

Manual UAT: attach desk screenshots for Preview, Timeline, History, outstanding on invoice.

---

## 7. Release gates implemented in code (this sprint)

1. **Policy-based permission** — `PDC Settings.workflow_rollback_allowed_roles` (default `System Manager`); `check_user_may_rollback_pdc_workflow` for desk button.
2. **Immutable audit** — insert-only log rows via `_append_rollback_audit_row`; child DocType blocks edit/delete; `validate_workflow_rollback_logs_immutable` on PDC save.
3. **Enriched preview** — `business_impact`, workflow/leaf sections in JS; step `impact` (GL/PLE/outstanding).
4. **SQL helpers** — `pdc_rollback_sql_evidence.py`, `run_integration_sql_evidence`, E2E `e2e_sql_verify_pdc` includes `snapshot`.

**Migrate required:** `bench --site <site> migrate` (PDC Settings field + rollback log columns).

---

## 8. Regression summary

- Rollback engine refactor retained integration behavior (payable + receivable lifecycles green).
- Permission unit tests updated for policy module (Administrator still allowed via policy helper).
- E2E prep `bench execute` must use unquoted method path (no quotes around `erpnext_extensions…`).

---

## 9. Release checklist

| # | Gate | Status |
|---|------|--------|
| 1 | Playwright A–K | **RED** (env login / URL — re-run locally) |
| 2 | SQL before/after JSON | **AMBER** (harness ready; generate on quiet DB) |
| 3 | Manual UAT + screenshots | **PENDING** (operator) |
| 4 | Preview business impact | **GREEN** (code) |
| 5 | Policy permission | **GREEN** (code + migrate) |
| 6 | Immutable audit | **GREEN** (code) |
| 7 | Integration lifecycles | **GREEN** |
| 8 | Unit tests | **GREEN** |

---

## 10. Suggested commit message

```
feat(cheque): PDC workflow rollback release gates — policy, audit, preview, SQL evidence

Add PDC Settings rollback roles, immutable rollback log rows, enriched dry-run preview,
and SQL snapshot helpers; keep transition-based rollback engine and integration parity.
```

---

## Production-ready when

All checklist rows are **GREEN**, Playwright `all_ok: true`, SQL evidence file committed or attached to release, and manual UAT signed off.
