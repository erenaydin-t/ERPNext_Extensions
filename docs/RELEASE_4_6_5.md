# Copyright (c) 2026, ERPNext Extensions contributors
"""RELEASE 4.6.5 — Payment Entry DECIMAL(30,9) amount hardening.

## Problem

Saving a Payment Entry with a large Iranian Rial amount such as:

``paid_amount = 1682808518031``

failed with:

``MySQLdb.DataError: (1264, "Out of range value for column 'paid_amount' at row 1")``

## Root cause

Frappe v16 maps Currency/Float to MariaDB ``DECIMAL(21,9)`` by default.
That leaves only 12 integer digits. Large IRR Payment Entry amounts exceed
this capacity.

## Fix

Isolated, allowlisted DECIMAL(30,9) remediation for Payment Entry monetary
columns and related child-table monetary columns through erpnext_extensions:

- pre_model_sync: Property Setter ``length=30``
- post_model_sync: idempotent INFORMATION_SCHEMA inspect + ``ALTER ... MODIFY``
- schema guard: fail clearly if any allowlisted column drifts from DECIMAL(30,9)

Does **not**:

- change Frappe global Currency/Float type_map
- modify ERPNext core
- change Payment Entry accounting/posting behavior
- change currency display precision

## Audited DocTypes / columns

### Payment Entry (14)

paid_amount, paid_amount_after_tax, base_paid_amount, base_paid_amount_after_tax,
received_amount, received_amount_after_tax, base_received_amount,
base_received_amount_after_tax, total_allocated_amount, base_total_allocated_amount,
unallocated_amount, difference_amount, total_taxes_and_charges,
base_total_taxes_and_charges

### Payment Entry Reference (5)

total_amount, outstanding_amount, allocated_amount, exchange_gain_loss,
payment_term_outstanding

Virtual field ``payment_request_outstanding`` has no DB column and is excluded.

### Payment Entry Deduction (1)

amount

### Advance Taxes and Charges (6)

tax_amount, total, base_tax_amount, base_total, net_amount, base_net_amount

### Tax Withholding Entry (2)

taxable_amount, withholding_amount

### Explicitly excluded (non-monetary rates)

Payment Entry ``source_exchange_rate`` / ``target_exchange_rate``,
Payment Entry Reference ``exchange_rate``, Advance Taxes ``rate``,
Tax Withholding ``tax_rate`` / ``conversion_rate``.

## Patches

- ``erpnext_extensions.patches.pre_model_sync.set_payment_entry_amount_decimal_metadata``
- ``erpnext_extensions.patches.post_model_sync.expand_payment_entry_amount_precision``

## Regression coverage

- Unit allowlist / decision matrix / Property Setter idempotency
- Schema sync + ``updatedb`` survival + schema guard
- Draft Payment Entry round-trip for ``1682808518031``
- Fractional round-trip ``1682808518031.123456789``
- Child ``allocated_amount`` above DECIMAL(21,9) range

## Version

``4.6.4`` → ``4.6.5``
"""
