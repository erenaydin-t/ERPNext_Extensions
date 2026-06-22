# Iran Accounting — Playwright E2E (Scenario 21 MTfM)

Release-blocking Desk UI test for **Material Transfer for Manufacture** zero-value transfer GL behavior (Scenario 21).

## Prerequisites

- Frappe bench with `erpnext_extensions` installed and `iran_accounting` patches active
- Site reachable from the test runner (default `http://development.localhost:8000`)
- Node.js 18+ and npm
- Chromium system deps on Linux/WSL:

```bash
npx playwright install-deps chromium
npm run install:browsers
```

## Setup

```bash
cd erpnext_extensions/iran_accounting/e2e/playwright
cp .env.example .env
# Edit .env for base URL, credentials, company, optional E2E_MTFM_STOCK_ENTRY

npm install
npm run install:browsers
```

## Environment variables

| Variable | Description |
|----------|-------------|
| `FRAPPE_E2E_BASE_URL` | Desk URL (no trailing slash) |
| `FRAPPE_E2E_USER` / `FRAPPE_E2E_PASSWORD` | Login |
| `FRAPPE_E2E_COMPANY` | IRR company (default `ESPAD`) |
| `E2E_MTFM_STOCK_ENTRY` | Optional fixed Stock Entry name |
| `FRAPPE_BENCH_ROOT` | Bench path for `bench execute` GL validation |
| `FRAPPE_SITE` | Site name for bench |

If `E2E_MTFM_STOCK_ENTRY` is empty, the test calls  
`erpnext_extensions.iran_accounting.e2e_playwright.resolve_mtfm_stock_entry` to find or create a **draft** MTfM.

## Run tests

```bash
# Full suite (Scenario 21)
npm test

# Single spec
npm run test:scenario21

# Headed (debug)
npm run test:headed

# HTML report
npm run report
```

Report output: `playwright-report/index.html`  
Step screenshots: `test-results/screenshots/`

## What PASS means

1. Login succeeds  
2. Stock Entry opens with purpose **Material Transfer for Manufacture**  
3. Source and target/WIP warehouses exist and differ  
4. **Preview → Accounting Ledger** dialog loads (draft only)  
5. Preview: debit total = credit total = document incoming value  
6. WIP debited, Stock In Hand credited; no Stock Adjustment / Round Off  
7. Document submits (if draft) and shows **Submitted**  
8. Backend SQL validation: `validate_stock_entry_gl_sql` returns **PASS** (no doubled GL)

## Project layout

```
playwright/
  playwright.config.ts
  tests/scenario21.spec.ts
  src/
    fixtures/erpnext.fixture.ts
    pages/login.page.ts
    pages/stock-entry.page.ts
    pages/accounting-ledger-preview.dialog.ts
    utils/env.ts
    utils/frappe-api.ts
    utils/screenshots.ts
```

Backend helpers: `erpnext_extensions/iran_accounting/e2e_playwright.py`

## CI suggestion

```bash
cd erpnext_extensions/iran_accounting/e2e/playwright
npm ci
npx playwright install --with-deps chromium
npm run test:scenario21
```

Fail the pipeline if the spec fails or `playwright-report` shows failures.

## Troubleshooting

- **Preview button missing**: Document must be **Draft** (`docstatus=0`). Set `E2E_MTFM_STOCK_ENTRY` to a draft MTfM or let the resolver create one.  
- **bench execute fails**: Set `FRAPPE_BENCH_ROOT` and `FRAPPE_SITE` correctly.  
- **Login timeout**: Confirm site URL and that Administrator can log in manually.
