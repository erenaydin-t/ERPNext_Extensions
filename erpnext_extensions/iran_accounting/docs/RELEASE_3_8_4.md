# ERPNext Extensions 3.8.4 — IRR Rate-First Accounting Release

## 1. Executive Summary

Version **3.8.4** freezes the approved **NEW-document** IRR accounting contract for
Stock Entry and related stock vouchers:

- Rate-first integer rounding for IRR
- Stock Entry Detail as the sole economic source of truth
- Deterministic Repost Item Valuation (RIV) that does not rewrite approved IRR rates
- Guarded ERPNext monkey patch with fail-closed Upgrade Guard
- Manufacture/Repack valuation gaps → Company Stock Adjustment (not Round Off)
- Additional Cost and Landed Cost Voucher (LCV) capitalization preserved
- Full unit, integration, UI, stress, report, and golden validation

**Historical repair is intentionally out of scope.**

## 2. Problem Statement

On IRR companies, ERPNext Moving Average / FIFO rebuild during RIV could overwrite
submitted Stock Entry `basic_rate` with a derived `outgoing_rate` from stock-value
residuals. That broke the integer rate×qty contract and produced silent amount drift
(example: submit `70154` / `210462` → after RIV `70147` / `210441`).

Separately, Manufacture/Repack integer-rate value differences must follow ERPNext
Stock Adjustment semantics and must not be absorbed into Round Off.

## 3. Root Cause Analysis

Call path:

`repost` → `repost_future_sle` → `process_sle` → `update_outgoing_rate_on_transaction`
→ `update_entries_after.update_rate_on_stock_entry`

Vanilla ERPNext does:

```python
frappe.db.set_value("Stock Entry Detail", sle.voucher_detail_no, "basic_rate", outgoing_rate)
```

where `outgoing_rate` is rebuilt from warehouse stock value ÷ qty (MA/FIFO), which is
not guaranteed to equal the submitted integer IRR rate.

Iran post-hooks that only re-rounded the already-wrong rate could not restore the
approved economics.

## 4. Accounting Contract

For company currency **IRR**, on **NEW** documents:

```
basic_rate      = ROUND_HALF_UP(raw_rate, 0)
basic_amount    = ROUND_HALF_UP(transfer_qty × basic_rate, 0)
amount          = ROUND_HALF_UP(basic_amount + additional_cost + landed_cost_voucher_amount, 0)
valuation_rate  = ROUND_HALF_UP(amount / transfer_qty, 0)
```

- **Amount** remains authoritative for inventory/SLE projection.
- Micro-residual `amount − valuation_rate × qty` may be ±1 on some shapes; never force
  `amount := valuation_rate × qty`.

### Mandatory Fixture A

```
qty = 1245
raw_rate = 2207006.162248996
basic_rate = 2207006
basic_amount = 2747722470
amount = 2747722470
```

After RIV ×1 and ×2: **no change**.

### Mandatory Fixture B

```
qty = 3
raw MA ≈ 70153.649…
basic_rate = 70154
amount = 210462
```

After RIV ×1 and ×2: **no rewrite** to `70147` / `210441`.

## 5. IRR Rate-First Design

- Single calculation engine: `align_stock_entry_item_amounts`
- No duplicated ROUND / qty×rate / Add Cost / LCV composition in the RIV wrapper
- Wrapper skips **only** `basic_rate ← outgoing_rate` on IRR; keeps vanilla recalculate gate
- After recalculate: re-apply align (+ Manufacture FG residual helper) and persist SE rows/header

## 6. Stock Entry Source of Truth

| Layer | Role |
|---|---|
| Stock Entry Detail | Accounting source of truth (`basic_rate`, `basic_amount`, `amount`, `valuation_rate`) |
| SLE | Projection of finalized SE economics |
| GL | Projection of finalized SE / inventory movements |
| Bin | Projection of SLE closing qty/value |

No business logic may direct-SQL rewrite submitted SE/SLE/GL/Bin for this contract.

## 7. RIV Preservation

- Monkey patch wraps `erpnext.stock.stock_ledger.update_entries_after.update_rate_on_stock_entry`
- Non-IRR → untouched original
- IRR → refuse MA overwrite; require preserved detail `basic_rate`; recalculate when gate matches vanilla
- Idempotent install; original reference saved and callable
- Post-repost pipeline remains available for reconcile without rewriting rates

## 8. Upgrade Guard

Fail-closed before install:

- Explicit ERPNext / Frappe major.minor allow-list (`16.29`, `16.30`)
- Signature match for target + companion helpers
- Normalized AST/source SHA-256 fingerprints
- Structural source token assertions
- Unknown version / fingerprint mismatch → **block** (clear remediation message; no silent fallback; no partial install)

## 9. ERPNext Compatibility

Validated stack for this release:

