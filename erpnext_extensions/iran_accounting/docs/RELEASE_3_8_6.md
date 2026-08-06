# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 3.8.6 — IRR Round Off / Stock Adjustment architecture.

## Why 3.8.6

3.8.4 delivered IRR rate-first amounts and deterministic RIV.
3.8.6 separates Round Off from Stock Adjustment, classifies residuals by
provenance (Class A / Class B), and adds Company-owned Round Off Dimension
Defaults so mandatory operational dimensions (e.g. Department) are not forced
through fake Accounting Dimension defaults.

3.8.4 / 3.8.5 remain unpublished internal notes for this stream; **3.8.6 is the
first publishable package** that includes rate-first plus safe Round Off policy.

## Three Company masters

| Master | Role |
|--------|------|
| `round_off_account` | Proven Class A IRR residuals (+ vanilla ERPNext GL balance) |
| `round_off_cost_center` | Sole CC for custom IRR Round Off GL (never CCA remap) |
| `stock_adjustment_account` | ERPNext inventory valuation (Manufacture/Repack/SR) |

Never use Stock Adjustment as Round Off fallback (missing dims / partner / Class B).

## Class A / Class B

- **Class A:** residual reproduced exactly by approved `iran_accounting` rounding helpers
  for the voucher flow (provenance-first; path-derived bound only after).
- **Class B:** rate≤0 with amount, non-integer rate, amount/rate mismatch, LCV/composition
  drift, etc. Fail closed with diagnostics. Never post to Round Off or invent SA.

## Net Class A gate

If net signed Class A residual == 0 → full Round Off subsystem bypass
(no Account/CC/dimension/partner/GL). Vanilla `make_round_off_gle` untouched.

## Company → Round Off Dimension Defaults

Child table `Round Off Dimension Default`:

- `accounting_dimension` (fieldname)
- `reference_doctype` (read-only)
- `default_value` (Dynamic Link)

No Cost Center / Account rows. No AD `default_dimension` migration.

Resolution order for mandatory dims on Round Off Account:

1. Voucher header (per field)
2. Unique value among Class A residual rows
3. Company Round Off Dimension Defaults
4. Validation error citing Company table

## No safe partner

Fail closed — no silent skip, no Stock Adjustment partner.

## Purchase Receipt

`valuation_rate = 0` + non-zero amount → Class B before Round Off/dims.
Header inherit is per-field (not “all AD fields present”).

## CCA / RIV

CCA excludes residual rows and re-stamps Company Round Off Account/CC.
RIV / RIV×2 use the same `evaluate_irr_rate_rounding_residual` contract.

## Migration

Patch `ensure_company_round_off_dimension_defaults`: schema only, no default rows,
no AD defaults, no historical GL/SLE repair.

## Company validate hook

Frappe does not call child `Document.validate()` when saving a parent Table
field. `company_round_off_defaults.validate_company_round_off_dimension_defaults`
runs child validation on Company save so duplicate / forbidden / invalid defaults
are rejected from Desk.

## Playwright E2E (development.localhost :8001)

Release-blocking specs:

- `round-off-dimension-defaults.spec.ts` — Company child table CRUD + validations
- `purchase-receipt-round-off.spec.ts` — PR Class B / Class A (header, Company default,
  missing default) + RIV×2

Helpers: `iran_accounting/e2e_round_off_ui.py` (test-support only; Class A fixtures
temporarily preserve amount≠qty×rate through submit).

## UAT checklist

- [x] Company Round Off Dimension Defaults grid (Playwright)
- [x] PR Class B clear error (VR=0 shape) (Playwright)
- [x] PR Class A header / Company default / missing (Playwright)
- [ ] Manufacture uses Stock Adjustment, not custom Round Off
- [x] RIV×2 deterministic (Playwright on Class A PR)
- [ ] Trial Balance / Round Off / Stock Adjustment movements reviewed

## Historical repair

**OUT OF SCOPE.**

## Rollback

Revert app to prior version; empty child table is harmless. Do not delete
submitted accounting data.
"""
