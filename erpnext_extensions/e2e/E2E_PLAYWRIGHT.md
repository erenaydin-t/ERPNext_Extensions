# Playwright E2E — database-first architecture

## Standard

1. User action (UI or `frappe.call` in browser).
2. Wait for server commit — poll **`e2e_playwright_db.mjs`** helpers against MariaDB via `bench execute`.
3. **Assert database** (`workflow_state`, `docstatus`, `exists`, domain-specific SQL helpers).
4. Optionally assert UI matches DB (secondary).

## Shared modules

| Module | Role |
|--------|------|
| `e2e_document_state.py` | `e2e_get_document_state`, `e2e_document_exists`, `e2e_wait_document_state`, `e2e_wait_workflow_state`, `e2e_wait_docstatus` |
| `e2e_playwright_db.mjs` | `benchExecute`, `getDocumentState`, `waitDocumentState`, `waitDocumentAbsent`, `assertDbState`, `buildFailureDebug` |

Import from Playwright:

```javascript
import {
  benchExecute,
  getDocumentState,
  waitDocumentState,
  assertDbState,
  buildFailureDebug,
} from "../../e2e/e2e_playwright_db.mjs";
```

## Failure debug

Use `buildFailureDebug()` — includes document name, workflow/docstatus before/after, DB row, UI snapshot, server response, elapsed wait, timestamp.

## Run all suites

```bash
node erpnext_extensions/e2e/run_all_playwright.mjs              # default: all serial (stable)
node erpnext_extensions/e2e/run_all_playwright.mjs --parallel   # FAST/UI_ONLY in parallel, then SERIAL
node erpnext_extensions/e2e/run_all_playwright.mjs --grep pdc_workflow --retries 1
```

Suite tags live in `playwright_suites.mjs`. Unique IDs: `e2e/e2e_unique.py`, fixtures: `e2e/e2e_fixture.py`.

Playwright is resolved from `/tmp/e2e-npm/node_modules/playwright` (all `playwright*.mjs` use this path).

## UI-primary suites

List filter / dimension link / JE preview scripts may remain **UI-primary** when the assertion is purely client-side (filters, layout). Workflow and accounting outcomes must use DB-first pattern.
