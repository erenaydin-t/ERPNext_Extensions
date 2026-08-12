# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.3.1 — ERPNext 16.32 / Frappe 16.31 upgrade compatibility.

## Why 4.3.1

Compatibility-only release. ERPNext **16.32.0** and Frappe **16.31.0** are
now on the explicit IRR upgrade-guard allow-lists.

No accounting behavior change.

## Compatibility result

Revalidated on live bench (ERPNext 16.32.0 / Frappe 16.31.0):

| Guard target | Signature | Fingerprint vs prior allow-list |
|---|---|---|
| ``update_rate_on_stock_entry`` | unchanged | **identical** |
| ``recalculate_amounts_in_stock_entry`` | unchanged | **identical** |
| ``is_manufacture_entry_with_sabb`` | unchanged | **identical** |
| ``BuyingController.update_valuation_rate`` | unchanged | **identical** to 16.31 primary |
| ``update_regional_item_valuation_rate`` | unchanged | **identical** |
| UVR → regional hook (AST) | still called | **OK** |

Accounting surfaces checked (no conflict with Iran Round Off / Stock
Adjustment / Company Round Off Dimension Defaults):

- ``erpnext.accounts.general_ledger.make_round_off_gle``
- ``erpnext.accounts.general_ledger.update_accounting_dimensions``
- LCV ``update_landed_cost`` still calls ``update_valuation_rate``
- RIV ``_recalculate_valuation_rate`` still calls ``update_valuation_rate``

## What changed

- ``riv_rate_guard``: allow ERPNext ``16.32``, Frappe ``16.31``
- ``uvr_regional_guard``: allow ERPNext ``16.32``, Frappe ``16.31``
- Guard unit tests expect the extended allow-list
- Version bump ``4.3.0`` → ``4.3.1``

Fingerprints were **not** rewritten — bodies match the existing allow-list
entries. Unknown major.minor versions remain **BLOCKED**.

## Frozen (unchanged)

- Class A / Class B residual classification
- Round Off Account / Cost Center / Company Round Off Dimension Defaults
- Stock Adjustment separation
- Manufacture / Repack exclusions
- LCV / RIV / UVR accounting math
- ``align_purchase_receipt_item_amounts`` / qty-rate-amount engines
"""
