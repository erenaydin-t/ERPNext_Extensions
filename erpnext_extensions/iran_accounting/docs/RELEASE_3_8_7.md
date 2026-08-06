# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 3.8.7 — CRITICAL HOTFIX: Purchase Receipt valuation pipeline.

## Why 3.8.7

3.8.6 Class A/B classification for Purchase Receipt used
``base_amount`` / ``amount`` and purchase ``qty`` as if
``valuation_rate == amount / qty``.

That identity is **not** ERPNext's stock contract. Valid Purchase Receipts with
inclusive VAT, Valuation-category taxes, landed cost on the row, or
``conversion_factor != 1`` were rejected as Class B
(``amount_rate_mismatch_not_reproducible_by_approved_pipeline``).

## Root cause

ERPNext computes Purchase Receipt ``valuation_rate`` in
``BuyingController.update_valuation_rate`` as:

```
(base_net_amount [or internal-transfer net]
 + item_tax_amount
 + landed_cost_voucher_amount
 + amount_difference_with_purchase_invoice
 [+ rm_supp_cost on old subcontract flow])
 / (qty * conversion_factor)
```

SLE ``incoming_rate`` is set from ``valuation_rate``. SRBNB credits
``base_net_amount``. Gross ``amount`` / ``base_amount`` are commercial fields and
may diverge when tax is included in print rate.

ERPNext exposes **no reusable public helper** for that stock numerator; the sum
is inlined in ``update_valuation_rate``. Iran Accounting therefore mirrors the
numerator and stock-UOM qty from fields ERPNext already wrote on the item row
(``purchase_receipt_stock_valuation_amount`` /
``purchase_receipt_valuation_stock_qty``). Taxes are **not** re-derived.

## What changed

- Purchase Receipt residual classification only
- Authoritative amount = ERPNext stock valuation numerator
- Qty = ERPNext stock-UOM qty (``qty * conversion_factor``, rejected fallback)
- Class B still fails closed for VR≤0, non-integer IRR rates, and true
  auth↔VR inconsistency

## Frozen (unchanged)

- Stock Entry (all purposes), Manufacture, Repack, Material Transfer / MTfM
- Stock Reconciliation, Additional Cost, RIV
- Round Off Account / Cost Center / Company Round Off Dimension Defaults
- Stock Adjustment architecture

## Tests

- Unit: ``test_irr_residual_classification`` (incl. inclusive VAT, Valuation tax,
  LCV, conversion_factor, true Class B retained)
- Playwright release-blocking: ``purchase-receipt-round-off.spec.ts``,
  ``round-off-dimension-defaults.spec.ts``
- Live: excluded/included VAT, Valuation and Total, LCV, conversion_factor,
  Purchase Return draft, SE purpose residual smoke
- Espad: 30 submitted PRs clean; ``MAT-PRE-2026-01083`` still Class B (VR=0)

## Historical repair

**OUT OF SCOPE.**

## Rollback

Revert to 3.8.6. No schema migration required for this hotfix.
"""
