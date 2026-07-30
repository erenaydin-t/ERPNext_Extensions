# erpnext_extensions 3.7.6 — Inventory Capitalization Fix

## Root cause

`iran_accounting` treated Stock Entry `amount` as `qty × basic_rate` and forced
single-FG Manufacture `Incoming = Outgoing` / `value_difference = 0`. That wiped
legitimate Additional Cost and Landed Cost Voucher capitalization.

Separately, `StockEntry.get_gl_entries` was fully replaced for IRR companies,
so ERPNext Additional Cost and LCV GL legs never posted.

## Affected versions

- Confirmed defective behavior through **3.7.5** (and earlier builds containing
  the Stock Entry qty×rate + manufacture force-equal + full GL wrapper pattern).

## Corrected ownership model (3.7.6)

| Concern | Owner |
|---|---|
| SE economics (`basic_*`, `additional_cost`, LCV, `amount`, `valuation_rate`, headers) | **ERPNext** (+ IRR residual rounding only) |
| Normal SE GL (inventory from SLE, Additional Cost, LCV) | **ERPNext** `StockEntry.get_gl_entries` |
| Zero-value transfer balanced GL | **iran_accounting** |
| IRR integer / residual absorb | **iran_accounting** |
| Stock Reconciliation qty×rate | **iran_accounting** (unchanged intent) |

## Affected voucher types

- Stock Entry: Manufacture, Repack, Material Receipt/Issue/Transfer/MTfM/Send to Subcontractor
- Landed Cost Voucher targeting Stock Entry (Manufacture/Repack in Desk UI)
- Repost Item Valuation / Repost Accounting Ledger for Stock Entry

Purchase Receipt LCV and Stock Reconciliation were not subject to the SE amount-strip bug.

## Detection strategy (read-only)

Flag submitted IRR Stock Entries where:

1. `Σ(additional_cost) + Σ(landed_cost_voucher_amount) > 1`, and
2. row `amount ≈ basic_amount` (capitalization missing from amount), **or**
3. Manufacture/Repack with `value_difference ≈ 0` despite additional costs, **or**
4. Additional Cost `expense_account` present on the voucher but absent from GL.

## Repair limitations

- **3.7.6 does not automatically mutate historical submitted vouchers.**
- Do **not** run old RIV/RAL alone on corrupted documents **before** upgrading;
  pre-3.7.6 post-repost reconcile re-applied the stripping invariant.
- After deploying 3.7.6, repair candidates via cancel/amend/re-submit, or a
  separately reviewed repair tool that rebuilds SLE/GL through the new path.

## Recommended repair procedure after deployment

1. Deploy **3.7.6** and restart workers (required so `StockEntry.get_gl_entries`
   original is captured correctly).
2. Run detection queries / diagnostics; export affected voucher list.
3. For each voucher: cancel → amend (or recreate) → submit under 3.7.6.
4. Optionally run RIV **after** upgrade; post-repost pipeline is capitalization-aware.
5. Spot-check Manufacture + overhead GL account and Bin valuation.

## Warning

Running repost utilities on affected Stock Entries **before** upgrading can
re-corrupt or lock in undervalued inventory. Upgrade first.

## Known issues

### Stock Reconciliation RIV ±1 IRR GL magnitude (`test_repost_determinism`)

`erpnext_extensions.iran_accounting.tests.test_repost_determinism.test_repost_item_does_not_break_determinism`
can fail after Repost Item Valuation on Opening Stock Reconciliation when
`gl_magnitude` is 1 IRR below `difference_amount` / SLE (example: GL 27535 vs
header/SLE 27536).

- **Scope:** Stock Reconciliation only — not Stock Entry capitalization.
- **Pre-existing:** Reproduced on parent of Commit 1 (`db71ca0`, pre-3.7.6).
  `_reconcile_stock_reconciliation_after_repost` is unchanged in 3.7.6.
- **Not a 3.7.6 regression** for Manufacture / Additional Cost / LCV / transfer GL.
- **Not fixed in this release.** Track separately from inventory capitalization.
