# IRR rate-first rounding contract (version 3.8.3)

## Scope

**NEW submitted documents only.** Historical repair is a separate Phase 2 project.

Code + tests for the forward contract. No historical production repair. No production repost of legacy vouchers in this release.

## Contract (NEW documents)

For company currency IRR:

1. `basic_rate = ROUND_HALF_UP(raw_rate, 0)`
2. `basic_amount = ROUND_HALF_UP(transfer_qty × basic_rate, 0)` — never `qty × fractional rate`
3. `amount = ROUND_HALF_UP(basic_amount + additional_cost + LCV, 0)`
4. `valuation_rate = ROUND_HALF_UP(amount / transfer_qty, 0)`
5. Amount remains the inventory/SLE authority. Micro-residual `amount − valuation_rate × qty` may be non-zero (±1 typical) on some voucher shapes; never force `amount := valuation_rate × qty`.

### Mandatory example

```
qty = 1245
raw_rate = 2207006.162248996
basic_rate = 2207006
basic_amount = 1245 × 2207006 = 2747722470
```

Not `2747722672` (qty × fractional rate).

## Accounting policy (separated)

| Concept | Destination |
|---|---|
| **A. Inventory valuation difference** (`value_difference`, incoming ≠ outgoing) | **Company Stock Adjustment Account** (`Company.stock_adjustment_account`) — vanilla ERPNext |
| **B. General Ledger debit/credit balancing** | **Company Round Off Account** (`Company.round_off_account`) — vanilla `make_round_off_gle` |

### Manufacture / Repack

Integer-rate policy may create `incoming ≠ outgoing`. That gap is a **stock valuation difference** and follows ERPNext Manufacture/Repack accounting → **Stock Adjustment**.

**Round Off Account must NOT compensate IRR integer-rate valuation for Manufacture / Repack stock movements.**

### Other Stock Entry / PR / SR residual Round Off (non-Manufacture)

Where a safe non-inventory GL leg exists (and is not Stock Adjustment, and Additional Cost
expense remains visible after reclass), an IRR `amount − valuation_rate×qty` residual may
post to Company Round Off.

- **Stock Adjustment** is never used as the Round Off reclassification partner.
- **Additional Cost** expense may be reclassified only when its GL magnitude strictly exceeds
  the residual (so Add Cost remains on the voucher).
- If no safe partner remains, Round Off residual is **soft-skipped**; inventory amounts stay
  authoritative and the vanilla GL stays balanced.

## Detection

Read-only: `domain/irr_rate_first_detector.py` → `detect_fractional_irr_stock_entry_rates`.
