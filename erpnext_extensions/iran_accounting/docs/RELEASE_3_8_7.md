# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 3.8.7 — CRITICAL HOTFIX: Purchase Receipt valuation + UVR IRR pipeline.

## Why 3.8.7

1. **Classifier auth (3.8.6 false Class B):** PR Class A/B used ``base_amount`` /
   ``amount`` ÷ qty. ERPNext stock auth is
   ``base_net_amount + item_tax_amount + landed_cost_voucher_amount + …`` over
   stock-UOM qty. Inclusive VAT / Valuation tax / LCV / conversion_factor were
   falsely Class B.

2. **UVR pipeline consistency:** IRR integerization lived only on
   ``Purchase Receipt.validate``. Landed Cost Voucher calls
   ``update_valuation_rate`` then ``db_update`` without validate, so fractional
   VR reached the classifier (``non_integer_rate_under_irr_contract``).

## Architecture

ERPNext ``BuyingController.update_valuation_rate`` ends with
``update_regional_item_valuation_rate(doc)``. Iran binds that extension point to
existing ``align_purchase_receipt_item_amounts`` (idempotent ROUND_HALF_UP).

One pipeline for PR / Purchase Return / LCV / RIV recalculation / PI update-stock:

```
update_valuation_rate()
  → update_regional_item_valuation_rate()  # IRR align
  → persist / SLE / classifier / GL
```

Classifier still mirrors ERPNext stock numerator (no tax re-derivation).

## Frozen (unchanged)

- Stock Entry / Manufacture / Repack / Material Transfer / Additional Cost
- Round Off Account / CC / Company Round Off Dimension Defaults
- Stock Adjustment / Class A·B rules (fail-closed)

## Historical repair

**OUT OF SCOPE.**

## Rollback

Revert to 3.8.6. No schema migration required for this hotfix.
"""