| Component | Version |
|---|---|
| ERPNext | 16.30.x (allow-list 16.29 / 16.30) |
| Frappe | 16.29.x (allow-list 16.29 / 16.30) |
| App | erpnext_extensions **3.8.4** |

Re-fingerprint before enabling on any new ERPNext build.

## 10. Golden Dataset

Mandatory golden / fixture coverage includes:

- Fixture A (large qty × fractional raw rate)
- Fixture B (MA residual MT defect)
- Manufacture + Additional Cost
- LCV field preservation
- MTfM / Issue / Repack RIV×2
- Final audit artifact (`test_final_audit_383`)

## 11. Stress Results

Local release gate `gate_release_383_local.run_gate(full_stress=1)` on restore site:

| Category | Count | Result |
|---|---|---|
| Material Transfer | 50 | PASS |
| Material Issue | 50 | PASS |
| MTfM | 30 | PASS |
| Manufacture | 30 | PASS |
| Stock Reconciliation | 20 | PASS |
| Material Receipt | 50 | PASS |

Representative duration ~80–90s serial on restore-espad (environment-dependent).

Hardening stress (50 receipts, 20 manufactures, SR, LCV + sampled RIV) PASS.

## 12. UI Validation

Playwright against local Desk (site-locked restore serve):

- Integer Basic Rate / Amount display
- Fixture A/B Desk ↔ API ↔ DB parity
- Manufacture no Round Off residual remarks
- Stock Ledger / General Ledger report execution
- Repost Item Valuation list opens
- `irr-rate-fields` release-blocking smoke

## 13. Database Validation

For test-scope vouchers:

- All IRR `basic_rate` integers
- `basic_amount` / `amount` contracts
- Balanced GL; no duplicate active SLE/GL
- No unexpected Round Off residual on Manufacture/Repack
- Fixture A/B exact persisted values

Company-wide restored backup history is **not** asserted clean.

## 14. Report Validation

Executed with numeric assertions (not smoke-only):

- Stock Ledger
- Stock Balance
- General Ledger
- Trial Balance (with fiscal year)
- Balance Sheet inventory where applicable

Inventory GL movement reconciles to SLE for fixture vouchers; Stock Adjustment /
Round Off policies as documented in §4.

## 15. Known Limitations

- **Repost Accounting Ledger (RAL):** Stock Entry may be blocked by ERPNext Accounts
  Settings “Allowed Doctype” / `Repost Allowed Types`. Classified as environment
  constraint; do not widen allowed_types solely to force a pass.
- **Multi-site HTTP:** `bench serve` may lock `_site` to `default_site`. Use
  site-locked serve (`bench --site <site> serve --port …`) for Desk E2E.
- **MariaDB `tabSeries`:** Concurrent naming can raise `1020` under parallel load;
  serial gate runs are authoritative.
- Gate stress module focuses on SE MR/MI/MT/MTfM/MFG/SR volumes; Repack/LCV covered
  in integration + hardening suites.

## 16. Historical Repair

**EXPLICITLY OUT OF SCOPE for 3.8.4.**

Do not RIV/repair legacy production vouchers as part of this release. Historical
cleanup is a separate Phase 2 project.

## 17. Upgrade Procedure

1. Deploy `erpnext_extensions` **3.8.4** to a local/staging site first.
2. Confirm ERPNext/Frappe on allow-list; Upgrade Guard must install cleanly.
3. `bench migrate` · `bench clear-cache` · `bench build --app erpnext_extensions`
4. Restart workers/web as required.
5. Smoke: create NEW Material Transfer with fractional raw rate; submit; confirm
   integer rates; run RIV ×2; confirm no drift.
6. Only then schedule production deploy of **NEW-document** behavior.

## 18. Rollback Procedure

1. Revert app to previous tagged/approved commit (or reinstall prior wheel).
2. `bench migrate` / clear-cache / restart as needed.
3. Confirm monkey patch / Upgrade Guard no longer active (or prior version active).
4. Do **not** mass-repost historical vouchers as part of rollback.

## 19. Compatibility Matrix

| Item | Supported |
|---|---|
| Frappe | 16.29, 16.30 (major.minor allow-list) |
| ERPNext | 16.29, 16.30 (major.minor allow-list) |
| Company currency | IRR (rate-first path); non-IRR passthrough vanilla |
| Perpetual inventory | Required for GL assertions |
| Historical voucher repair | Not supported in this release |

## 20. Test Coverage Summary

| Suite | Status |
|---|---|
| `test_riv_rate_first_preserve` (guard + fixtures) | Required |
| `test_irr_rounding_residual` | Required |
| `test_final_audit_383` | Required |
| `test_production_hardening_376` | Required (RAL may skip) |
| `test_material_transfer_same_stock_account` | Required |
| `gate_release_383_local` full_stress=1 | Required local gate |
| Playwright `irr-rate-fields` / final audit UI | Required local E2E |

## Related historical note

Prior draft: [RELEASE_3_8_3.md](./RELEASE_3_8_3.md) (superseded).
