# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.6.5 — Payment Entry DECIMAL(30,9) amount hardening.

## Problem

Saving a Payment Entry with a large Iranian Rial amount such as:

``paid_amount = 1682808518031``

failed with:

``MySQLdb.DataError: (1264, "Out of range value for column 'paid_amount' at row 1")``

This is **not** a single-field defect. Default ``DECIMAL(21,9)`` is too narrow for
every stored monetary amount that can carry Payment Entry values.

## Root cause

Frappe v16 maps Currency/Float to MariaDB ``DECIMAL(21,9)`` by default
(12 integer digits). Large IRR amounts overflow that capacity on parent and
child tables alike.

## Fix

Isolated, allowlisted DECIMAL(30,9) remediation for **all** DB-backed Payment
Entry monetary amount columns through erpnext_extensions:

- pre_model_sync: Property Setter ``length=30``
- post_model_sync: idempotent INFORMATION_SCHEMA inspect + ``ALTER ... MODIFY``
- schema guard: fail clearly if **any** allowlisted column drifts from DECIMAL(30,9)

Does **not**:

- change Frappe global Currency/Float type_map
- modify ERPNext core
- change Payment Entry accounting/posting behavior
- change currency display precision
- widen exchange-rate / tax-rate fields

## Full audit result (previous → resulting)

| Table | Field | DocField type | Previous SQL | Resulting SQL |
|-------|-------|---------------|--------------|---------------|
| tabPayment Entry | paid_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | paid_amount_after_tax | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_paid_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_paid_amount_after_tax | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | received_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | received_amount_after_tax | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_received_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_received_amount_after_tax | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | total_allocated_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_total_allocated_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | unallocated_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | difference_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | total_taxes_and_charges | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry | base_total_taxes_and_charges | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Reference | total_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Reference | outstanding_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Reference | allocated_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Reference | exchange_gain_loss | Currency | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Reference | payment_term_outstanding | Float | decimal(21,9) | decimal(30,9) |
| tabPayment Entry Deduction | amount | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | tax_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | total | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | base_tax_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | base_total | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | net_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabAdvance Taxes and Charges | base_net_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabTax Withholding Entry | taxable_amount | Currency | decimal(21,9) | decimal(30,9) |
| tabTax Withholding Entry | withholding_amount | Currency | decimal(21,9) | decimal(30,9) |

**Total monetary columns hardened: 28**

### Discovered beyond the original ``paid_amount`` failure

All other PE Currency amounts, plus child:

- Payment Entry Reference: ``total_amount``, ``outstanding_amount``, ``allocated_amount``, ``exchange_gain_loss``, ``payment_term_outstanding``
- Payment Entry Deduction: ``amount``
- Advance Taxes and Charges: ``tax_amount``, ``total``, ``base_tax_amount``, ``base_total``, ``net_amount``, ``base_net_amount``
- Tax Withholding Entry: ``taxable_amount``, ``withholding_amount``

No additional PE Currency Custom Fields were present on the development site.

### Explicitly excluded

| Table | Field | Reason |
|-------|-------|--------|
| tabPayment Entry | source_exchange_rate | rate, not amount |
| tabPayment Entry | target_exchange_rate | rate, not amount |
| tabPayment Entry Reference | exchange_rate | rate, not amount |
| tabPayment Entry Reference | payment_request_outstanding | virtual (no DB column) |
| tabAdvance Taxes and Charges | rate | tax rate |
| tabTax Withholding Entry | tax_rate / conversion_rate | rates |

## Patches

- ``erpnext_extensions.patches.pre_model_sync.set_payment_entry_amount_decimal_metadata``
- ``erpnext_extensions.patches.post_model_sync.expand_payment_entry_amount_precision``

Helper: ``erpnext_extensions.payment_entry_decimal_precision``

## Regression coverage

- Unit allowlist / decision matrix / Property Setter idempotency / rate exclusions
- Schema sync + ``updatedb`` survival + full-set schema guard
- Completeness: every non-virtual Currency field on audited DocTypes is allowlisted
- Draft Payment Entry round-trip for ``1682808518031`` across **all** PE amount fields
- Child ``allocated_amount`` / deduction / tax / withholding amounts
- Fractional round-trip ``1682808518031.123456789`` via CAST AS CHAR

## Version

``4.6.4`` → ``4.6.5``
"""
