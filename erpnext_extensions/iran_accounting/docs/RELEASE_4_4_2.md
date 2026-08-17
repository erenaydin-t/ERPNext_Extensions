# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.4.2 — Purchase Receipt IRR residual eligibility for non-stock rows.

## Fixed

- False Class B ``valuation_rate_le_zero_with_nonzero_amount`` on non-stock /
  non-asset Purchase Receipt rows (including Subcontracting Receipt auto-created
  service Purchase Receipts where ERPNext intentionally sets ``valuation_rate = 0``).
- Purchase Receipt residual classification now follows ERPNext stock/asset
  valuation eligibility (``get_stock_items()`` + ``get_asset_items()``, mirroring
  ``BuyingController.update_valuation_rate``).
- Both ``classify_document_residuals`` and the legacy
  ``collect_purchase_receipt_residuals`` collector share the same row-level gate.

## Unchanged

- No accounting policy change
- Stock-valued Purchase Receipt Class A / Class B mathematics and fail-closed
  behavior remain unchanged
- Subcontracting Receipt finished-good valuation remains ERPNext-native
- Round Off Account / Cost Center / Stock Adjustment architecture unchanged
- No schema change
- No historical repair / no submitted-data rewrite

## Version

``4.4.0`` → ``4.4.2``
"""
